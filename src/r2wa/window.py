"""The main window: character list on the left, items and worlds on the right."""

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

#: Delay after a file change before re-analyzing. The game writes several
#: files in quick succession when saving.
RELOAD_DEBOUNCE_MS = 2000

#: Window size on first ever start, before any size has been remembered.
DEFAULT_WIDTH = 1100
DEFAULT_HEIGHT = 760


class Window(Adw.ApplicationWindow):
    """Main window of the application."""

    __gtype_name__ = "R2waWindow"

    def __init__(self, application: Adw.Application, save_dir: str | None = None):
        super().__init__(application=application, title="Remnant 2 Analyzer")

        self._analysis: Analysis | None = None
        self._location: SaveLocation | None = None
        self._settings = Settings.load()
        # A path from the command line only applies to this run and is not
        # saved; the remembered choice is unaffected by it.
        self._explicit_save_dir = save_dir or self._settings.save_dir
        self._monitor: Gio.FileMonitor | None = None
        self._reload_source: int | None = None
        self._loading = False

        self.set_default_size(
            self._settings.window_width or DEFAULT_WIDTH,
            self._settings.window_height or DEFAULT_HEIGHT,
        )
        if self._settings.window_maximized:
            self.maximize()

        self._build_ui()
        self.load()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._items_view = ItemsView()
        self._worlds_view = WorldsView()

        # vexpand is needed because the stack sits in a box below the
        # banner, and box children otherwise only get their minimum height.
        self._stack = Adw.ViewStack(vexpand=True)
        self._stack.add_titled_with_icon(
            self._items_view, "items", "Items", "view-list-bullet-symbolic"
        )
        self._stack.add_titled_with_icon(self._worlds_view, "worlds", "Worlds", "map-symbolic")

        self._banner = Adw.Banner(revealed=False)
        self._banner.connect("button-clicked", lambda _b: self._banner.set_revealed(False))

        content_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_body.append(self._banner)
        content_body.append(self._stack)

        self._content_toolbar = Adw.ToolbarView(content=content_body)
        self._content_toolbar.add_top_bar(self._build_content_header())

        self._split = Adw.NavigationSplitView(
            sidebar=Adw.NavigationPage(title="Characters", child=self._build_sidebar()),
            content=Adw.NavigationPage(title="Overview", child=self._content_toolbar),
        )
        self._split.set_min_sidebar_width(260)
        self._split.set_max_sidebar_width(340)

        # On a narrow window the sidebar becomes its own page.
        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720px"))
        breakpoint_.add_setter(self._split, "collapsed", True)
        self.add_breakpoint(breakpoint_)

        # The empty state replaces the whole window as long as nothing is loaded.
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
        self._character_selection_handler = self._character_list.connect(
            "row-selected", self._on_character_selected
        )

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
            tooltip_text="Re-read save game",
        )
        self._reload_button.connect("clicked", lambda _b: self.load())
        header.pack_start(self._reload_button)

        self._spinner = Gtk.Spinner(visible=False)
        header.pack_start(self._spinner)

        return header

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append("Open Folder…", "win.open-folder")
        menu.append("Reload", "win.reload")
        menu.append("About r2wa", "app.about")

        return Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            menu_model=menu,
            tooltip_text="Main Menu",
        )

    def _build_placeholder(self) -> Gtk.Widget:
        self._status = Adw.StatusPage(
            icon_name="folder-saved-search-symbolic",
            title="No Save Game Found",
            description=(
                "No Remnant 2 save game was found in a Proton prefix. "
                "Choose the directory containing profile.sav by hand."
            ),
        )

        button = Gtk.Button(
            label="Choose Folder…",
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
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Look for a save game and start the analysis."""
        if self._loading:
            return

        location = self._resolve_location()
        if location is None:
            self._show_placeholder(
                "No Save Game Found",
                "No Remnant 2 save game was found in a Proton prefix. "
                "Choose the directory containing profile.sav by hand.",
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
                f"{count} warning{'s' if count != 1 else ''} while reading - "
                "some items could not be fully evaluated."
            )
            self._banner.set_button_label("Dismiss")
            self._banner.set_revealed(True)
        else:
            self._banner.set_revealed(False)

    def _on_analysis_failed(self, error: ParserError) -> None:
        self._finish_loading()

        if error.kind == "parser_not_found":
            description = (
                "The parser binary is missing. Build it with\n\n"
                "    just build-parser\n\n"
                "or set R2WA_PARSER to the path of the binary."
            )
        else:
            # Error texts contain paths and messages from the parser.
            # Adw.StatusPage renders the description as Pango markup, the
            # title does not - an "&" in the text would otherwise break the
            # display. The same applies to Adw.ActionRow (both fields are
            # markup); Adw.Banner, in turn, takes its title verbatim.
            description = GLib.markup_escape_text(str(error))

        self._show_placeholder("Analysis Failed", description)

    def _show_placeholder(self, title: str, description: str) -> None:
        self._status.set_title(title)
        self._status.set_description(description)
        self._root.set_visible_child_name("placeholder")

    # ------------------------------------------------------------------
    # Character list
    # ------------------------------------------------------------------

    def _populate_characters(self, analysis: Analysis) -> None:
        previous = self._selected_index()

        # Emptying the list deselects, and Gtk.ListBox reports that as a
        # selection of None. Left through, every reload tears both views down
        # to their "no character" state and rebuilds them a moment later -
        # wasted work on a catalog of hundreds of items, and a visible flicker
        # while the game is running.
        self._character_list.handler_block(self._character_selection_handler)
        try:
            self._character_list.remove_all()
            for character in analysis.characters:
                self._character_list.append(_CharacterRow(character, analysis))
        finally:
            self._character_list.handler_unblock(self._character_selection_handler)

        # On a reload the selection stays put; on the first start, the last
        # viewed character wins, otherwise the one active in the game.
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
        self._worlds_view.set_analysis(self._analysis, character)

    # ------------------------------------------------------------------
    # Folder selection and file monitoring
    # ------------------------------------------------------------------

    def choose_folder(self) -> None:
        """Choose the save game directory by hand."""
        dialog = Gtk.FileDialog(title="Choose Save Game Directory")

        def chosen(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                folder = source.select_folder_finish(result)
            except GLib.Error:
                return  # Cancelled - no message needed.
            if folder is None or folder.get_path() is None:
                return

            self._explicit_save_dir = folder.get_path()
            self._settings.save_dir = self._explicit_save_dir
            self._settings.save()
            self.load()

        dialog.select_folder(self, None, chosen)

    def _watch(self, path: Path) -> None:
        """Watch the save game directory and re-read after changes."""
        self._cancel_pending_reload()
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None

        try:
            self._monitor = Gio.File.new_for_path(str(path)).monitor_directory(
                Gio.FileMonitorFlags.NONE, None
            )
        except GLib.Error:
            return  # Without monitoring, the manual button still works.

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

        # The game writes several files when saving; only re-read after a
        # short quiet period.
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

        # Only remember the unmaximized size - otherwise un-maximizing later
        # would restore to a window that fills the screen.
        self._settings.window_maximized = self.is_maximized()
        if not self.is_maximized():
            self._settings.window_width = self.get_width()
            self._settings.window_height = self.get_height()

        self._settings.save()
        return False


class _CharacterRow(Gtk.ListBoxRow):
    """A row of the character list with a progress bar."""

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
        # Gtk.Label renders text without markup, hence unescaped.
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
            title_row.append(Gtk.Label(label="active", css_classes=["caption", "accent"]))
        box.append(title_row)

        details = " · ".join(
            part
            for part in (
                f"Slot {character.index + 1}",
                f"Level {character.display_power_level}",
                # Equal to the sum of the character's trait levels, checked
                # against the save - it is the number the game itself shows.
                f"Trait Rank {character.trait_rank}" if character.trait_rank else "",
                format_playtime(character.playtime_seconds),
            )
            if part
        )
        box.append(Gtk.Label(label=details, xalign=0.0, css_classes=["caption", "dim-label"]))

        counts = character.counts
        progress = Gtk.ProgressBar(fraction=counts.fraction, margin_top=4)
        progress.set_tooltip_text(
            f"{counts.acquired} of {counts.total} found, {counts.missing} missing"
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
