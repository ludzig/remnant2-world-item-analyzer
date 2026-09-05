"""The worlds view: what's in the currently rolled worlds.

Three linked columns, left to right: zones (the biomes, e.g. "Losomn"), the
locations within the selected zone, and the loot at the selected location.
Picking a row in one column repopulates the next.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from ..gobjects import LocationObject, LootItemObject, ZoneObject  # noqa: E402
from ..icons import IconLookup  # noqa: E402
from ..models import (  # noqa: E402
    Analysis,
    Character,
    Location,
    LootGroup,
    LootItem,
    World,
    Zone,
    format_playtime,
)
from .widgets import open_uri, toggle_group  # noqa: E402

#: Side length of an item's icon in the third column - matches the Items view.
ICON_SIZE = 32

#: Portraits head a whole group rather than a single row, and they are
#: photographs of a character rather than a small object on a plain
#: background - at the item icons' size they read as a smudge.
PORTRAIT_SIZE = ICON_SIZE * 2

#: Loot group types whose label names somebody the wiki has a picture of.
#: Everything else heads a place or an event ("World Drop", "dungeon"), and
#: those have no portrait to show.
PORTRAIT_GROUP_TYPES = frozenset({"vendor", "boss", "miniboss"})


class ItemStatus(Enum):
    """Which loot of the selected location the third column shows."""

    ALL = "all"
    MISSING = "missing"
    FOUND = "found"


class WorldsView(Gtk.Box):
    """Campaign and adventure as three linked lists: zones, locations, loot."""

    __gtype_name__ = "R2waWorldsView"

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._character: Character | None = None
        # The loot only names an item; the account-wide catalog is what
        # carries the note saying where and how to get it.
        self._analysis: Analysis | None = None
        self._slot = "campaign"
        self._only_open = False
        self._item_status = ItemStatus.ALL
        self._item_needle = ""
        self._icons = IconLookup()

        # Remembered by name (zones/locations are rebuilt from scratch on
        # every reload, so there's no stable object to keep a reference to)
        # so a live save-game reload restores the same drill-down instead of
        # always resetting to the first zone/location.
        self._last_zone_name: str | None = None
        self._last_location_name: str | None = None

        self._zone_store = Gio.ListStore.new(ZoneObject)
        self._zone_filter = Gtk.CustomFilter.new(self._match_zone)
        zones_filtered = Gtk.FilterListModel.new(self._zone_store, self._zone_filter)
        self._zone_selection = Gtk.SingleSelection.new(zones_filtered)
        self._zone_selection_handler = self._zone_selection.connect(
            "notify::selected-item", self._on_zone_selected
        )

        self._location_store = Gio.ListStore.new(LocationObject)
        self._location_filter = Gtk.CustomFilter.new(self._match_location)
        locations_filtered = Gtk.FilterListModel.new(self._location_store, self._location_filter)
        self._location_selection = Gtk.SingleSelection.new(locations_filtered)
        self._location_selection_handler = self._location_selection.connect(
            "notify::selected-item", self._on_location_selected
        )

        self._item_store = Gio.ListStore.new(LootItemObject)
        self._item_filter = Gtk.CustomFilter.new(self._match_item)
        items_filtered = Gtk.FilterListModel.new(self._item_store, self._item_filter)
        self._item_model = Gtk.SortListModel.new(items_filtered, _build_item_sorter())
        self._item_model.set_section_sorter(_build_item_section_sorter())

        self.append(self._build_toolbar())

        self._columns = self._build_columns()
        self.append(self._columns)

        self._empty = Adw.StatusPage(
            icon_name="map-symbolic",
            title="No World Rolled",
            description="This character has no world rolled in this slot.",
            vexpand=True,
            visible=False,
        )
        self.append(self._empty)

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

        self._slot_switch = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, css_classes=["linked"])
        self._campaign_button = Gtk.ToggleButton(label="Campaign", active=True)
        self._adventure_button = Gtk.ToggleButton(label="Adventure")
        self._adventure_button.set_group(self._campaign_button)
        self._campaign_button.connect(
            "toggled", lambda b: self._set_slot("campaign") if b.get_active() else None
        )
        self._adventure_button.connect(
            "toggled", lambda b: self._set_slot("adventure") if b.get_active() else None
        )
        self._slot_switch.append(self._campaign_button)
        self._slot_switch.append(self._adventure_button)
        bar.append(self._slot_switch)

        open_toggle = Gtk.ToggleButton(
            label="Open Only",
            tooltip_text="Only zones and locations with items not yet collected",
        )
        open_toggle.connect("toggled", self._on_open_toggled)
        bar.append(open_toggle)

        self._info = Gtk.Label(css_classes=["dim-label"], xalign=1.0, hexpand=True)
        bar.append(self._info)

        return bar

    def _build_columns(self) -> Gtk.Widget:
        zones = _build_column(
            "Zones", _build_list(self._zone_selection, _setup_zone_row, _bind_zone_row)
        )
        locations = _build_column(
            "Locations",
            _build_list(self._location_selection, _setup_location_row, _bind_location_row),
        )
        items = _build_column(
            "Items",
            _build_list(
                Gtk.NoSelection.new(self._item_model),
                _setup_item_row,
                _bind_item_row,
                header_setup=_setup_item_header,
                header_bind=_bind_item_header,
            ),
            toolbar=self._build_item_toolbar(),
        )
        self._locations_scroller = locations.r2wa_scroller
        self._locations_empty = locations.r2wa_empty
        self._items_scroller = items.r2wa_scroller
        self._items_empty = items.r2wa_empty

        inner = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        inner.set_start_child(locations)
        inner.set_end_child(items)
        inner.set_resize_start_child(False)
        inner.set_shrink_start_child(False)
        inner.set_position(260)

        outer = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        outer.set_start_child(zones)
        outer.set_end_child(inner)
        outer.set_resize_start_child(False)
        outer.set_shrink_start_child(False)
        outer.set_resize_end_child(True)
        outer.set_position(220)
        return outer

    def _build_item_toolbar(self) -> Gtk.Widget:
        bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=12,
            margin_end=12,
            margin_bottom=6,
        )
        self._item_search = Gtk.SearchEntry(placeholder_text="Search", hexpand=True)
        self._item_search.connect("search-changed", self._on_item_search_changed)
        bar.append(self._item_search)

        bar.append(
            toggle_group(
                [
                    ("All", ItemStatus.ALL),
                    ("Missing", ItemStatus.MISSING),
                    ("Found", ItemStatus.FOUND),
                ],
                active=ItemStatus.ALL,
                on_change=self._on_item_status_changed,
            )
        )
        return bar

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def _match_zone(self, obj: ZoneObject, _user_data=None) -> bool:
        return not self._only_open or obj.zone.open_item_count > 0

    def _match_location(self, obj: LocationObject, _user_data=None) -> bool:
        return not self._only_open or obj.location.open_item_count > 0

    def _match_item(self, obj: LootItemObject, _user_data=None) -> bool:
        item = obj.item
        if self._item_status is ItemStatus.MISSING and item.is_looted:
            return False
        if self._item_status is ItemStatus.FOUND and not item.is_looted:
            return False

        if self._item_needle:
            haystack = f"{item.name} {item.subcategory or ''} {obj.group_label}".casefold()
            return self._item_needle.casefold() in haystack
        return True

    def _on_open_toggled(self, button: Gtk.ToggleButton) -> None:
        self._only_open = button.get_active()
        self._zone_filter.changed(Gtk.FilterChange.DIFFERENT)
        self._location_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_item_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._item_needle = entry.get_text().strip()
        self._item_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_item_status_changed(self, status: ItemStatus) -> None:
        self._item_status = status
        self._item_filter.changed(Gtk.FilterChange.DIFFERENT)

    # ------------------------------------------------------------------
    # Selection cascade: picking a zone fills the locations, picking a
    # location fills the items.
    # ------------------------------------------------------------------

    def _on_zone_selected(self, selection: Gtk.SingleSelection, _pspec) -> None:
        obj: ZoneObject | None = selection.get_selected_item()
        self._remember_zone(obj)
        self._fill_locations(obj.zone if obj else None)

    def _on_location_selected(self, selection: Gtk.SingleSelection, _pspec) -> None:
        obj: LocationObject | None = selection.get_selected_item()
        self._remember_location(obj)
        self._fill_items(obj.location if obj else None)

    def _remember_zone(self, obj: ZoneObject | None) -> None:
        """Keep the last *real* zone, so an empty in-between state doesn't erase it.

        Showing no character at all is a state the window passes through on
        every reload; forgetting there would defeat the whole point of
        remembering. A name that no longer exists costs nothing - it is only
        ever a preference, and falls back to the first entry.
        """
        if obj is not None:
            self._last_zone_name = obj.zone.name

    def _remember_location(self, obj: LocationObject | None) -> None:
        """Keep the last *real* location - see :meth:`_remember_zone`."""
        if obj is not None:
            self._last_location_name = obj.location.name

    def _fill_locations(self, zone: Zone | None, wanted_location_name: str | None = None) -> None:
        """Rebuild the locations column for ``zone``.

        ``wanted_location_name`` lets a caller restore a specific location
        by name (used when restoring a whole drill-down after a reload);
        left out, it defaults to whatever is currently remembered (used for
        an ordinary zone click, where staying on a same-named location in
        the new zone is a reasonable - if usually moot - default).

        Rebuilding the store below fires its own intermediate, meaningless
        selection-changed notifications (emptying it, then autoselecting
        index 0 once refilled) before the real one we want is applied; the
        location selection's own change handler is blocked for that reason,
        and the actual outcome is resolved explicitly afterwards instead.
        """
        if wanted_location_name is None:
            wanted_location_name = self._last_location_name

        self._location_selection.handler_block(self._location_selection_handler)
        try:
            self._location_store.remove_all()
            if zone is not None and zone.locations:
                self._location_store.splice(0, 0, [LocationObject(loc) for loc in zone.locations])

            index = _find_index(
                self._location_selection, wanted_location_name, lambda obj: obj.location.name
            )
            if index is None and self._location_selection.get_n_items() > 0:
                index = 0
            if index is not None:
                self._location_selection.set_selected(index)
        finally:
            self._location_selection.handler_unblock(self._location_selection_handler)

        selected: LocationObject | None = self._location_selection.get_selected_item()
        self._remember_location(selected)
        self._fill_items(selected.location if selected else None)

        has_locations = self._zone_store_has(zone)
        self._locations_scroller.set_visible(has_locations)
        self._locations_empty.set_visible(not has_locations)

    def _fill_items(self, location: Location | None) -> None:
        self._item_store.remove_all()
        if location is not None:
            objects: list[LootItemObject] = []
            for group_index, group in enumerate(location.loot_groups):
                # Looked up once per group rather than per item - every item
                # of a group carries the same heading.
                group_icon = self._group_icon(group)
                group_url = self._group_wiki_url(group)
                objects.extend(
                    LootItemObject(
                        item,
                        group_index,
                        group.label,
                        group.type or "",
                        icon_path=self._icons.path_for(item),
                        wiki_url=self._icons.wiki_url_for(item),
                        group_icon_path=group_icon,
                        group_wiki_url=group_url,
                        note=self._note_for(item),
                    )
                    for item in group.items
                )
            if objects:
                self._item_store.splice(0, 0, objects)

        has_items = location is not None and bool(location.loot_groups)
        self._items_scroller.set_visible(has_items)
        self._items_empty.set_visible(not has_items)

    def _group_icon(self, group: LootGroup) -> Path | None:
        """A loot group's heading picture - vendors, bosses and minibosses.

        For those, the label is the name of whoever the group belongs to,
        which is what the portraits are keyed by. The type is checked first
        so a location that happens to share a boss's name can't pick up that
        boss's picture.
        """
        if (group.type or "").casefold() not in PORTRAIT_GROUP_TYPES:
            return None
        return self._icons.portrait_for(group.label)

    def _note_for(self, item: LootItem) -> str | None:
        """How and where the item is found, from the account-wide catalog.

        A location's loot carries only id, name and category, but the ids
        are the same on both sides, so the catalog's note can be looked up
        directly.
        """
        if self._analysis is None:
            return None
        entry = self._analysis.catalog.get(item.id)
        return entry.note if entry else None

    def _group_wiki_url(self, group: LootGroup) -> str | None:
        """The wiki page of whoever heads the group - same gate as the picture.

        Kept separate from :meth:`_group_icon` because the page is known
        from the table alone: a link works even where `just fetch-icons`
        has not run.
        """
        if (group.type or "").casefold() not in PORTRAIT_GROUP_TYPES:
            return None
        return self._icons.portrait_wiki_url_for(group.label)

    @staticmethod
    def _zone_store_has(zone: Zone | None) -> bool:
        return zone is not None and bool(zone.locations)

    # ------------------------------------------------------------------
    # Populating
    # ------------------------------------------------------------------

    def set_analysis(self, analysis: Analysis | None, character: Character | None) -> None:
        """Same shape as the items view takes, for the same reason.

        The worlds belong to the character, but the notes belong to the
        account-wide catalog - one call keeps the two from ever getting out
        of step on a reload.
        """
        self._analysis = analysis
        self._character = character
        self._update_slot_buttons()
        self._reload()

    def _update_slot_buttons(self) -> None:
        """Disable a slot if the character has no world there."""
        has_campaign = bool(self._character and self._character.world("campaign"))
        has_adventure = bool(self._character and self._character.world("adventure"))

        self._campaign_button.set_sensitive(has_campaign)
        self._adventure_button.set_sensitive(has_adventure)

        if self._slot == "adventure" and not has_adventure and has_campaign:
            self._slot = "campaign"
            self._campaign_button.set_active(True)

    def _set_slot(self, slot: str) -> None:
        if slot == self._slot:
            return
        self._slot = slot
        self._reload()

    def _reload(self) -> None:
        # Snapshotted upfront: rebuilding the store below fires its own
        # intermediate, meaningless selection-changed notifications first
        # (see _fill_locations) - the zone selection's own change handler is
        # blocked for that reason, and both the zone and location outcome
        # are resolved explicitly afterwards instead.
        wanted_zone_name = self._last_zone_name
        wanted_location_name = self._last_location_name

        world = self._character.world(self._slot) if self._character else None

        self._zone_selection.handler_block(self._zone_selection_handler)
        try:
            self._zone_store.remove_all()
            if world is not None and world.zones:
                self._zone_store.splice(0, 0, [ZoneObject(z) for z in world.zones])

            index = _find_index(self._zone_selection, wanted_zone_name, lambda obj: obj.zone.name)
            if index is None and self._zone_selection.get_n_items() > 0:
                index = 0
            if index is not None:
                self._zone_selection.set_selected(index)
        finally:
            self._zone_selection.handler_unblock(self._zone_selection_handler)

        selected: ZoneObject | None = self._zone_selection.get_selected_item()
        self._remember_zone(selected)
        self._fill_locations(selected.zone if selected else None, wanted_location_name)

        self._info.set_label(_world_summary(world))

        has_content = self._zone_store.get_n_items() > 0
        self._columns.set_visible(has_content)
        self._empty.set_visible(not has_content)


# ----------------------------------------------------------------------
# Stateless building blocks
# ----------------------------------------------------------------------


def _find_index(selection: Gtk.SelectionModel, wanted_name: str | None, name_of) -> int | None:
    """Index of the item whose name matches, or None if there's no such item."""
    if wanted_name is None:
        return None
    for index in range(selection.get_n_items()):
        if name_of(selection.get_item(index)) == wanted_name:
            return index
    return None


def _build_column(
    title: str, list_widget: Gtk.Widget, toolbar: Gtk.Widget | None = None
) -> Gtk.Box:
    column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=200)
    column.append(
        Gtk.Label(
            label=title,
            xalign=0.0,
            css_classes=["heading"],
            margin_top=6,
            margin_bottom=6,
            margin_start=12,
            margin_end=12,
        )
    )
    if toolbar is not None:
        column.append(toolbar)

    scroller = Gtk.ScrolledWindow(
        child=list_widget,
        vexpand=True,
        hscrollbar_policy=Gtk.PolicyType.NEVER,
    )
    column.append(scroller)

    empty = Gtk.Label(css_classes=["dim-label"], vexpand=True, visible=False)
    column.append(empty)

    column.r2wa_scroller = scroller
    column.r2wa_empty = empty
    return column


def _build_list(
    selection: Gtk.SelectionModel,
    setup,
    bind,
    header_setup=None,
    header_bind=None,
) -> Gtk.Widget:
    factory = Gtk.SignalListItemFactory()
    factory.connect("setup", setup)
    factory.connect("bind", bind)

    header_factory = None
    if header_setup is not None:
        header_factory = Gtk.SignalListItemFactory()
        header_factory.connect("setup", header_setup)
        header_factory.connect("bind", header_bind)

    return Gtk.ListView(
        model=selection,
        factory=factory,
        header_factory=header_factory,
        vexpand=True,
        show_separators=False,
    )


def _build_info_row(
    with_picture: bool = False, with_link: bool = False, with_note: bool = False
) -> Gtk.Box:
    """Icon + title/subtitle + badge - the shape shared by zone/location/item rows.

    Only the item row also gets a picture prefix (the item's own wiki icon,
    same as the Items view), a wiki-link suffix button and the catalog's
    note on how to find it - zones and locations have no such artwork, wiki
    page or note of their own.
    """
    box = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=8,
        margin_top=6,
        margin_bottom=6,
        margin_start=12,
        # A bit more room on the right, otherwise the badge sits under the
        # list's overlay scrollbar.
        margin_end=18,
    )

    picture = None
    if with_picture:
        picture = Gtk.Picture(
            content_fit=Gtk.ContentFit.CONTAIN,
            can_shrink=True,
            width_request=ICON_SIZE,
            height_request=ICON_SIZE,
            valign=Gtk.Align.CENTER,
        )
        box.append(picture)

    icon = Gtk.Image()
    box.append(icon)

    labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
    title = Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
    subtitle = Gtk.Label(
        xalign=0.0,
        css_classes=["caption", "dim-label"],
        visible=False,
        ellipsize=Pango.EllipsizeMode.END,
    )
    labels.append(title)
    labels.append(subtitle)

    note = None
    if with_note:
        # Notes run from a dozen characters to over a thousand. Two lines
        # keep the rows an even height and the list scannable; the full text
        # is on the row's tooltip.
        note = Gtk.Label(
            xalign=0.0,
            css_classes=["caption", "dim-label"],
            visible=False,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
            lines=2,
            ellipsize=Pango.EllipsizeMode.END,
        )
        labels.append(note)
    box.append(labels)

    badge = Gtk.Label(css_classes=["accent", "numeric"], valign=Gtk.Align.CENTER, visible=False)
    box.append(badge)

    link = None
    if with_link:
        link = Gtk.Button(
            icon_name="web-browser-symbolic",
            css_classes=["flat"],
            valign=Gtk.Align.CENTER,
            tooltip_text="Open wiki page",
            visible=False,
            cursor=Gdk.Cursor.new_from_name("pointer"),
        )
        box.append(link)

    box.r2wa_picture = picture
    box.r2wa_icon = icon
    box.r2wa_title = title
    box.r2wa_subtitle = subtitle
    box.r2wa_note = note
    box.r2wa_badge = badge
    box.r2wa_link = link
    return box


def _setup_zone_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    list_item.set_child(_build_info_row())


def _bind_zone_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    obj: ZoneObject = list_item.get_item()
    zone = obj.zone
    box = list_item.get_child()

    box.r2wa_icon.set_from_icon_name("map-symbolic")

    # Gtk.Label renders text without markup - this must not be escaped,
    # otherwise an "&" in a zone name would show up as "&amp;".
    box.r2wa_title.set_label(zone.name)
    box.r2wa_title.set_css_classes(
        ["dim-label"] if zone.finished and not zone.open_item_count else []
    )

    subtitle = _zone_subtitle(zone)
    box.r2wa_subtitle.set_label(subtitle)
    box.r2wa_subtitle.set_visible(bool(subtitle))

    box.r2wa_badge.set_label(str(zone.open_item_count) if zone.open_item_count else "")
    box.r2wa_badge.set_visible(bool(zone.open_item_count))


def _setup_location_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    list_item.set_child(_build_info_row())


def _bind_location_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    obj: LocationObject = list_item.get_item()
    location = obj.location
    box = list_item.get_child()

    box.r2wa_icon.set_from_icon_name("mark-location-symbolic")

    box.r2wa_title.set_label(location.name)
    box.r2wa_title.set_css_classes(["dim-label"] if not location.open_item_count else [])

    subtitle = _location_subtitle(location)
    box.r2wa_subtitle.set_label(subtitle)
    box.r2wa_subtitle.set_visible(bool(subtitle))

    box.r2wa_badge.set_label(str(location.open_item_count) if location.open_item_count else "")
    box.r2wa_badge.set_visible(bool(location.open_item_count))


def _setup_item_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    box = _build_info_row(with_picture=True, with_link=True, with_note=True)
    box.r2wa_wiki_url = None
    # The URL to open lives on the row, not baked into the closure: rows
    # are recycled while scrolling, so a fresh item can be bound to the
    # same button between setup and a later click.
    box.r2wa_link.connect("clicked", lambda _button: open_uri(box.r2wa_wiki_url))
    list_item.set_child(box)


def _bind_item_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    obj: LootItemObject = list_item.get_item()
    item = obj.item
    box = list_item.get_child()

    box.r2wa_picture.set_filename(str(obj.icon_path) if obj.icon_path else None)

    # Looted items get a checkmark; open ones stay blank instead of a "+" -
    # the item is already marked "open" by not being dimmed.
    box.r2wa_icon.set_from_icon_name("object-select-symbolic")
    box.r2wa_icon.set_visible(item.is_looted)

    box.r2wa_wiki_url = obj.wiki_url
    box.r2wa_link.set_visible(obj.wiki_url is not None)

    box.r2wa_title.set_label(item.name)
    box.r2wa_title.set_css_classes(["dim-label"] if item.is_looted else [])

    subtitle = " · ".join(_item_notes(item))
    box.r2wa_subtitle.set_label(subtitle)
    box.r2wa_subtitle.set_visible(bool(subtitle))

    box.r2wa_note.set_label(obj.note or "")
    box.r2wa_note.set_visible(bool(obj.note))
    box.set_tooltip_text(obj.note or None)


def _setup_item_header(_factory: Gtk.SignalListItemFactory, list_header: Gtk.ListHeader) -> None:
    box = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=12,
        margin_top=12,
        margin_bottom=4,
        margin_start=12,
        margin_end=12,
    )
    # A round portrait rather than the square frame the items get - this is
    # somebody, not a thing. Adw.Avatar also brings the fallback for free:
    # initials on a coloured circle if the portrait hasn't been downloaded.
    avatar = Adw.Avatar(
        size=PORTRAIT_SIZE, show_initials=True, valign=Gtk.Align.CENTER, visible=False
    )
    title = Gtk.Label(
        xalign=0.0, hexpand=True, css_classes=["heading"], ellipsize=Pango.EllipsizeMode.END
    )
    kind = Gtk.Label(xalign=1.0, css_classes=["dim-label", "caption"])
    link = Gtk.Button(
        icon_name="web-browser-symbolic",
        css_classes=["flat"],
        valign=Gtk.Align.CENTER,
        tooltip_text="Open wiki page",
        visible=False,
        cursor=Gdk.Cursor.new_from_name("pointer"),
    )
    box.append(avatar)
    box.append(title)
    box.append(kind)
    box.append(link)

    box.r2wa_avatar = avatar
    box.r2wa_title = title
    box.r2wa_kind = kind
    box.r2wa_link = link
    # Same reason as on the item rows: headers are recycled, so the URL has
    # to be read at click time rather than captured now.
    box.r2wa_wiki_url = None
    link.connect("clicked", lambda _button: open_uri(box.r2wa_wiki_url))

    list_header.set_child(box)


def _bind_item_header(_factory: Gtk.SignalListItemFactory, list_header: Gtk.ListHeader) -> None:
    obj: LootItemObject = list_header.get_item()
    box = list_header.get_child()

    has_portrait = obj.group_type.casefold() in PORTRAIT_GROUP_TYPES
    box.r2wa_avatar.set_visible(has_portrait)
    if has_portrait:
        box.r2wa_avatar.set_text(obj.group_label)
        box.r2wa_avatar.set_custom_image(_portrait_texture(obj.group_icon_path))

    box.r2wa_wiki_url = obj.group_wiki_url
    box.r2wa_link.set_visible(obj.group_wiki_url is not None)

    box.r2wa_title.set_label(obj.group_label)
    box.r2wa_kind.set_label(obj.group_type)
    box.r2wa_kind.set_visible(bool(obj.group_type))


#: Portraits already decoded. Headers are rebuilt on every scroll and on
#: every location change, and there are only a few dozen vendors and bosses
#: in the game - re-reading the file each time would be pure waste.
_PORTRAIT_TEXTURES: dict[Path, Gdk.Texture | None] = {}


def _portrait_texture(path: Path | None) -> Gdk.Texture | None:
    if path is None:
        return None
    if path not in _PORTRAIT_TEXTURES:
        try:
            _PORTRAIT_TEXTURES[path] = Gdk.Texture.new_from_filename(str(path))
        except GLib.Error:
            # A half-downloaded file shouldn't cost the heading its initials.
            _PORTRAIT_TEXTURES[path] = None
    return _PORTRAIT_TEXTURES[path]


def _zone_subtitle(zone: Zone) -> str:
    details = [zone.story] if zone.story else []
    if zone.finished:
        details.append("completed")
    return " · ".join(details)


def _location_subtitle(location: Location) -> str:
    marks: list[str] = []
    if location.trait_book and not location.trait_book_looted:
        marks.append("Trait Book")
    if location.simulacrum and not location.simulacrum_looted:
        marks.append("Simulacrum")
    if location.bloodmoon:
        marks.append("Blood Moon")
    if location.vendors:
        marks.append("Vendor: " + ", ".join(location.vendors))
    return " · ".join(marks) if marks else (location.category or "")


def _item_notes(item: LootItem) -> list[str]:
    notes: list[str] = []
    if item.subcategory:
        notes.append(item.subcategory)
    if item.coop_only:
        notes.append("co-op only")
    if item.is_prerequisite_missing:
        notes.append("prerequisite missing")
    if not item.has_required_material and item.category == "mod":
        notes.append("missing material")
    return notes


def _build_item_sorter() -> Gtk.Sorter:
    """By loot group, in the order the parser reported them."""

    def compare(a: LootItemObject, b: LootItemObject, _user_data=None) -> int:
        return (a.group_index > b.group_index) - (a.group_index < b.group_index)

    return Gtk.CustomSorter.new(compare)


def _build_item_section_sorter() -> Gtk.Sorter:
    """Groups the list by loot group; must match the sort order."""

    def compare(a: LootItemObject, b: LootItemObject, _user_data=None) -> int:
        return (a.group_index > b.group_index) - (a.group_index < b.group_index)

    return Gtk.CustomSorter.new(compare)


def _world_summary(world: World | None) -> str:
    if world is None:
        return ""

    parts = [world.label]
    if world.difficulty:
        parts.append(world.difficulty)
    if world.playtime_seconds:
        parts.append(format_playtime(world.playtime_seconds))

    open_items = sum(zone.open_item_count for zone in world.zones)
    if open_items:
        parts.append(f"{open_items} open")

    return " · ".join(parts)
