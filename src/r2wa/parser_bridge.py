"""Aufruf des C#-Parsers und Auswertung seiner JSON-Ausgabe.

Der Parser ist ein eigenstaendiges Binary, das auf stdout ausschliesslich JSON
schreibt. Die Trennung als Subprozess hat einen praktischen Vorteil: faellt der
Parser bei einem kaputten Savegame um, bleibt die Oberflaeche stehen und kann
den Fehler anzeigen.

Der synchrone Weg (:func:`analyze`) ist fuer Tests und Kommandozeile gedacht,
die Oberflaeche benutzt :func:`analyze_async` und blockiert damit nie den
GTK-Main-Loop.
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

#: Name des Parser-Binaries; unter Windows mit .exe.
PARSER_NAME = "r2wa-parser"

#: Wurzel des Arbeitsverzeichnisses, von src/r2wa/ aus zwei Ebenen hoeher.
#: Als Konstante gefuehrt, damit Tests die Suche im Repo umlenken koennen.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Wie lange ein Parser-Lauf hoechstens dauern darf. Fuenf Charaktere brauchen
#: wenige Sekunden; alles darueber deutet auf ein Problem hin.
DEFAULT_TIMEOUT = 120.0


class ParserError(Exception):
    """Der Parser konnte die Analyse nicht liefern."""

    def __init__(self, message: str, kind: str = "unknown", detail: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail


class ParserNotFoundError(ParserError):
    """Das Parser-Binary wurde nicht gefunden."""

    def __init__(self, searched: list[Path]):
        locations = "\n  ".join(str(p) for p in searched)
        super().__init__(
            "Das Parser-Binary wurde nicht gefunden. Gesucht wurde in:\n  " + locations,
            kind="parser_not_found",
        )
        self.searched = searched


def find_parser(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Finde das Parser-Binary.

    Reihenfolge: expliziter Pfad, Umgebungsvariable ``R2WA_PARSER``, das
    Build-Verzeichnis des Repos, danach ``PATH``. Damit funktioniert sowohl der
    Start aus dem Arbeitsverzeichnis als auch eine spaetere Installation.
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
    """Baue die Kommandozeile fuer eine Analyse."""
    return [str(parser), "analyze", "--save-dir", str(save_dir)]


def parse_output(stdout: str) -> Analysis:
    """Werte die JSON-Ausgabe des Parsers aus.

    Wirft :class:`ParserError`, wenn der Parser einen Fehler gemeldet hat, die
    Ausgabe kein JSON ist oder das Schema nicht zu dieser Anwendung passt.
    """
    text = stdout.strip()
    if not text:
        raise ParserError("Der Parser hat nichts ausgegeben.", kind="empty_output")

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParserError(
            f"Die Ausgabe des Parsers ist kein gueltiges JSON: {exc}",
            kind="invalid_json",
            detail=text[:2000],
        ) from exc

    if not isinstance(data, dict):
        raise ParserError("Unerwartete Struktur in der Parser-Ausgabe.", kind="invalid_json")

    if "error" in data:
        error = data["error"] or {}
        raise ParserError(
            error.get("message", "Unbekannter Fehler im Parser."),
            kind=error.get("kind", "unknown"),
            detail=error.get("detail"),
        )

    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ParserError(
            f"Der Parser liefert Schema-Version {version}, erwartet wird "
            f"{SCHEMA_VERSION}. Bitte den Parser neu bauen (just build-parser).",
            kind="schema_mismatch",
        )

    return Analysis.from_json(data)


def analyze(
    save_dir: str | os.PathLike[str],
    parser: str | os.PathLike[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Analysis:
    """Analysiere ein Savegame-Verzeichnis (blockierend)."""
    binary = find_parser(parser)

    try:
        completed = subprocess.run(  # noqa: S603 - festes Binary, keine Shell
            build_command(save_dir, binary),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ParserError(
            f"Der Parser hat nach {timeout:.0f} s nicht geantwortet.", kind="timeout"
        ) from exc
    except OSError as exc:
        raise ParserError(
            f"Der Parser liess sich nicht starten: {exc}", kind="spawn_failed"
        ) from exc

    try:
        return parse_output(completed.stdout)
    except ParserError:
        # Bei einem Absturz ohne JSON auf stdout ist stderr die einzige Spur.
        if completed.returncode != 0 and not completed.stdout.strip():
            raise ParserError(
                f"Der Parser wurde mit Code {completed.returncode} beendet.",
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
    """Analysiere im Hintergrund und melde das Ergebnis im GTK-Main-Loop.

    Wird bewusst erst hier importiert: die Datenschicht soll ohne PyGObject
    nutzbar bleiben, damit sie sich ohne GTK testen laesst.
    """
    from gi.repository import Gio, GLib

    try:
        binary = find_parser(parser)
    except ParserError as exc:
        # Python loescht den Namen am Ende des except-Blocks; ohne diese
        # Bindung waere er im Callback nicht mehr da.
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
                    f"Der Parser liess sich nicht starten: {error.message}", kind="spawn_failed"
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
    """``python -m r2wa.parser_bridge <verzeichnis>`` - Analyse auf der Konsole."""
    import sys

    from .discovery import discover

    if len(sys.argv) > 1:
        save_dir: str | None = sys.argv[1]
    else:
        locations = discover()
        if not locations:
            print("Kein Savegame-Verzeichnis gefunden.", file=sys.stderr)
            return 1
        save_dir = str(locations[0].path)
        print(f"Verwende {save_dir}", file=sys.stderr)

    try:
        analysis = analyze(save_dir)
    except ParserError as exc:
        print(f"Fehler ({exc.kind}): {exc}", file=sys.stderr)
        if exc.detail:
            print(exc.detail, file=sys.stderr)
        return 1

    print(f"Katalog: {len(analysis.catalog)} Items, {len(analysis.characters)} Charaktere")
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
