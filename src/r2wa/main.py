"""Einstiegspunkt der Anwendung."""

from __future__ import annotations

import argparse
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from . import APP_ID, __version__  # noqa: E402
from .window import Window  # noqa: E402

#: Mindestversionen. Die Item-Liste nutzt Abschnitte in Gtk.ListView und
#: Gtk.ListBox.remove_all(), beides ab GTK 4.12; Adw.AboutDialog kam mit
#: libadwaita 1.5 (GNOME 46). Damit ist GNOME 46 die Untergrenze.
REQUIRED_GTK = (4, 12)
REQUIRED_ADW = (1, 5)


class Application(Adw.Application):
    """Die Anwendung selbst."""

    def __init__(self, save_dir: str | None = None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._save_dir = save_dir
        self._window: Window | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        self._add_action("quit", lambda *_: self.quit(), ["<Control>q", "<Control>w"])
        self._add_action("about", lambda *_: self._show_about())

    def do_activate(self) -> None:
        if self._window is None:
            self._window = Window(application=self, save_dir=self._save_dir)
            self._add_window_actions(self._window)
        self._window.present()

    def _add_action(self, name: str, callback, accels: list[str] | None = None) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def _add_window_actions(self, window: Window) -> None:
        for name, callback, accels in (
            ("reload", lambda *_: window.load(), ["<Control>r", "F5"]),
            ("open-folder", lambda *_: window.choose_folder(), ["<Control>o"]),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            window.add_action(action)
            self.set_accels_for_action(f"win.{name}", accels)

    def _show_about(self) -> None:
        about = Adw.AboutDialog(
            application_name="Remnant 2 Analyzer",
            application_icon=APP_ID,
            version=__version__,
            comments=(
                "Zeigt für jeden Charakter, welche Items gefunden sind und "
                "welche noch fehlen, und was in den gerollten Welten steckt."
            ),
            license_type=Gtk.License.MIT_X11,
            developer_name="RustySilver",
        )
        about.add_credit_section(
            "Savegame-Auswertung",
            [
                "AndrewSav https://github.com/AndrewSav/lib.remnant2.analyzer",
                "t1nky https://github.com/t1nky/remnant-item-finder",
            ],
        )
        about.present(self._window)


def _check_versions() -> str | None:
    """Pruefe die Laufzeitversionen; gib eine Meldung zurueck, wenn zu alt."""
    gtk_version = (Gtk.get_major_version(), Gtk.get_minor_version())
    adw_version = (Adw.get_major_version(), Adw.get_minor_version())

    if gtk_version < REQUIRED_GTK:
        return (
            f"GTK {REQUIRED_GTK[0]}.{REQUIRED_GTK[1]} oder neuer wird benötigt, "
            f"gefunden wurde {gtk_version[0]}.{gtk_version[1]}."
        )
    if adw_version < REQUIRED_ADW:
        return (
            f"libadwaita {REQUIRED_ADW[0]}.{REQUIRED_ADW[1]} oder neuer wird "
            f"benötigt, gefunden wurde {adw_version[0]}.{adw_version[1]}."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="r2wa",
        description="Remnant 2 World & Item Analyzer für GNOME.",
    )
    parser.add_argument(
        "save_dir",
        nargs="?",
        help="Savegame-Verzeichnis (sonst wird automatisch gesucht)",
    )
    parser.add_argument("--version", action="version", version=f"r2wa {__version__}")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    problem = _check_versions()
    if problem:
        print(problem, file=sys.stderr)
        return 1

    return Application(save_dir=args.save_dir).run([])


if __name__ == "__main__":
    raise SystemExit(main())
