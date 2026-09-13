"""The item checklist: what do I have, what am I still missing."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..gobjects import CategoryObject, ItemObject  # noqa: E402
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
    """Collapsible, category-grouped list of all collectibles.

    The categories are rows of the list, not headings above it: with close
    to a thousand items the way to find something is to fold away the
    thirteen categories one is not looking at.
    """

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
        # The analyzer puts the internal id in `name` for a good half of the
        # catalog, traits included. Resolved once per analysis, not per row.
        self._display_names: dict[str, str] = {}

        # Which categories are folded away, by category name rather than by
        # row: the rows are rebuilt on every character switch, the choice of
        # what to look at outlives them.
        self._collapsed: set[str] = set()
        self._collapsed_before_search: set[str] | None = None

        # Data chain: one store per category, each behind the shared item
        # filter, all of them behind a filter that drops categories without
        # a match, and a tree on top that turns them into expandable rows.
        self._filter = Gtk.CustomFilter.new(self._match)

        self._categories = Gio.ListStore.new(CategoryObject)
        self._category_filter = Gtk.CustomFilter.new(_has_matches)
        self._visible = Gtk.FilterListModel.new(self._categories, self._category_filter)
        self._tree = Gtk.TreeListModel.new(self._visible, False, False, _children_of)

        self.append(self._build_toolbar())

        self._scroller = self._build_list(self._tree)
        self.append(self._scroller)

        self._empty = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title="No Matches",
            description="Try different search terms or a different filter.",
            vexpand=True,
            visible=False,
        )
        self.append(self._empty)

        self._visible.connect("items-changed", lambda *_: self._update_empty_state())

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

        self._toggle_all = Gtk.Button(
            icon_name="pan-up-symbolic",
            css_classes=["flat"],
            valign=Gtk.Align.CENTER,
            tooltip_text="Collapse all categories",
        )
        self._toggle_all.connect("clicked", self._on_toggle_all)
        bar.append(self._toggle_all)

        self._summary = Gtk.Label(css_classes=["dim-label", "numeric"], xalign=1.0)
        bar.append(self._summary)

        return bar

    def _build_list(self, model: Gio.ListModel) -> Gtk.Widget:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_row)
        factory.connect("bind", self._bind_row)
        factory.connect("unbind", _unbind_row)

        self._list = Gtk.ListView(
            model=Gtk.NoSelection.new(model),
            factory=factory,
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

    def _setup_row(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        """Build both kinds of row at once.

        A Gtk.ListView has a single factory, and the tree hands it category
        rows and item rows interleaved. Building both and showing one is
        cheaper than rebuilding a widget on every bind - the list recycles
        roughly as many widgets as fit on screen, not one per item.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = _build_category_row()
        header.connect("clicked", self._on_category_clicked)
        box.append(header)

        row = _build_item_row()
        box.append(row)

        box.r2wa_header = header
        box.r2wa_item = row

        list_item.set_child(box)

    def _bind_row(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        tree_row: Gtk.TreeListRow = list_item.get_item()
        obj = tree_row.get_item()
        box = list_item.get_child()

        is_category = isinstance(obj, CategoryObject)
        box.r2wa_header.set_visible(is_category)
        box.r2wa_item.set_visible(not is_category)

        if is_category:
            self._bind_category(box.r2wa_header, tree_row, obj)
        else:
            self._bind_item(box.r2wa_item, obj)

    def _bind_category(
        self, header: Gtk.Button, tree_row: Gtk.TreeListRow, obj: CategoryObject
    ) -> None:
        header.r2wa_tree_row = tree_row
        header.r2wa_title.set_label(category_label(obj.category))

        # The counter deliberately shows the full stock of the category, not
        # the currently visible subset - otherwise it would be worthless
        # while filtering.
        counts = self._counts.by_category.get(obj.category)
        header.r2wa_count.set_label(f"{counts.acquired} / {counts.total}" if counts else "")

        _set_arrow(header.r2wa_arrow, tree_row.get_expanded())
        # Folding also happens from the toolbar button, which never touches
        # this widget - so the arrow follows the row's own state rather than
        # the click that caused it.
        header.r2wa_notify = tree_row.connect(
            "notify::expanded",
            lambda row, _param: _set_arrow(header.r2wa_arrow, row.get_expanded()),
        )

    def _bind_item(self, row: Adw.ActionRow, obj: ItemObject) -> None:
        item = obj.item

        row.set_title(_escape(obj.display_name))
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
        if self._scope is Scope.CHARACTER and self._character is not None:
            state = item.state
            if state.obtainable_in_campaign:
                badges.append(("Campaign", "success"))
            if state.obtainable_in_adventure:
                badges.append(("Adventure", "success"))

            # `None` means two different things: the slot has no rolled world
            # at all, or the analyzer could not decide (it gives up on a few
            # items with several prerequisites). Only the second is
            # "unknown" - and "Reroll needed" would claim a reroll helps,
            # which is precisely what we do not know.
            undecided = any(
                self._character.world(slot) is not None and obtainable is None
                for slot, obtainable in (
                    ("campaign", state.obtainable_in_campaign),
                    ("adventure", state.obtainable_in_adventure),
                )
            )
            if undecided:
                badges.append(("Reachability unknown", "dim-label"))
            elif not state.obtainable_now:
                badges.append(("Reroll needed", "warning"))

        if item.catalog.coop_only:
            badges.append(("Co-op", "accent"))

        return badges

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _match(self, obj: ItemObject, _user_data=None) -> bool:
        item = obj.item

        if self._status is Status.MISSING and item.acquired:
            return False
        if self._status is Status.ACQUIRED and not item.acquired:
            return False

        if item.matches(self._needle):
            return True

        # The search index on the model is built from the raw catalog name,
        # so "Blood Bond" would find nothing while `Trait_BloodBond` did.
        return self._needle.casefold() in obj.display_name.casefold()

    def _refilter(self) -> None:
        """Re-run both filters and put the rows back in shape.

        The order matters: the category filter asks each category how many
        items are left, so the items have to be thinned out first. The
        expansion pass comes last because a filter change can bring a
        category row back that was gone a keystroke ago.
        """
        self._filter.changed(Gtk.FilterChange.DIFFERENT)
        self._category_filter.changed(Gtk.FilterChange.DIFFERENT)
        self._apply_expansion()

    # ------------------------------------------------------------------
    # Folding
    # ------------------------------------------------------------------

    def _apply_expansion(self) -> None:
        """Put every category row into the state :attr:`_collapsed` asks for."""
        for index in range(self._visible.get_n_items()):
            row = self._tree.get_child_row(index)
            if row is None:
                continue
            row.set_expanded(row.get_item().category not in self._collapsed)
        self._sync_toggle_all()

    def _on_category_clicked(self, header: Gtk.Button) -> None:
        tree_row: Gtk.TreeListRow | None = header.r2wa_tree_row
        if tree_row is None:
            return

        category = tree_row.get_item().category
        if category in self._collapsed:
            self._collapsed.discard(category)
        else:
            self._collapsed.add(category)

        tree_row.set_expanded(category not in self._collapsed)
        self._sync_toggle_all()

    def _on_toggle_all(self, _button: Gtk.Button) -> None:
        categories = [obj.category for obj in self._categories]
        if any(category not in self._collapsed for category in categories):
            self._collapsed.update(categories)
        else:
            self._collapsed.clear()
        self._apply_expansion()

    def _sync_toggle_all(self) -> None:
        """One button for both directions - it offers whatever is left to do."""
        categories = [obj.category for obj in self._categories]
        self._toggle_all.set_sensitive(bool(categories))

        collapse = any(category not in self._collapsed for category in categories)
        self._toggle_all.set_icon_name("pan-up-symbolic" if collapse else "pan-down-symbolic")
        self._toggle_all.set_tooltip_text(
            "Collapse all categories" if collapse else "Expand all categories"
        )

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        needle = entry.get_text().strip()

        # A search has to be able to show what it found, so starting one
        # opens every category. What was folded away comes back once the
        # search box is empty again - including anything folded meanwhile,
        # which belongs to the search, not to the list.
        if needle and self._collapsed_before_search is None:
            self._collapsed_before_search = set(self._collapsed)
            self._collapsed.clear()
        elif not needle and self._collapsed_before_search is not None:
            self._collapsed = self._collapsed_before_search
            self._collapsed_before_search = None

        self._needle = needle
        self._refilter()

    def _on_status_changed(self, status: Status) -> None:
        self._status = status
        self._refilter()

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
            self._display_names = (
                {
                    entry.id: self._icons.display_name_for(entry)
                    for entry in analysis.catalog.values()
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

        self._categories.remove_all()
        for category, entries in self._grouped(items):
            store = Gio.ListStore.new(ItemObject)
            store.splice(0, 0, entries)
            self._categories.append(
                CategoryObject(category, store, Gtk.FilterListModel.new(store, self._filter))
            )

        self._apply_expansion()
        self._summary.set_label(f"{self._counts.acquired} / {self._counts.total}" if items else "")
        self._update_empty_state()

    def _grouped(self, items: list[Item]) -> list[tuple[str, list[ItemObject]]]:
        """Group into categories in display order, alphabetical within each.

        Sorted here rather than by a Gtk.Sorter per category: the order only
        changes when the items do, which is once per character switch.
        """
        groups: dict[str, list[ItemObject]] = {}
        for item in items:
            groups.setdefault(item.category, []).append(
                ItemObject(item, self._display_names.get(item.id))
            )

        for entries in groups.values():
            entries.sort(key=lambda obj: obj.display_name.casefold())

        return sorted(groups.items(), key=lambda group: category_sort_key(group[0]))

    def _current_items(self) -> list[Item]:
        if self._analysis is None:
            return []
        if self._scope is Scope.ACCOUNT:
            return list(self._analysis.aggregate_items())
        return list(self._character.items) if self._character else []

    def _update_empty_state(self) -> None:
        has_rows = self._visible.get_n_items() > 0
        self._empty.set_visible(not has_rows)
        self._scroller.set_visible(has_rows)


# ----------------------------------------------------------------------
# Stateless building blocks
# ----------------------------------------------------------------------


def _children_of(obj: CategoryObject | ItemObject, _user_data=None) -> Gio.ListModel | None:
    """What hangs under a row - items under a category, nothing under an item."""
    return obj.items if isinstance(obj, CategoryObject) else None


def _has_matches(obj: CategoryObject, _user_data=None) -> bool:
    return obj.items.get_n_items() > 0


def _build_category_row() -> Gtk.Button:
    """The category row: an arrow, the name, and the category's tally.

    A button rather than a bare box, so the whole width answers to a click
    and the row can be reached with the keyboard - the arrow alone would be
    a needlessly small target.
    """
    arrow = Gtk.Image(icon_name="pan-down-symbolic")
    title = Gtk.Label(xalign=0.0, hexpand=True, css_classes=["heading"])
    count = Gtk.Label(xalign=1.0, css_classes=["dim-label", "numeric"])

    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    box.append(arrow)
    box.append(title)
    box.append(count)

    button = Gtk.Button(
        child=box,
        css_classes=["flat"],
        hexpand=True,
        margin_top=12,
        margin_bottom=2,
        margin_start=6,
        margin_end=6,
        cursor=Gdk.Cursor.new_from_name("pointer"),
    )

    button.r2wa_arrow = arrow
    button.r2wa_title = title
    button.r2wa_count = count
    # Both set in _bind_category; rows are recycled while scrolling, so a
    # click may well arrive after the widget has moved to another category.
    button.r2wa_tree_row = None
    button.r2wa_notify = 0

    return button


def _build_item_row() -> Adw.ActionRow:
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

    # Badges are cleared and rebuilt on every bind (see _bind_item); this
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

    return row


def _unbind_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    """Let go of the row the widget was showing.

    The expansion listener has to go with it: the widget outlives the row it
    was bound to, and would otherwise keep drawing a second category's arrow.
    """
    header: Gtk.Button = list_item.get_child().r2wa_header
    if header.r2wa_notify:
        header.r2wa_tree_row.disconnect(header.r2wa_notify)
        header.r2wa_notify = 0
    header.r2wa_tree_row = None


def _set_arrow(arrow: Gtk.Image, expanded: bool) -> None:
    arrow.set_from_icon_name("pan-down-symbolic" if expanded else "pan-end-symbolic")


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
