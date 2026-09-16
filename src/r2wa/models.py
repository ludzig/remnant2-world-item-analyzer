"""Data model of the analysis.

Deliberately plain Python without PyGObject: this way the whole evaluation
can be tested without GTK. The GObject wrappers for the list models live in
:mod:`r2wa.gobjects` and only hold a reference to these objects.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: Display order of the categories. Anything not listed here is appended
#: alphabetically at the end - that way a new category from a DLC stands out
#: instead of getting lost.
CATEGORY_ORDER = (
    "weapon",
    "mod",
    "mutator",
    "ring",
    "amulet",
    "armor",
    "relic",
    "fragment",
    "trait",
    "engram",
    "prism",
    "concoction",
    "consumable",
    "dream",
)

#: Display labels of the categories. Item names themselves stay as-is,
#: those are the terms from the game.
CATEGORY_LABELS = {
    "weapon": "Weapons",
    "mod": "Mods",
    "mutator": "Mutators",
    "ring": "Rings",
    "amulet": "Amulets",
    "armor": "Armor",
    "relic": "Relics",
    "fragment": "Relic Fragments",
    "trait": "Traits",
    "engram": "Engrams",
    "prism": "Prisms",
    "concoction": "Concoctions",
    "consumable": "Consumables",
    "dream": "Dreams",
}


def category_label(category: str) -> str:
    """Display label of a category, otherwise the raw name."""
    return CATEGORY_LABELS.get(category, category.capitalize())


def category_sort_key(category: str) -> tuple[int, str]:
    """Sort key according to :data:`CATEGORY_ORDER`."""
    try:
        return (CATEGORY_ORDER.index(category), "")
    except ValueError:
        return (len(CATEGORY_ORDER), category)


@dataclass(frozen=True, slots=True)
class CatalogItem:
    """Master data of a collectible item, independent of the character."""

    id: str
    name: str
    category: str
    subcategory: str | None = None
    world: str | None = None
    drop_type: str | None = None
    drop_reference: str | None = None
    note: str | None = None
    prerequisite: str | None = None
    coop_only: bool = False
    account_award: bool = False

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> CatalogItem:
        return cls(
            id=data["id"],
            name=data["name"],
            category=data["category"],
            subcategory=data.get("subcategory"),
            world=data.get("world"),
            drop_type=data.get("drop_type"),
            drop_reference=data.get("drop_reference"),
            note=data.get("note"),
            prerequisite=data.get("prerequisite"),
            coop_only=data.get("coop_only", False),
            account_award=data.get("account_award", False),
        )

    @property
    def source(self) -> str:
        """Short origin note, e.g. ``Vendor: Reggie``."""
        if self.drop_type and self.drop_reference:
            return f"{self.drop_type}: {self.drop_reference}"
        return self.drop_type or self.drop_reference or ""


@dataclass(frozen=True, slots=True)
class ItemState:
    """Ownership status of an item for one character."""

    id: str
    acquired: bool = False
    level: int | None = None
    quantity: int | None = None
    favorited: bool = False
    is_equipped: bool = False
    obtainable_in_campaign: bool | None = None
    obtainable_in_adventure: bool | None = None

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ItemState:
        return cls(
            id=data["id"],
            acquired=data.get("acquired", False),
            level=data.get("level"),
            quantity=data.get("quantity"),
            favorited=data.get("favorited", False),
            is_equipped=data.get("is_equipped", False),
            obtainable_in_campaign=data.get("obtainable_in_campaign"),
            obtainable_in_adventure=data.get("obtainable_in_adventure"),
        )

    @property
    def obtainable_now(self) -> bool:
        """Whether the item is reachable in one of the currently rolled worlds."""
        return bool(self.obtainable_in_campaign or self.obtainable_in_adventure)


@dataclass(frozen=True, slots=True)
class Item:
    """Master data and ownership status combined - the view the UI works with."""

    catalog: CatalogItem
    state: ItemState

    @property
    def id(self) -> str:
        return self.catalog.id

    @property
    def name(self) -> str:
        return self.catalog.name

    @property
    def category(self) -> str:
        return self.catalog.category

    @property
    def subcategory(self) -> str | None:
        return self.catalog.subcategory

    @property
    def acquired(self) -> bool:
        return self.state.acquired

    @property
    def search_text(self) -> str:
        """Precomputed search index - search runs over every row."""
        parts = [self.catalog.name, self.catalog.category]
        if self.catalog.subcategory:
            parts.append(self.catalog.subcategory)
        if self.catalog.drop_reference:
            parts.append(self.catalog.drop_reference)
        return " ".join(parts).casefold()

    def matches(self, needle: str) -> bool:
        return not needle or needle.casefold() in self.search_text


@dataclass(frozen=True, slots=True)
class CategoryCount:
    acquired: int = 0
    total: int = 0

    @property
    def missing(self) -> int:
        return self.total - self.acquired

    @property
    def fraction(self) -> float:
        return self.acquired / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class Counts:
    acquired: int = 0
    missing: int = 0
    total: int = 0
    acquired_reported: int = 0
    by_category: Mapping[str, CategoryCount] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Counts:
        return cls(
            acquired=data.get("acquired", 0),
            missing=data.get("missing", 0),
            total=data.get("total", 0),
            acquired_reported=data.get("acquired_reported", 0),
            by_category={
                name: CategoryCount(acquired=value.get("acquired", 0), total=value.get("total", 0))
                for name, value in (data.get("by_category") or {}).items()
            },
        )

    @property
    def fraction(self) -> float:
        return self.acquired / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class LootItem:
    id: str
    name: str
    category: str
    subcategory: str | None = None
    is_looted: bool = False
    has_required_material: bool = False
    is_prerequisite_missing: bool = False
    coop_only: bool = False

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> LootItem:
        return cls(
            id=data["id"],
            name=data["name"],
            category=data["category"],
            subcategory=data.get("subcategory"),
            is_looted=data.get("is_looted", False),
            has_required_material=data.get("has_required_material", False),
            is_prerequisite_missing=data.get("is_prerequisite_missing", False),
            coop_only=data.get("coop_only", False),
        )


@dataclass(frozen=True, slots=True)
class LootGroup:
    name: str | None
    type: str | None
    event_drop_reference: str | None
    items: tuple[LootItem, ...] = ()

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> LootGroup:
        return cls(
            name=data.get("name"),
            type=data.get("type"),
            event_drop_reference=data.get("event_drop_reference"),
            items=tuple(LootItem.from_json(i) for i in data.get("items", ())),
        )

    @property
    def label(self) -> str:
        return self.name or self.event_drop_reference or self.type or "Loot Location"


@dataclass(frozen=True, slots=True)
class Location:
    name: str
    category: str | None = None
    world: str | None = None
    world_stones: tuple[str, ...] = ()
    connections: tuple[str, ...] = ()
    vendors: tuple[str, ...] = ()
    trait_book: bool = False
    trait_book_looted: bool = False
    simulacrum: bool = False
    simulacrum_looted: bool = False
    bloodmoon: bool = False
    loot_groups: tuple[LootGroup, ...] = ()

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Location:
        return cls(
            name=data["name"],
            category=data.get("category"),
            world=data.get("world"),
            world_stones=tuple(data.get("world_stones", ())),
            connections=tuple(data.get("connections", ())),
            vendors=tuple(data.get("vendors", ())),
            trait_book=data.get("trait_book", False),
            trait_book_looted=data.get("trait_book_looted", False),
            simulacrum=data.get("simulacrum", False),
            simulacrum_looted=data.get("simulacrum_looted", False),
            bloodmoon=data.get("bloodmoon", False),
            loot_groups=tuple(LootGroup.from_json(g) for g in data.get("loot_groups", ())),
        )

    @property
    def items(self) -> Iterator[LootItem]:
        for group in self.loot_groups:
            yield from group.items

    def open_items(self, owned: Collection[str] = ()) -> Iterator[LootItem]:
        """Loot here that is still worth the walk.

        Two conditions, and both are needed. ``is_looted`` is about this
        world roll only - it says the drop has been taken or the alternate
        reward was chosen, so it is gone from *this* roll. It says nothing
        about whether the player owns the item, which they may well do from
        an earlier roll, the other mode or a vendor. An item already owned
        is not worth a trip either.
        """
        for item in self.items:
            if item.id not in owned and not item.is_looted:
                yield item

    def open_item_count(self, owned: Collection[str] = ()) -> int:
        """Number of items here the player neither owns nor has used up."""
        return sum(1 for _ in self.open_items(owned))


@dataclass(frozen=True, slots=True)
class Zone:
    name: str
    story: str | None = None
    finished: bool = False
    completes_biome: bool = False
    locations: tuple[Location, ...] = ()

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Zone:
        return cls(
            name=data["name"],
            story=data.get("story"),
            finished=data.get("finished", False),
            completes_biome=data.get("completes_biome", False),
            locations=tuple(Location.from_json(loc) for loc in data.get("locations", ())),
        )

    def open_item_count(self, owned: Collection[str] = ()) -> int:
        return sum(loc.open_item_count(owned) for loc in self.locations)


@dataclass(frozen=True, slots=True)
class World:
    slot: str
    difficulty: str | None = None
    playtime_seconds: float | None = None
    respawn_point: str | None = None
    zones: tuple[Zone, ...] = ()

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> World:
        return cls(
            slot=data["slot"],
            difficulty=data.get("difficulty"),
            playtime_seconds=data.get("playtime_seconds"),
            respawn_point=data.get("respawn_point"),
            zones=tuple(Zone.from_json(z) for z in data.get("zones", ())),
        )

    @property
    def label(self) -> str:
        return "Campaign" if self.slot == "campaign" else "Adventure"


@dataclass(frozen=True, slots=True)
class Character:
    index: int
    archetype: str | None = None
    secondary_archetype: str | None = None
    gender: str | None = None
    power_level: int = 0
    item_level: int = 0
    trait_rank: int = 0
    trait_points: int = 0
    is_hardcore: bool = False
    save_datetime: datetime | None = None
    active_world_slot: str = "campaign"
    playtime_seconds: float | None = None
    counts: Counts = field(default_factory=Counts)
    items: tuple[Item, ...] = ()
    worlds: tuple[World, ...] = ()

    @property
    def display_power_level(self) -> int:
        """Power level as the game's own HUD shows it.

        The save file's raw ``PowerLevel`` is consistently one lower than
        what Remnant 2 displays in-game (a quirk of the game's own save
        format, confirmed against the live HUD - not something the parser
        or this app introduces).
        """
        return self.power_level + 1

    @classmethod
    def from_json(cls, data: Mapping[str, Any], catalog: Mapping[str, CatalogItem]) -> Character:
        items = []
        for raw in data.get("item_states", ()):
            entry = catalog.get(raw["id"])
            # A state without a catalog entry can only happen on a schema
            # break; skipping it is better than crashing.
            if entry is not None:
                items.append(Item(catalog=entry, state=ItemState.from_json(raw)))

        return cls(
            index=data["index"],
            archetype=data.get("archetype"),
            secondary_archetype=data.get("secondary_archetype"),
            gender=data.get("gender"),
            power_level=data.get("power_level", 0),
            item_level=data.get("item_level", 0),
            trait_rank=data.get("trait_rank", 0),
            trait_points=data.get("trait_points", 0),
            is_hardcore=data.get("is_hardcore", False),
            save_datetime=_parse_datetime(data.get("save_datetime")),
            active_world_slot=data.get("active_world_slot", "campaign"),
            playtime_seconds=data.get("playtime_seconds"),
            counts=Counts.from_json(data.get("counts") or {}),
            items=tuple(items),
            worlds=tuple(World.from_json(w) for w in data.get("worlds", ())),
        )

    @property
    def title(self) -> str:
        """Display name in the sidebar."""
        classes = [c for c in (self.archetype, self.secondary_archetype) if c]
        return " / ".join(classes) if classes else f"Slot {self.index + 1}"

    def world(self, slot: str) -> World | None:
        return next((w for w in self.worlds if w.slot == slot), None)

    @property
    def owned_ids(self) -> frozenset[str]:
        """Ids of everything this character already has.

        The world loot knows only whether a drop is still lying there, not
        whether the item is already in the player's hands. Both answers are
        needed before calling a location worth visiting.
        """
        return frozenset(item.id for item in self.items if item.acquired)


@dataclass(frozen=True, slots=True)
class Analysis:
    """Full result of a parser run."""

    schema_version: int
    save_dir: str
    active_character_index: int = 0
    account_awards: tuple[str, ...] = ()
    catalog: Mapping[str, CatalogItem] = field(default_factory=dict)
    characters: tuple[Character, ...] = ()
    warnings: tuple[str, ...] = ()
    generator: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Analysis:
        catalog = {entry["id"]: CatalogItem.from_json(entry) for entry in data.get("catalog", ())}
        return cls(
            schema_version=data["schema_version"],
            save_dir=data.get("save_dir", ""),
            active_character_index=data.get("active_character_index", 0),
            account_awards=tuple(data.get("account_awards", ())),
            catalog=catalog,
            characters=tuple(Character.from_json(c, catalog) for c in data.get("characters", ())),
            warnings=tuple(data.get("warnings", ())),
            generator=dict(data.get("generator") or {}),
        )

    def character(self, index: int) -> Character | None:
        return next((c for c in self.characters if c.index == index), None)

    @property
    def active_character(self) -> Character | None:
        return self.character(self.active_character_index) or (
            self.characters[0] if self.characters else None
        )

    def aggregate_items(self) -> tuple[Item, ...]:
        """Combined collection status across all characters.

        In Remnant 2 most items belong to the character; but for the
        question "have I ever found this at all" the account is what
        counts. An item counts as found here as soon as any character
        owns it.
        """
        best: dict[str, Item] = {}
        for character in self.characters:
            for item in character.items:
                current = best.get(item.id)
                if current is None or (item.acquired and not current.acquired):
                    best[item.id] = item

        return tuple(
            sorted(
                best.values(),
                key=lambda i: (category_sort_key(i.category), i.name.casefold()),
            )
        )

    def aggregate_counts(self) -> Counts:
        """Counts matching :meth:`aggregate_items`."""
        return counts_for(self.aggregate_items())


def counts_for(items: Iterable[Item]) -> Counts:
    """Compute counts over an arbitrary item selection."""
    items = list(items)
    per_category: dict[str, list[int]] = {}
    for item in items:
        bucket = per_category.setdefault(item.category, [0, 0])
        bucket[1] += 1
        if item.acquired:
            bucket[0] += 1

    acquired = sum(1 for item in items if item.acquired)
    return Counts(
        acquired=acquired,
        missing=len(items) - acquired,
        total=len(items),
        acquired_reported=acquired,
        by_category={
            name: CategoryCount(acquired=values[0], total=values[1])
            for name, values in per_category.items()
        },
    )


def sort_items(items: Iterable[Item]) -> list[Item]:
    """Sort by category display order, then by name."""
    return sorted(items, key=lambda i: (category_sort_key(i.category), i.name.casefold()))


def group_by_category(items: Sequence[Item]) -> list[tuple[str, list[Item]]]:
    """Group items by category in display order."""
    groups: dict[str, list[Item]] = {}
    for item in items:
        groups.setdefault(item.category, []).append(item)

    return [
        (category, sorted(entries, key=lambda i: i.name.casefold()))
        for category, entries in sorted(groups.items(), key=lambda kv: category_sort_key(kv[0]))
    ]


def format_playtime(seconds: float | None) -> str:
    """``12345`` -> ``3 h 25 min``."""
    if not seconds:
        return "-"
    total_minutes = int(seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
