"""GObject wrappers around the data model.

Gtk.ListView works exclusively with GObject instances. These classes only
hold a reference to the dataclasses from :mod:`r2wa.models` and carry no
logic of their own - that way the evaluation stays testable there without
GTK having to be loaded.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GObject  # noqa: E402

from .models import Character, Item, Location, LootItem, Zone  # noqa: E402


class ItemObject(GObject.Object):
    """A collectible item in the item list.

    ``display_name`` is what the row shows, what the search matches and
    what the list sorts by - all three have to agree, so it is resolved
    once here rather than in each of the three places.
    """

    __gtype_name__ = "R2waItemObject"

    def __init__(self, item: Item, display_name: str | None = None):
        super().__init__()
        self.item = item
        self.display_name = display_name or item.name

    @GObject.Property(type=str, flags=GObject.ParamFlags.READABLE)
    def name(self) -> str:
        return self.display_name

    @GObject.Property(type=str, flags=GObject.ParamFlags.READABLE)
    def category(self) -> str:
        return self.item.category

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READABLE)
    def acquired(self) -> bool:
        return self.item.acquired


class CategoryObject(GObject.Object):
    """A collapsible category in the item list.

    ``store`` holds every item of the category, ``items`` the filtered view
    of it that the list actually shows. The category row drops out of the
    list as soon as that view runs empty, so a search never leaves a
    heading behind with nothing under it.
    """

    __gtype_name__ = "R2waCategoryObject"

    def __init__(self, category: str, store: Gio.ListStore, items: Gio.ListModel):
        super().__init__()
        self.category = category
        self.store = store
        self.items = items


class CharacterObject(GObject.Object):
    """A character in the sidebar."""

    __gtype_name__ = "R2waCharacterObject"

    def __init__(self, character: Character):
        super().__init__()
        self.character = character


class ZoneObject(GObject.Object):
    """A zone (biome) of a rolled world, shown in the worlds view's first column.

    ``open_count`` is worked out once when the row is built: it depends on
    what the character owns, which the zone itself knows nothing about.
    """

    __gtype_name__ = "R2waZoneObject"

    def __init__(self, zone: Zone, open_count: int = 0):
        super().__init__()
        self.zone = zone
        self.open_count = open_count


class LocationObject(GObject.Object):
    """A location within a zone, shown in the worlds view's second column."""

    __gtype_name__ = "R2waLocationObject"

    def __init__(self, location: Location, open_count: int = 0):
        super().__init__()
        self.location = location
        self.open_count = open_count


class LootItemObject(GObject.Object):
    """An item found at a location, shown in the worlds view's third column.

    ``group_index``/``group_label`` carry the loot group the item came from
    (e.g. a vendor's name, or an event trigger) so the item list can still
    section itself by group after flattening the location's loot groups.
    ``group_icon_path``/``group_wiki_url`` belong to that heading - only
    vendors and bosses have them, the wiki keeps no page or portrait for a
    "World Drop".

    ``acquired`` is the character's own answer to "do I have this?", which
    the loot item cannot give: its ``is_looted`` only covers this one world
    roll. Both are shown, because they mean different things.
    """

    __gtype_name__ = "R2waLootItemObject"

    def __init__(
        self,
        item: LootItem,
        group_index: int,
        group_label: str,
        group_type: str,
        icon_path: Path | None = None,
        wiki_url: str | None = None,
        group_icon_path: Path | None = None,
        group_wiki_url: str | None = None,
        note: str | None = None,
        acquired: bool = False,
    ):
        super().__init__()
        self.item = item
        self.acquired = acquired
        self.group_index = group_index
        self.group_label = group_label
        self.group_type = group_type
        self.icon_path = icon_path
        self.wiki_url = wiki_url
        self.group_icon_path = group_icon_path
        self.group_wiki_url = group_wiki_url
        self.note = note
