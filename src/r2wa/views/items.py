"""The item checklist: what do I have, what am I still missing."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..gobjects import ItemObject  # noqa: E402
from ..icons import IconLookup  # noqa: E402
from ..models import (  # noqa: E402
    Analysis,
    Character,
    Counts,
    Item,
    category_label,
    category_sort_key,
    counts_for,
)
from .widgets import open_uri, toggle_group  # noqa: E402

#: Side length of the item icon in the row.
ICON_SIZE = 32


class Status(Enum):
    """Which items the list shows."""

    ALL = "all"
    MISSING = "missing"
    ACQUIRED = "acquired"


class Scope(Enum):
    """Whose collection status the list shows."""

    CHARACTER = "character"
    ACCOUNT = "account"


class ItemsView(Gtk.Box):
    """Filtered, category-grouped list of all collectibles."""

    __gtype_name__ = "R2waItemsView"

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._analysis: Analysis | None = None
        self._character: Character | None = None
        self._status = Status.ALL
        self._scope = Scope.CHARACTER
        self._needle = ""
        self._counts = Counts()
        self._icons = IconLookup()
        self._icon_paths: dict[str, Path] = {}
        self._wiki_urls: dict[str, str] = {}

        # Data chain: store -> filter -> sort with sections.
        # Gtk.SortListModel provides the sections for the category headers
        # once a section sorter is set (GTK 4.12+).
        self._store = Gio.ListStore.new(ItemObject)

        self._filter = Gtk.CustomFilter.new(self._match)
        filtered = Gtk.FilterListModel.new(self._store, self._filter)

        self._model = Gtk.SortListModel.new(filtered, _build_sorter())
        self._model.set_section_sorter(_build_section_sorter())

        self.append(self._build_toolbar())

        self._scroller = self._build_list(self._model)
        self.append(self._scroller)

        self._empty = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title="No Matches",
            description="Try different search terms or a different filter.",
            vexpand=True,
            visible=False,
        )
        self.append(self._empty)

        self._model.connect("items-changed", lambda *_: self._update_empty_state())

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> Gtk.Widget:
        bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        self._search = Gtk.SearchEntry(
            placeholder_text="Search item, category, or drop location",
            hexpand=True,
        )
        self._search.connect("search-changed", self._on_search_changed)
        bar.append(self._search)

        bar.append(
            toggle_group(
                [
                    ("All", Status.ALL),
                    ("Missing", Status.MISSING),
                    ("Found", Status.ACQUIRED),
                ],
                active=Status.ALL,
                on_change=self._on_status_changed,
            )
        )

        self._scope_group = toggle_group(
            [
                ("Character", Scope.CHARACTER),
                ("All", Scope.ACCOUNT),
            ],
            active=Scope.CHARACTER,
            on_change=self._on_scope_changed,
            tooltips=[
                "Only the selected character's collection status",
                "Combined across all characters",
            ],
        )
        bar.append(self._scope_group)

        self._summary = Gtk.Label(css_classes=["dim-label", "numeric"], xalign=1.0)
        bar.append(self._summary)

        return bar

    def _build_list(self, model: Gio.ListModel) -> Gtk.Widget:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", _setup_row)
        factory.connect("bind", self._bind_row)

        header_factory = Gtk.SignalListItemFactory()
        header_factory.connect("setup", _setup_header)
        header_factory.connect("bind", self._bind_header)

        self._list = Gtk.ListView(
            model=Gtk.NoSelection.new(model),
            factory=factory,
            header_factory=header_factory,
            vexpand=True,
            show_separators=False,
        )

        return Gtk.ScrolledWindow(
            child=self._list,
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
        )

    # ------------------------------------------------------------------
    # Rows
    # ------------------------------------------------------------------

    def _bind_row(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        obj: ItemObject = list_item.get_item()
        item = obj.item
        row: Adw.ActionRow = list_item.get_child()

        row.set_title(_escape(item.name))
        row.set_subtitle(_escape(self._subtitle_for(item)))
        # Notes run to a couple of hundred characters and occasionally to a
        # thousand; two lines keep the rows uniform, the tooltip has the rest.
        row.set_tooltip_text(item.catalog.note or None)

        icon: Gtk.Picture = row.r2wa_icon
        icon_path = self._icon_paths.get(item.id)
        icon.set_filename(str(icon_path) if icon_path else None)

        link: Gtk.Button = row.r2wa_link
        wiki_url = self._wiki_urls.get(item.id)
        link.set_visible(wiki_url is not None)
        row.r2wa_wiki_url = wiki_url

        check: Gtk.Image = row.r2wa_check
        check.set_from_icon_name("object-select-symbolic" if item.acquired else "checkbox-symbolic")
        check.set_css_classes(["success"] if item.acquired else ["dim-label"])

        # Finished items step back visually so the open ones stand out.
        row.set_css_classes(["dim-label"] if item.acquired else [])

        badges: Gtk.Box = row.r2wa_badges
        _clear(badges)
        for label, style in self._badges_for(item):
            badges.append(Gtk.Label(label=label, css_classes=["caption", style]))

    @staticmethod
    def _subtitle_for(item: Item) -> str:
        """Where the item comes from, and how to get there.

        The note is the useful half - the catalog carries one for almost
        every item, and it names the actual place and the steps ("Wear the
        Red Doe Sigil amulet to open"). It used to be shown only where
        there was no source at all, which hid it behind lines as unhelpful
        as "Event: Quest_Injectable_Island_DLC".
        """
        parts: list[str] = []
        if item.subcategory:
            parts.append(item.subcategory)
        if item.catalog.source:
            parts.append(item.catalog.source)
        if item.catalog.note:
            parts.append(item.catalog.note)
        return " · ".join(parts)

    def _badges_for(self, item: Item) -> list[tuple[str, str]]:
        """Short hints on the right of the row."""
        badges: list[tuple[str, str]] = []

        if item.acquired:
            if item.state.is_equipped:
                badges.append(("equipped", "accent"))
            if item.state.level:
                badges.append((f"Level {item.state.level}", "dim-label"))
            return badges

        # Reachability only matters for missing items, and only carries
        # meaning when a specific character is selected - the worlds belong
        # to the character, not the account.
        if self._scope is Scope.CHARACTER:
            if item.state.obtainable_in_campaign:
                badges.append(("Campaign", "success"))
            if item.state.obtainable_in_adventure:
                badges.append(("Adventure", "success"))
            if not item.state.obtainable_now:
                badges.append(("Reroll needed", "warning"))

        if item.catalog.coop_only:
            badges.append(("Co-op", "accent"))

        return badges

    def _bind_header(
        self, _factory: Gtk.SignalListItemFactory, list_header: Gtk.ListHeader
    ) -> None:
        obj: ItemObject = list_header.get_item()
        category = obj.item.category
        box = list_header.get_child()

        box.r2wa_title.set_label(category_label(category))

        # The counter deliberately shows the full stock of the category, not
        # the currently visible subset - otherwise it would be worthless
        # while filtering.
        counts = self._counts.by_category.get(category)
        box.r2wa_count.set_label(f"{counts.acquired} / {counts.total}" if counts else "")

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _match(self, obj: ItemObject, _user_data=None) -> bool:
        item = obj.item

        if self._status is Status.MISSING and item.acquired:
            return False
        if self._status is Status.ACQUIRED and not item.acquired:
            return False

        return item.matches(self._needle)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._needle = entry.get_text().strip()
        self._filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_status_changed(self, status: Status) -> None:
        self._status = status
        self._filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_scope_changed(self, scope: Scope) -> None:
        if scope is self._scope:
            return
        self._scope = scope
        self._reload_items()

    # ------------------------------------------------------------------
    # Populating
    # ------------------------------------------------------------------

    def set_analysis(self, analysis: Analysis | None, character: Character | None) -> None:
        """Show the items of a character (or the whole account)."""
        # New catalog -> new icon mapping. Once per analysis instead of per
        # row, so scrolling doesn't re-match on every row.
        if analysis is not self._analysis:
            self._icon_paths = (
                {
                    entry.id: path
                    for entry in analysis.catalog.values()
                    if (path := self._icons.path_for(entry)) is not None
                }
                if analysis is not None
                else {}
            )
            self._wiki_urls = (
                {
                    entry.id: url
                    for entry in analysis.catalog.values()
                    if (url := self._icons.wiki_url_for(entry)) is not None
                }
                if analysis is not None
                else {}
            )

        self._analysis = analysis
        self._character = character
        self._scope_group.set_sensitive(analysis is not None and len(analysis.characters) > 1)
        self._reload_items()

    def _reload_items(self) -> None:
        items = self._current_items()
        self._counts = counts_for(items)

        self._store.remove_all()
        if items:
            self._store.splice(0, 0, [ItemObject(item) for item in items])

        self._summary.set_label(f"{self._counts.acquired} / {self._counts.total}" if items else "")
        self._update_empty_state()

    def _current_items(self) -> list[Item]:
        if self._analysis is None:
            return []
        if self._scope is Scope.ACCOUNT:
            return list(self._analysis.aggregate_items())
        return list(self._character.items) if self._character else []

    def _update_empty_state(self) -> None:
        has_rows = self._model.get_n_items() > 0
        self._empty.set_visible(not has_rows)
        self._scroller.set_visible(has_rows)


# ----------------------------------------------------------------------
# Stateless building blocks
# ----------------------------------------------------------------------


def _setup_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    row = Adw.ActionRow(activatable=False, subtitle_lines=2)

    # If there is no icon, the area stays blank instead of hiding the
    # widget - otherwise the title and badges would drift by a different
    # amount from row to row.
    icon = Gtk.Picture(
        content_fit=Gtk.ContentFit.CONTAIN,
        can_shrink=True,
        width_request=ICON_SIZE,
        height_request=ICON_SIZE,
        valign=Gtk.Align.CENTER,
    )
    row.add_prefix(icon)

    check = Gtk.Image(icon_name="checkbox-symbolic")
    row.add_prefix(check)

    # One suffix box holding both the badges and the wiki-link button, so a
    # single margin_end keeps the true right-hand edge clear of the list's
    # overlay scrollbar regardless of which of the two is visible.
    suffix = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER, margin_end=12
    )
    row.add_suffix(suffix)

    # Badges are cleared and rebuilt on every bind (see _bind_row); this
    # inner box isolates that from the link button, which must survive it.
    badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
    suffix.append(badges)

    # The URL to open lives on the row, not baked into the closure below:
    # rows are recycled while scrolling, so a fresh item can be bound to the
    # same button between setup and a later click.
    link = Gtk.Button(
        icon_name="web-browser-symbolic",
        css_classes=["flat"],
        valign=Gtk.Align.CENTER,
        tooltip_text="Open wiki page",
        visible=False,
        cursor=Gdk.Cursor.new_from_name("pointer"),
    )
    link.connect("clicked", lambda _button: open_uri(row.r2wa_wiki_url))
    suffix.append(link)

    # Keep references on the widget itself, not on the Gtk.ListItem: rows
    # are recycled while scrolling, the widget persists across that.
    row.r2wa_icon = icon
    row.r2wa_check = check
    row.r2wa_badges = badges
    row.r2wa_link = link
    row.r2wa_wiki_url = None

    list_item.set_child(row)


def _setup_header(_factory: Gtk.SignalListItemFactory, list_header: Gtk.ListHeader) -> None:
    box = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=12,
        margin_top=18,
        margin_bottom=6,
        margin_start=12,
        margin_end=12,
    )
    title = Gtk.Label(xalign=0.0, hexpand=True, css_classes=["heading"])
    count = Gtk.Label(xalign=1.0, css_classes=["dim-label", "numeric"])
    box.append(title)
    box.append(count)

    box.r2wa_title = title
    box.r2wa_count = count

    list_header.set_child(box)


def _build_sorter() -> Gtk.Sorter:
    """By category in display order, alphabetical within that."""

    def compare(a: ItemObject, b: ItemObject, _user_data=None) -> int:
        key_a = (category_sort_key(a.item.category), a.item.name.casefold())
        key_b = (category_sort_key(b.item.category), b.item.name.casefold())
        return (key_a > key_b) - (key_a < key_b)

    return Gtk.CustomSorter.new(compare)


def _build_section_sorter() -> Gtk.Sorter:
    """Groups the list by category; must match the sort order."""

    def compare(a: ItemObject, b: ItemObject, _user_data=None) -> int:
        key_a = category_sort_key(a.item.category)
        key_b = category_sort_key(b.item.category)
        return (key_a > key_b) - (key_a < key_b)

    return Gtk.CustomSorter.new(compare)


def _clear(box: Gtk.Box) -> None:
    """Remove all children of a box."""
    child = box.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        box.remove(child)
        child = following


def _escape(text: str) -> str:
    """Escape markup characters.

    Adw.ActionRow interprets the title and subtitle as Pango markup; an
    ``&`` in an item name would otherwise break the row.
    """
    return GLib.markup_escape_text(text) if text else ""
