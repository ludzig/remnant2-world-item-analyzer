"""Invoking the C# parser and evaluating its JSON output.

The parser is a standalone binary that writes nothing but JSON to stdout.
Running it as a separate process has a practical advantage: if the parser
falls over on a broken save game, the UI keeps running and can display the
error.

The synchronous path (:func:`analyze`) is for tests and the command line;
the UI uses :func:`analyze_async` so it never blocks the GTK main loop.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .models import Analysis

#: Name of the parser binary; with .exe on Windows.
PARSER_NAME = "r2wa-parser"

#: Root of the working directory, two levels up from src/r2wa/.
#: Kept as a constant so tests can redirect the search into the repo.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Maximum time a parser run may take. Five characters take a few seconds;
#: anything beyond that points to a problem.
DEFAULT_TIMEOUT = 120.0


class ParserError(Exception):
    """The parser could not deliver an analysis."""

    def __init__(self, message: str, kind: str = "unknown", detail: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail


class ParserNotFoundError(ParserError):
    """The parser binary was not found."""

    def __init__(self, searched: list[Path]):
        locations = "\n  ".join(str(p) for p in searched)
        super().__init__(
            "The parser binary was not found. Searched in:\n  " + locations,
            kind="parser_not_found",
        )
        self.searched = searched


def find_parser(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Find the parser binary.

    Order: explicit path, ``R2WA_PARSER`` environment variable, the repo's
    build directory, then ``PATH``. This way it works both when starting
    from the working directory and after a later installation.
    """
    candidates: list[Path] = []

    if explicit:
        candidates.append(Path(explicit))

    from_env = os.environ.get("R2WA_PARSER")
    if from_env:
        candidates.append(Path(from_env))

    for name in (PARSER_NAME, PARSER_NAME + ".exe"):
        candidates.append(REPO_ROOT / "build" / "parser" / name)
        candidates.append(REPO_ROOT / "parser" / "bin" / "Release" / "net10.0" / name)

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    on_path = shutil.which(PARSER_NAME)
    if on_path:
        return Path(on_path)

    raise ParserNotFoundError(candidates)


def build_command(save_dir: str | os.PathLike[str], parser: Path) -> list[str]:
    """Build the command line for an analysis run."""
    return [str(parser), "analyze", "--save-dir", str(save_dir)]


def parse_output(stdout: str) -> Analysis:
    """Evaluate the parser's JSON output.

    Raises :class:`ParserError` if the parser reported an error, the output
    isn't JSON, or the schema doesn't match this application.
    """
    text = stdout.strip()
    if not text:
        raise ParserError("The parser produced no output.", kind="empty_output")

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParserError(
            f"The parser's output is not valid JSON: {exc}",
            kind="invalid_json",
            detail=text[:2000],
        ) from exc

    if not isinstance(data, dict):
        raise ParserError("Unexpected structure in the parser output.", kind="invalid_json")

    if "error" in data:
        error = data["error"] or {}
        raise ParserError(
            error.get("message", "Unknown error in the parser."),
            kind=error.get("kind", "unknown"),
            detail=error.get("detail"),
        )

    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ParserError(
            f"The parser returned schema version {version}, expected "
            f"{SCHEMA_VERSION}. Please rebuild the parser (just build-parser).",
            kind="schema_mismatch",
        )

    return Analysis.from_json(data)


def analyze(
    save_dir: str | os.PathLike[str],
    parser: str | os.PathLike[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Analysis:
    """Analyze a save game directory (blocking)."""
    binary = find_parser(parser)

    try:
        completed = subprocess.run(  # noqa: S603 - fixed binary, no shell
            build_command(save_dir, binary),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ParserError(
            f"The parser did not respond within {timeout:.0f}s.", kind="timeout"
        ) from exc
    except OSError as exc:
        raise ParserError(f"The parser could not be started: {exc}", kind="spawn_failed") from exc

    try:
        return parse_output(completed.stdout)
    except ParserError:
        # On a crash without JSON on stdout, stderr is the only clue left.
        if completed.returncode != 0 and not completed.stdout.strip():
            raise ParserError(
                f"The parser exited with code {completed.returncode}.",
                kind="crashed",
                detail=(completed.stderr or "").strip()[:2000],
            ) from None
        raise


def analyze_async(
    save_dir: str | os.PathLike[str],
    on_success: Callable[[Analysis], None],
    on_error: Callable[[ParserError], None],
    parser: str | os.PathLike[str] | None = None,
) -> None:
    """Analyze in the background and report the result on the GTK main loop.

    Imported here on purpose: the data layer should stay usable without
    PyGObject, so it can be tested without GTK.
    """
    from gi.repository import Gio, GLib

    try:
        binary = find_parser(parser)
    except ParserError as exc:
        # Python discards the name at the end of the except block; without
        # this binding it would be gone by the time the callback runs.
        failure = exc

        def report_failure() -> bool:
            on_error(failure)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(report_failure)
        return

    process = Gio.Subprocess.new(
        build_command(save_dir, binary),
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
    )

    def finished(proc: Gio.Subprocess, result: Gio.AsyncResult) -> None:
        try:
            _, stdout, stderr = proc.communicate_utf8_finish(result)
        except GLib.Error as error:
            on_error(
                ParserError(
                    f"The parser could not be started: {error.message}", kind="spawn_failed"
                )
            )
            return

        try:
            analysis = parse_output(stdout or "")
        except ParserError as exc:
            if not (stdout or "").strip() and stderr:
                exc.detail = exc.detail or stderr.strip()[:2000]
            on_error(exc)
            return

        on_success(analysis)

    process.communicate_utf8_async(None, None, finished)


def main() -> int:
    """``python -m r2wa.parser_bridge <directory>`` - analyze from the console."""
    import sys

    from .discovery import discover

    if len(sys.argv) > 1:
        save_dir: str | None = sys.argv[1]
    else:
        locations = discover()
        if not locations:
            print("No save game directory found.", file=sys.stderr)
            return 1
        save_dir = str(locations[0].path)
        print(f"Using {save_dir}", file=sys.stderr)

    try:
        analysis = analyze(save_dir)
    except ParserError as exc:
        print(f"Error ({exc.kind}): {exc}", file=sys.stderr)
        if exc.detail:
            print(exc.detail, file=sys.stderr)
        return 1

    print(f"Catalog: {len(analysis.catalog)} items, {len(analysis.characters)} characters")
    for character in analysis.characters:
        counts = character.counts
        print(
            f"  Slot {character.index}: {character.title:32s} "
            f"{counts.acquired:4d}/{counts.total} ({counts.fraction:5.1%})"
        )
    for warning in analysis.warnings:
        print(f"  ! {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
