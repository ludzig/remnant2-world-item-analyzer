"""Discovering the Remnant 2 save game directories.

On Linux the saves live inside the game's Proton prefix. The path there
varies with the Steam installation type (native, Flatpak) and library
folder, and the Steam ID in the last segment differs per account anyway.
This module therefore collects all plausible candidates and validates them.

All functions take the roots to search as parameters, so the search can run
against a rebuilt directory tree in tests.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import user_home

#: Steam app ID of Remnant II - names the compatdata folder of the prefix.
GAME_APP_ID = "1282100"

#: Path from the compatdata folder of the game to the directory of Steam accounts.
SAVE_SUBPATH = ("pfx", "drive_c", "users", "steamuser", "Saved Games", "Remnant2", "Steam")

#: Path from the Windows user profile - for development/testing on Windows.
WINDOWS_SUBPATH = ("Saved Games", "Remnant2", "Steam")

PROFILE_FILE = "profile.sav"
SLOT_PATTERN = re.compile(r"^save_(\d+)\.sav$", re.IGNORECASE)

#: Steam roots relative to the home directory, in order of likelihood.
_STEAM_ROOT_CANDIDATES = (
    ".steam/steam",
    ".steam/root",
    ".local/share/Steam",
    ".var/app/com.valvesoftware.Steam/data/Steam",
    ".var/app/com.valvesoftware.Steam/.local/share/Steam",
)

#: libraryfolders.vdf has one "path" line per library.
_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"')


@dataclass(frozen=True, slots=True)
class SaveLocation:
    """A validated save game directory of a Steam account."""

    path: Path
    steam_id: str
    source: str
    """Where the find came from: ``proton``, ``windows`` or ``manual``."""
    profile: Path
    slots: tuple[Path, ...]
    """The ``save_N.sav`` files, sorted ascending by slot number."""

    @property
    def slot_count(self) -> int:
        return len(self.slots)

    @property
    def modified(self) -> float:
        """Modification time of the profile file - used as the sort key."""
        try:
            return self.profile.stat().st_mtime
        except OSError:
            return 0.0

    def __str__(self) -> str:
        return f"{self.path} ({self.slot_count} slots, {self.source})"


def validate(path: Path, source: str = "manual") -> SaveLocation | None:
    """Check whether *path* is a save game directory.

    Requires a ``profile.sav`` and at least one ``save_N.sav``. A directory
    without slots belongs to an account that has started the game but never
    created a character - useless for the analysis, so not a match.
    """
    if not path.is_dir():
        return None

    profile = path / PROFILE_FILE
    if not profile.is_file():
        return None

    slots: list[tuple[int, Path]] = []
    try:
        entries = list(path.iterdir())
    except OSError:
        return None

    for entry in entries:
        match = SLOT_PATTERN.match(entry.name)
        if match and entry.is_file():
            slots.append((int(match.group(1)), entry))

    if not slots:
        return None

    slots.sort(key=lambda item: item[0])
    return SaveLocation(
        path=path,
        steam_id=path.name,
        source=source,
        profile=profile,
        slots=tuple(slot for _, slot in slots),
    )


def steam_roots(home: Path) -> list[Path]:
    """Return the existing Steam installation roots under *home*."""
    roots: list[Path] = []
    for candidate in _STEAM_ROOT_CANDIDATES:
        root = home / candidate
        if (root / "steamapps").is_dir():
            roots.append(root)
    return _dedupe(roots)


def library_folders(root: Path) -> list[Path]:
    """Read additional Steam library folders from ``libraryfolders.vdf``.

    The return value does not include *root* itself; only the further
    libraries listed there. If the file is unreadable or unexpectedly
    formatted, this is silently treated as "no further libraries" - the
    discovery should not fail because of it.
    """
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        content = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    folders = [Path(match) for match in _VDF_PATH.findall(content)]
    return _dedupe(folder for folder in folders if (folder / "steamapps").is_dir())


def compat_save_dirs(library: Path) -> list[Path]:
    """Return the account directories in the Proton prefix of a library."""
    base = library.joinpath("steamapps", "compatdata", GAME_APP_ID, *SAVE_SUBPATH)
    if not base.is_dir():
        return []
    try:
        return sorted(entry for entry in base.iterdir() if entry.is_dir())
    except OSError:
        return []


def discover(
    home: Path | None = None,
    extra_paths: tuple[Path, ...] | list[Path] = (),
) -> list[SaveLocation]:  # noqa: C901 - the candidate search is deliberately linear
    """Find all save game directories.

    *extra_paths* are manually configured directories; they are checked
    first and appear in the result before the automatically found ones.
    Automatic hits are sorted by modification time of the profile file, so
    the most recently played account is on top.

    Multiple hits are deliberately all returned instead of silently picking
    the first one - with two Steam accounts on one machine the choice would
    otherwise be a guess.

    If the home directory cannot be determined, only the automatic search is
    skipped; paths passed in explicitly are still checked.
    """
    home = home or user_home()
    found: list[SaveLocation] = []
    seen: set[Path] = set()

    for path in extra_paths:
        location = validate(Path(path), source="manual")
        if location and location.path.resolve() not in seen:
            seen.add(location.path.resolve())
            found.append(location)

    if home is None:
        return found

    auto: list[SaveLocation] = []
    for candidate, source in _auto_candidates(home):
        location = validate(candidate, source=source)
        if not location:
            continue
        resolved = location.path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        auto.append(location)

    auto.sort(key=lambda loc: loc.modified, reverse=True)
    return found + auto


def _auto_candidates(home: Path) -> list[tuple[Path, str]]:
    """Collect all directories to check, together with their origin."""
    candidates: list[tuple[Path, str]] = []

    libraries: list[Path] = []
    for root in steam_roots(home):
        libraries.append(root)
        libraries.extend(library_folders(root))

    for library in _dedupe(libraries):
        for save_dir in compat_save_dirs(library):
            candidates.append((save_dir, "proton"))

    # On Windows the same tree lives directly in the user profile. That is
    # irrelevant for the target platform, but makes the discovery testable
    # on the development machine.
    if sys.platform == "win32":
        windows_base = home.joinpath(*WINDOWS_SUBPATH)
        if windows_base.is_dir():
            try:
                for entry in sorted(windows_base.iterdir()):
                    if entry.is_dir():
                        candidates.append((entry, "windows"))
            except OSError:
                pass

    return candidates


def _dedupe(paths) -> list[Path]:
    """Remove duplicates stably, resolved through symlinks."""
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def main() -> int:
    """``python -m r2wa.discovery`` - shows the directories found."""
    extra = [Path(p) for p in os.environ.get("R2WA_SAVE_DIR", "").split(os.pathsep) if p]
    locations = discover(extra_paths=tuple(extra))
    if not locations:
        print("No Remnant 2 save game directory found.", file=sys.stderr)
        return 1
    for location in locations:
        print(location)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
