"""GObject-Huellen um das Datenmodell.

Gtk.ListView arbeitet ausschliesslich mit GObject-Instanzen. Diese Klassen
halten nur eine Referenz auf die Dataclasses aus :mod:`r2wa.models` und
bringen keine eigene Logik mit - so bleibt die Auswertung dort testbar,
ohne dass GTK geladen werden muss.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GObject  # noqa: E402

from .models import Character, Item, Location, LootGroup, LootItem, World, Zone  # noqa: E402


class ItemObject(GObject.Object):
    """Ein Sammelobjekt in der Item-Liste."""

    __gtype_name__ = "R2waItemObject"

    def __init__(self, item: Item):
        super().__init__()
        self.item = item

    @GObject.Property(type=str, flags=GObject.ParamFlags.READABLE)
    def name(self) -> str:
        return self.item.name

    @GObject.Property(type=str, flags=GObject.ParamFlags.READABLE)
    def category(self) -> str:
        return self.item.category

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READABLE)
    def acquired(self) -> bool:
        return self.item.acquired


class CharacterObject(GObject.Object):
    """Ein Charakter in der Seitenleiste."""

    __gtype_name__ = "R2waCharacterObject"

    def __init__(self, character: Character):
        super().__init__()
        self.character = character


class TreeNode(GObject.Object):
    """Ein Knoten im Weltenbaum.

    Der Baum ist flach modelliert: jeder Knoten kennt seine Kinder als Liste
    von Rohobjekten und erzeugt sie erst, wenn Gtk.TreeListModel danach fragt.
    """

    __gtype_name__ = "R2waTreeNode"

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        icon: str | None = None,
        badge: str = "",
        payload: object = None,
        children: tuple[TreeNode, ...] = (),
        dim: bool = False,
    ):
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.badge = badge
        self.payload = payload
        self.children = children
        #: Abgeschlossenes oder eingesammeltes wird gedaempft dargestellt.
        self.dim = dim

    @property
    def expandable(self) -> bool:
        return bool(self.children)

    def child_model(self) -> Gio.ListStore | None:
        """Kindknoten als ListStore - Rueckgabewert fuer Gtk.TreeListModel."""
        if not self.children:
            return None
        store = Gio.ListStore.new(TreeNode)
        for child in self.children:
            store.append(child)
        return store


def build_world_nodes(world: World) -> tuple[TreeNode, ...]:
    """Baue den Knotenbaum einer gerollten Welt: Zone -> Ort -> Fundstelle."""
    return tuple(_zone_node(zone) for zone in world.zones)


def _zone_node(zone: Zone) -> TreeNode:
    open_items = zone.open_item_count
    details = [zone.story] if zone.story else []
    if zone.finished:
        details.append("abgeschlossen")

    return TreeNode(
        title=zone.name,
        subtitle=" · ".join(details),
        icon="map-symbolic",
        badge=str(open_items) if open_items else "",
        payload=zone,
        children=tuple(_location_node(loc) for loc in zone.locations),
        dim=zone.finished and not open_items,
    )


def _location_node(location: Location) -> TreeNode:
    marks: list[str] = []
    if location.trait_book and not location.trait_book_looted:
        marks.append("Eigenschaftsbuch")
    if location.simulacrum and not location.simulacrum_looted:
        marks.append("Simulacrum")
    if location.bloodmoon:
        marks.append("Blutmond")
    if location.vendors:
        marks.append("Händler: " + ", ".join(location.vendors))

    open_items = location.open_item_count
    return TreeNode(
        title=location.name,
        subtitle=" · ".join(marks) if marks else (location.category or ""),
        icon="mark-location-symbolic",
        badge=str(open_items) if open_items else "",
        payload=location,
        children=tuple(_group_node(group) for group in location.loot_groups),
        dim=not open_items,
    )


def _group_node(group: LootGroup) -> TreeNode:
    return TreeNode(
        title=group.label,
        subtitle=group.type or "",
        icon="package-x-generic-symbolic",
        payload=group,
        children=tuple(_loot_node(item) for item in group.items),
        dim=all(item.is_looted for item in group.items) if group.items else False,
    )


def _loot_node(item: LootItem) -> TreeNode:
    notes: list[str] = []
    if item.subcategory:
        notes.append(item.subcategory)
    if item.coop_only:
        notes.append("nur im Koop")
    if item.is_prerequisite_missing:
        notes.append("Voraussetzung fehlt")
    if not item.has_required_material and item.category == "mod":
        notes.append("Material fehlt")

    return TreeNode(
        title=item.name,
        subtitle=" · ".join(notes),
        icon="emblem-ok-symbolic" if item.is_looted else "list-add-symbolic",
        payload=item,
        dim=item.is_looted,
    )
