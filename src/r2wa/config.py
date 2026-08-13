"""Kleine, dateibasierte Einstellungen.

Bewusst kein GSettings: dessen Schema muesste erst kompiliert und systemweit
installiert werden, was dem Start direkt aus dem Arbeitsverzeichnis
widerspricht. Gespeichert wird deshalb eine JSON-Datei im
Konfigurationsverzeichnis des Benutzers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = "settings.json"


def user_home() -> Path | None:
    """Home-Verzeichnis, oder ``None`` wenn es sich nicht bestimmen laesst.

    ``Path.home()`` wirft eine RuntimeError, wenn weder HOME noch USERPROFILE
    gesetzt sind. Das kommt auf einem Desktop praktisch nicht vor, wohl aber
    in abgemagerten Umgebungen - und darf die Anwendung nicht am Start
    hindern.
    """
    for variable in ("HOME", "USERPROFILE"):
        value = os.environ.get(variable)
        if value:
            return Path(value)
    try:
        return Path.home()
    except RuntimeError:
        return None


def config_dir() -> Path | None:
    """Verzeichnis nach XDG-Konvention, ohne Abhaengigkeit von GLib.

    ``None`` bedeutet: es gibt keinen Ort zum Speichern. Die Anwendung laeuft
    dann ohne gemerkte Einstellungen weiter.
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "r2wa"

    home = user_home()
    return home / ".config" / "r2wa" if home else None


@dataclass(slots=True)
class Settings:
    """Was die Anwendung sich zwischen zwei Starts merkt."""

    save_dir: str | None = None
    """Zuletzt von Hand gewaehltes Savegame-Verzeichnis."""

    character_index: int | None = None
    """Zuletzt betrachteter Charakter."""

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Lies die Einstellungen; fehlerhafte Dateien werden ignoriert."""
        target = path or _default_path()
        if target is None:
            return cls()

        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        if not isinstance(data, dict):
            return cls()

        save_dir = data.get("save_dir")
        index = data.get("character_index")
        return cls(
            save_dir=save_dir if isinstance(save_dir, str) else None,
            character_index=index if isinstance(index, int) else None,
        )

    def save(self, path: Path | None = None) -> None:
        """Schreibe die Einstellungen.

        Ein Fehlschlag ist kein Grund abzubrechen - im schlimmsten Fall muss
        der Ordner beim naechsten Start erneut gewaehlt werden.
        """
        target = path or _default_path()
        if target is None:
            return

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = {"save_dir": self.save_dir, "character_index": self.character_index}
            # Erst daneben schreiben, dann ersetzen: ein Absturz mittendrin
            # hinterlaesst so keine halbe Datei.
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            pass


def _default_path() -> Path | None:
    directory = config_dir()
    return directory / CONFIG_FILE if directory else None
