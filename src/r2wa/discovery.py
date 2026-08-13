"""Auffinden der Remnant-2-Savegame-Verzeichnisse.

Unter Linux liegen die Saves im Proton-Prefix des Spiels. Der Pfad dorthin
variiert nach Steam-Installationsart (nativ, Flatpak) und Library-Ordner, die
Steam-ID im letzten Segment ist ohnehin pro Account verschieden. Dieses Modul
sammelt daher alle plausiblen Kandidaten ein und validiert sie.

Alle Funktionen nehmen die zu durchsuchenden Wurzeln als Parameter entgegen,
damit die Suche in Tests gegen einen nachgebauten Verzeichnisbaum laufen kann.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: Steam-App-ID von Remnant II - benennt den compatdata-Ordner des Prefix.
GAME_APP_ID = "1282100"

#: Pfad vom compatdata-Ordner des Spiels bis zum Verzeichnis der Steam-Accounts.
SAVE_SUBPATH = ("pfx", "drive_c", "users", "steamuser", "Saved Games", "Remnant2", "Steam")

#: Pfad ab dem Windows-Benutzerprofil - fuer Entwicklung/Test auf Windows.
WINDOWS_SUBPATH = ("Saved Games", "Remnant2", "Steam")

PROFILE_FILE = "profile.sav"
SLOT_PATTERN = re.compile(r"^save_(\d+)\.sav$", re.IGNORECASE)

#: Steam-Wurzeln relativ zum Home-Verzeichnis, in Reihenfolge der Ueblichkeit.
_STEAM_ROOT_CANDIDATES = (
    ".steam/steam",
    ".steam/root",
    ".local/share/Steam",
    ".var/app/com.valvesoftware.Steam/data/Steam",
    ".var/app/com.valvesoftware.Steam/.local/share/Steam",
)

#: In libraryfolders.vdf steht je Library eine "path"-Zeile.
_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"')


@dataclass(frozen=True, slots=True)
class SaveLocation:
    """Ein validiertes Savegame-Verzeichnis eines Steam-Accounts."""

    path: Path
    steam_id: str
    source: str
    """Woher der Fund stammt: ``proton``, ``windows`` oder ``manual``."""
    profile: Path
    slots: tuple[Path, ...]
    """Die ``save_N.sav``-Dateien, aufsteigend nach Slot-Nummer."""

    @property
    def slot_count(self) -> int:
        return len(self.slots)

    @property
    def modified(self) -> float:
        """Aenderungszeit der Profildatei - dient als Sortierkriterium."""
        try:
            return self.profile.stat().st_mtime
        except OSError:
            return 0.0

    def __str__(self) -> str:
        return f"{self.path} ({self.slot_count} Slots, {self.source})"


def validate(path: Path, source: str = "manual") -> SaveLocation | None:
    """Pruefe, ob *path* ein Savegame-Verzeichnis ist.

    Gefordert sind eine ``profile.sav`` und mindestens ein ``save_N.sav``.
    Ein Verzeichnis ohne Slots gehoert zu einem Account, der das Spiel zwar
    gestartet, aber nie einen Charakter angelegt hat - fuer die Analyse
    wertlos, deshalb kein Treffer.
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
    """Liefere die existierenden Steam-Installationswurzeln unter *home*."""
    roots: list[Path] = []
    for candidate in _STEAM_ROOT_CANDIDATES:
        root = home / candidate
        if (root / "steamapps").is_dir():
            roots.append(root)
    return _dedupe(roots)


def library_folders(root: Path) -> list[Path]:
    """Lies zusaetzliche Steam-Library-Ordner aus ``libraryfolders.vdf``.

    Der Rueckgabewert enthaelt *root* selbst nicht; nur die dort eingetragenen
    weiteren Bibliotheken. Ist die Datei nicht lesbar oder unerwartet
    formatiert, wird das still als "keine weiteren Bibliotheken" behandelt -
    die Discovery soll daran nicht scheitern.
    """
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        content = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    folders = [Path(match) for match in _VDF_PATH.findall(content)]
    return _dedupe(folder for folder in folders if (folder / "steamapps").is_dir())


def compat_save_dirs(library: Path) -> list[Path]:
    """Liefere die Account-Verzeichnisse im Proton-Prefix einer Library."""
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
) -> list[SaveLocation]:
    """Finde alle Savegame-Verzeichnisse.

    *extra_paths* sind manuell konfigurierte Verzeichnisse; sie werden zuerst
    geprueft und erscheinen im Ergebnis vor den automatisch gefundenen.
    Automatische Treffer sind nach Aenderungszeit der Profildatei sortiert,
    der zuletzt bespielte Account steht also oben.

    Mehrere Treffer werden bewusst alle zurueckgegeben statt still den ersten
    zu waehlen - bei zwei Steam-Accounts auf einer Maschine waere die Auswahl
    sonst geraten.
    """
    home = home or Path.home()
    found: list[SaveLocation] = []
    seen: set[Path] = set()

    for path in extra_paths:
        location = validate(Path(path), source="manual")
        if location and location.path.resolve() not in seen:
            seen.add(location.path.resolve())
            found.append(location)

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
    """Sammle alle zu pruefenden Verzeichnisse samt ihrer Herkunft."""
    candidates: list[tuple[Path, str]] = []

    libraries: list[Path] = []
    for root in steam_roots(home):
        libraries.append(root)
        libraries.extend(library_folders(root))

    for library in _dedupe(libraries):
        for save_dir in compat_save_dirs(library):
            candidates.append((save_dir, "proton"))

    # Auf Windows liegt der gleiche Baum direkt im Benutzerprofil. Das ist fuer
    # die Zielplattform irrelevant, macht aber die Discovery auf dem
    # Entwicklungsrechner testbar.
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
    """Entferne Duplikate stabil, aufgeloest ueber Symlinks."""
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
    """``python -m r2wa.discovery`` - zeigt die gefundenen Verzeichnisse."""
    extra = [Path(p) for p in os.environ.get("R2WA_SAVE_DIR", "").split(os.pathsep) if p]
    locations = discover(extra_paths=tuple(extra))
    if not locations:
        print("Kein Remnant-2-Savegame-Verzeichnis gefunden.", file=sys.stderr)
        return 1
    for location in locations:
        print(location)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
