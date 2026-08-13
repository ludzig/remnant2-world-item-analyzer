"""Das Hauptfenster: Charakterliste links, Items und Welten rechts."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402

from .config import Settings  # noqa: E402
from .discovery import SaveLocation, discover  # noqa: E402
from .models import Analysis, Character, format_playtime  # noqa: E402
from .parser_bridge import ParserError, analyze_async  # noqa: E402
from .views.items import ItemsView  # noqa: E402
from .views.worlds import WorldsView  # noqa: E402

#: Wartezeit nach einer Dateiaenderung, bevor neu analysiert wird. Das Spiel
#: schreibt beim Speichern mehrere Dateien kurz hintereinander.
RELOAD_DEBOUNCE_MS = 2000


class Window(Adw.ApplicationWindow):
    """Hauptfenster der Anwendung."""

    __gtype_name__ = "R2waWindow"

    def __init__(self, application: Adw.Application, save_dir: str | None = None):
        super().__init__(application=application, title="Remnant 2 Analyzer")
        self.set_default_size(1100, 760)

        self._analysis: Analysis | None = None
        self._location: SaveLocation | None = None
        self._settings = Settings.load()
        # Ein Pfad von der Kommandozeile gilt nur fuer diesen Start und wird
        # nicht gespeichert; die gemerkte Wahl bleibt davon unberuehrt.
        self._explicit_save_dir = save_dir or self._settings.save_dir
        self._monitor: Gio.FileMonitor | None = None
        self._reload_source: int | None = None
        self._loading = False

        self._build_ui()
        self.load()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._items_view = ItemsView()
        self._worlds_view = WorldsView()

        # vexpand ist noetig, weil der Stack in einer Box unter dem Banner
        # sitzt und Box-Kinder sonst nur ihre Mindesthoehe bekommen.
        self._stack = Adw.ViewStack(vexpand=True)
        self._stack.add_titled_with_icon(
            self._items_view, "items", "Items", "view-list-bullet-symbolic"
        )
        self._stack.add_titled_with_icon(self._worlds_view, "worlds", "Welten", "map-symbolic")

        self._banner = Adw.Banner(revealed=False)
        self._banner.connect("button-clicked", lambda _b: self._banner.set_revealed(False))

        content_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_body.append(self._banner)
        content_body.append(self._stack)

        self._content_toolbar = Adw.ToolbarView(content=content_body)
        self._content_toolbar.add_top_bar(self._build_content_header())

        self._split = Adw.NavigationSplitView(
            sidebar=Adw.NavigationPage(title="Charaktere", child=self._build_sidebar()),
            content=Adw.NavigationPage(title="Übersicht", child=self._content_toolbar),
        )
        self._split.set_min_sidebar_width(260)
        self._split.set_max_sidebar_width(340)

        # Bei schmalem Fenster wird die Seitenleiste zur eigenen Seite.
        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720px"))
        breakpoint_.add_setter(self._split, "collapsed", True)
        self.add_breakpoint(breakpoint_)

        # Der Leerzustand ersetzt das gesamte Fenster, solange nichts geladen ist.
        self._placeholder = self._build_placeholder()

        self._root = Gtk.Stack()
        self._root.add_named(self._split, "content")
        self._root.add_named(self._placeholder, "placeholder")
        self._root.set_visible_child_name("placeholder")

        self.set_content(self._root)

    def _build_sidebar(self) -> Gtk.Widget:
        self._character_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.SINGLE,
            css_classes=["navigation-sidebar"],
        )
        self._character_list.connect("row-selected", self._on_character_selected)

        toolbar = Adw.ToolbarView(
            content=Gtk.ScrolledWindow(child=self._character_list, vexpand=True)
        )

        header = Adw.HeaderBar()
        header.pack_end(self._build_menu_button())
        toolbar.add_top_bar(header)

        return toolbar

    def _build_content_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()

        self._switcher = Adw.ViewSwitcher(stack=self._stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self._switcher)

        self._reload_button = Gtk.Button(
            icon_name="view-refresh-symbolic",
            tooltip_text="Savegame neu einlesen",
        )
        self._reload_button.connect("clicked", lambda _b: self.load())
        header.pack_start(self._reload_button)

        self._spinner = Gtk.Spinner(visible=False)
        header.pack_start(self._spinner)

        return header

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append("Ordner öffnen…", "win.open-folder")
        menu.append("Neu einlesen", "win.reload")
        menu.append("Über r2wa", "app.about")

        return Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            menu_model=menu,
            tooltip_text="Hauptmenü",
        )

    def _build_placeholder(self) -> Gtk.Widget:
        self._status = Adw.StatusPage(
            icon_name="folder-saved-search-symbolic",
            title="Kein Savegame gefunden",
            description=(
                "Es wurde kein Remnant-2-Savegame im Proton-Prefix gefunden. "
                "Wähle das Verzeichnis mit profile.sav von Hand aus."
            ),
        )

        button = Gtk.Button(
            label="Ordner wählen…",
            halign=Gtk.Align.CENTER,
            css_classes=["pill", "suggested-action"],
        )
        button.connect("clicked", lambda _b: self.choose_folder())
        self._status.set_child(button)

        toolbar = Adw.ToolbarView(content=self._status)
        header = Adw.HeaderBar()
        header.pack_end(self._build_menu_button())
        toolbar.add_top_bar(header)
        return toolbar

    # ------------------------------------------------------------------
    # Laden
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Suche ein Savegame und starte die Analyse."""
        if self._loading:
            return

        location = self._resolve_location()
        if location is None:
            self._show_placeholder(
                "Kein Savegame gefunden",
                "Es wurde kein Remnant-2-Savegame im Proton-Prefix gefunden. "
                "Wähle das Verzeichnis mit profile.sav von Hand aus.",
            )
            return

        self._location = location
        self._watch(location.path)
        self._start_analysis(location.path)

    def _resolve_location(self) -> SaveLocation | None:
        extra = (Path(self._explicit_save_dir),) if self._explicit_save_dir else ()
        locations = discover(extra_paths=extra)
        return locations[0] if locations else None

    def _start_analysis(self, path: Path) -> None:
        self._loading = True
        self._spinner.set_visible(True)
        self._spinner.start()
        self._reload_button.set_sensitive(False)

        analyze_async(path, self._on_analysis_ready, self._on_analysis_failed)

    def _finish_loading(self) -> None:
        self._loading = False
        self._spinner.stop()
        self._spinner.set_visible(False)
        self._reload_button.set_sensitive(True)

    def _on_analysis_ready(self, analysis: Analysis) -> None:
        self._finish_loading()
        self._analysis = analysis

        self._populate_characters(analysis)
        self._root.set_visible_child_name("content")

        if analysis.warnings:
            count = len(analysis.warnings)
            self._banner.set_title(
                f"{count} Hinweis{'e' if count != 1 else ''} beim Einlesen – "
                "einzelne Items konnten nicht vollständig ausgewertet werden."
            )
            self._banner.set_button_label("Ausblenden")
            self._banner.set_revealed(True)
        else:
            self._banner.set_revealed(False)

    def _on_analysis_failed(self, error: ParserError) -> None:
        self._finish_loading()

        if error.kind == "parser_not_found":
            description = (
                "Das Parser-Binary fehlt. Baue es mit\n\n"
                "    just build-parser\n\n"
                "oder setze R2WA_PARSER auf den Pfad des Binaries."
            )
        else:
            # Fehlertexte enthalten Pfade und Meldungen des Parsers;
            # Adw.StatusPage rendert die Beschreibung als Markup.
            description = GLib.markup_escape_text(str(error))

        self._show_placeholder("Analyse fehlgeschlagen", description)

    def _show_placeholder(self, title: str, description: str) -> None:
        self._status.set_title(title)
        self._status.set_description(description)
        self._root.set_visible_child_name("placeholder")

    # ------------------------------------------------------------------
    # Charakterliste
    # ------------------------------------------------------------------

    def _populate_characters(self, analysis: Analysis) -> None:
        previous = self._selected_index()

        self._character_list.remove_all()
        for character in analysis.characters:
            self._character_list.append(_CharacterRow(character, analysis))

        # Beim erneuten Einlesen bleibt die Auswahl stehen; beim ersten Start
        # zaehlt der zuletzt betrachtete Charakter, sonst der im Spiel aktive.
        row = None
        for candidate in (
            previous,
            self._settings.character_index,
            analysis.active_character_index,
        ):
            if candidate is not None and (row := self._row_for_index(candidate)) is not None:
                break

        row = row or self._character_list.get_row_at_index(0)
        if row is not None:
            self._character_list.select_row(row)
        else:
            self._show_character(None)

    def _selected_index(self) -> int | None:
        row = self._character_list.get_selected_row()
        return row.character.index if isinstance(row, _CharacterRow) else None

    def _row_for_index(self, index: int) -> Gtk.ListBoxRow | None:
        position = 0
        while (row := self._character_list.get_row_at_index(position)) is not None:
            if isinstance(row, _CharacterRow) and row.character.index == index:
                return row
            position += 1
        return None

    def _on_character_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        character = row.character if isinstance(row, _CharacterRow) else None
        if character is not None:
            self._settings.character_index = character.index
        self._show_character(character)

    def _show_character(self, character: Character | None) -> None:
        self._items_view.set_analysis(self._analysis, character)
        self._worlds_view.set_character(character)

    # ------------------------------------------------------------------
    # Ordnerauswahl und Dateiueberwachung
    # ------------------------------------------------------------------

    def choose_folder(self) -> None:
        """Savegame-Verzeichnis von Hand waehlen."""
        dialog = Gtk.FileDialog(title="Savegame-Verzeichnis wählen")

        def chosen(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                folder = source.select_folder_finish(result)
            except GLib.Error:
                return  # Abgebrochen - keine Meldung noetig.
            if folder is None or folder.get_path() is None:
                return

            self._explicit_save_dir = folder.get_path()
            self._settings.save_dir = self._explicit_save_dir
            self._settings.save()
            self.load()

        dialog.select_folder(self, None, chosen)

    def _watch(self, path: Path) -> None:
        """Beobachte das Savegame-Verzeichnis und lies nach Aenderungen neu ein."""
        self._cancel_pending_reload()
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None

        try:
            self._monitor = Gio.File.new_for_path(str(path)).monitor_directory(
                Gio.FileMonitorFlags.NONE, None
            )
        except GLib.Error:
            return  # Ohne Ueberwachung bleibt der manuelle Knopf.

        self._monitor.connect("changed", self._on_save_changed)

    def _on_save_changed(
        self,
        _monitor: Gio.FileMonitor,
        file: Gio.File,
        _other: Gio.File | None,
        event: Gio.FileMonitorEvent,
    ) -> None:
        if event not in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.MOVED_IN,
        ):
            return

        name = file.get_basename() or ""
        if not name.endswith(".sav"):
            return

        # Das Spiel schreibt beim Speichern mehrere Dateien; erst nach einer
        # kurzen Ruhephase neu einlesen.
        self._cancel_pending_reload()
        self._reload_source = GLib.timeout_add(RELOAD_DEBOUNCE_MS, self._reload_now)

    def _reload_now(self) -> bool:
        self._reload_source = None
        self.load()
        return GLib.SOURCE_REMOVE

    def _cancel_pending_reload(self) -> None:
        if self._reload_source is not None:
            GLib.source_remove(self._reload_source)
            self._reload_source = None

    def do_close_request(self) -> bool:
        self._cancel_pending_reload()
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None
        self._settings.save()
        return False


class _CharacterRow(Gtk.ListBoxRow):
    """Eine Zeile der Charakterliste mit Fortschrittsbalken."""

    __gtype_name__ = "R2waCharacterRow"

    def __init__(self, character: Character, analysis: Analysis):
        super().__init__()
        self.character = character

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            margin_top=10,
            margin_bottom=10,
            margin_start=12,
            margin_end=12,
        )

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        # Gtk.Label stellt Text ohne Markup dar, deshalb unmaskiert.
        title = Gtk.Label(
            label=character.title,
            xalign=0.0,
            hexpand=True,
            ellipsize=Pango.EllipsizeMode.END,
            css_classes=["heading"],
        )
        title_row.append(title)

        if character.is_hardcore:
            title_row.append(Gtk.Label(label="Hardcore", css_classes=["caption", "error"]))
        if character.index == analysis.active_character_index:
            title_row.append(Gtk.Label(label="aktiv", css_classes=["caption", "accent"]))
        box.append(title_row)

        details = " · ".join(
            part
            for part in (
                f"Slot {character.index + 1}",
                f"Stufe {character.power_level}",
                format_playtime(character.playtime_seconds),
            )
            if part
        )
        box.append(Gtk.Label(label=details, xalign=0.0, css_classes=["caption", "dim-label"]))

        counts = character.counts
        progress = Gtk.ProgressBar(fraction=counts.fraction, margin_top=4)
        progress.set_tooltip_text(
            f"{counts.acquired} von {counts.total} gefunden, {counts.missing} fehlen"
        )
        box.append(progress)

        box.append(
            Gtk.Label(
                label=f"{counts.acquired} / {counts.total}",
                xalign=0.0,
                css_classes=["caption", "dim-label", "numeric"],
            )
        )

        self.set_child(box)
