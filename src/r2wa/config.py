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


def config_dir() -> Path:
    """Verzeichnis nach XDG-Konvention, ohne Abhaengigkeit von GLib."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "r2wa"


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
        target = path or (config_dir() / CONFIG_FILE)
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
        target = path or (config_dir() / CONFIG_FILE)
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
