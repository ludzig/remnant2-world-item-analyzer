"""Small, file-based settings.

Deliberately not GSettings: its schema would first have to be compiled and
installed system-wide, which conflicts with starting directly from the
working directory. A JSON file in the user's config directory is stored
instead.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = "settings.json"


def user_home() -> Path | None:
    """Home directory, or ``None`` if it cannot be determined.

    ``Path.home()`` raises a RuntimeError if neither HOME nor USERPROFILE is
    set. That practically never happens on a desktop, but it can happen in
    stripped-down environments - and it must not prevent the application
    from starting.
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
    """Directory following the XDG convention, without depending on GLib.

    ``None`` means: there is no place to save. The application then keeps
    running without remembered settings.
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "r2wa"

    home = user_home()
    return home / ".config" / "r2wa" if home else None


@dataclass(slots=True)
class Settings:
    """What the application remembers between two runs."""

    save_dir: str | None = None
    """Last manually chosen save game directory."""

    character_index: int | None = None
    """Last viewed character."""

    window_width: int | None = None
    """Last window width, unmaximized."""

    window_height: int | None = None
    """Last window height, unmaximized."""

    window_maximized: bool = False
    """Whether the window was maximized on close.

    Only the maximized flag and the unmaximized size are kept - not a
    screen position. GTK4 deliberately has no API for that under Wayland;
    the compositor, not the application, decides where a window appears.
    """

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Read the settings; malformed files are ignored."""
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
        width = data.get("window_width")
        height = data.get("window_height")
        return cls(
            save_dir=save_dir if isinstance(save_dir, str) else None,
            character_index=index if isinstance(index, int) else None,
            window_width=width if isinstance(width, int) else None,
            window_height=height if isinstance(height, int) else None,
            window_maximized=bool(data.get("window_maximized", False)),
        )

    def save(self, path: Path | None = None) -> None:
        """Write the settings.

        A failure here is no reason to abort - at worst the folder has to be
        chosen again on the next start.
        """
        target = path or _default_path()
        if target is None:
            return

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "save_dir": self.save_dir,
                "character_index": self.character_index,
                "window_width": self.window_width,
                "window_height": self.window_height,
                "window_maximized": self.window_maximized,
            }
            # Write next to the target first, then replace: a crash in the
            # middle doesn't leave a half-written file behind.
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            pass


def _default_path() -> Path | None:
    directory = config_dir()
    return directory / CONFIG_FILE if directory else None
