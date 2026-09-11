"""Maps catalog items to the metadata from the Remnant2Toolkit export.

The CSV export (``data/iteminfo.csv``) carries, for most items, a link to
the matching page on the Remnant wiki (wiki.gg). The item icon's image path
can be derived from the page name (see :mod:`r2wa.icon_fetch`).

The internal catalog ID (``Amulet_AbrasiveWhetstone``) and the CSV name
(``Abrasive Whetstone``) come from independent sources and don't always
match - for some items the analyzer already delivers the pretty name as
``name``, for the rest only the internal ID. The matching therefore
normalizes both sides (case, whitespace, and special characters removed)
and compares against both variants.

Alongside that export the module reads the two hand-maintained tables in
``data/``, for everything the export doesn't cover: the wiki pages of quest
items and materials, and the portrait filenames of the vendors and bosses.
"""

from __future__ import annotations

import csv
import os
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote, urlsplit

from .models import CatalogItem, LootItem

#: Root of the working directory, two levels up from src/r2wa/.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Location of the CSV export; overridable for tests and alternative data sets.
DEFAULT_ITEMINFO_CSV = REPO_ROOT / "data" / "iteminfo.csv"

#: Save-file slugs and CDN image paths, extracted from the toolkit's sources.
DEFAULT_TOOLKIT_CSV = REPO_ROOT / "data" / "toolkit_items.csv"

#: Wiki pages looked up by hand, for items no data source lists at all -
#: quest items and crafting materials. Doubles as a record of where the
#: matching file in ``data/manual_icons/`` came from.
DEFAULT_MANUAL_LINKS_CSV = REPO_ROOT / "data" / "manual_links.csv"

#: The name of a vendor or boss (as the save writes it), their portrait's
#: filename on the wiki, and their wiki page. Neither can be derived from
#: the name: "Reggie" is filed under his full name, "Nightweaver" under
#: "The Nightweaver", and the game's own spelling is not always the wiki's.
DEFAULT_PORTRAITS_CSV = REPO_ROOT / "data" / "portraits.csv"

#: Categories under which the catalog keeps items that sit under a different
#: name in the CSV export (armor is split there by piece).
CATEGORY_ALIASES: dict[str, frozenset[str]] = {
    "fragment": frozenset({"relicfragment"}),
    "armor": frozenset({"helm", "gloves", "legs", "torso"}),
}

_PREFIX_RE = re.compile(r"^(?:[A-Za-z0-9]+_)+")
_LOWER_UPPER_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_UPPER_UPPER_LOWER_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")

#: The account-wide catalog and a location's loot both carry id/name/category
#: - either can be matched against the CSV export the same way.
Lookupable = CatalogItem | LootItem


@dataclass(frozen=True, slots=True)
class ItemInfo:
    """A row from the CSV export, enriched with what the toolkit adds."""

    name: str
    category: str
    wiki_link: str | None
    toolkit_id: str | None = None

    #: Image path on the toolkit's own CDN, e.g. ``/items/amulets/x.png``.
    #: A fallback: it exists for items the wiki has no usable image for.
    image_path: str | None = None

    @property
    def wiki_slug(self) -> str | None:
        """The image path name derived from the wiki link (see module docstring)."""
        return _slug_from_wiki_link(self.wiki_link) if self.wiki_link else None

    @property
    def has_icon(self) -> bool:
        return bool(self.wiki_slug)


@dataclass(frozen=True, slots=True)
class Portrait:
    """A row from ``data/portraits.csv``: one vendor, boss or miniboss."""

    name: str
    image_file: str
    wiki_page: str


@dataclass(frozen=True, slots=True)
class ToolkitEntry:
    """A row from ``data/toolkit_items.csv``.

    ``save_file_slug`` is what the game itself writes into the save, so it
    matches the analyzer's catalog IDs verbatim - a far sturdier key than
    comparing display names.
    """

    save_file_slug: str
    toolkit_id: str
    name: str
    image_path: str | None


def _normalize(text: str) -> str:
    """Comparison key: camelCase split apart, only a-z0-9, lowercased."""
    text = _LOWER_UPPER_RE.sub(" ", text)
    text = _UPPER_UPPER_LOWER_RE.sub(" ", text)
    text = text.replace("_", " ")
    return _NON_ALNUM_RE.sub("", text.lower())


def prettify_id(raw: str) -> str:
    """Best effort at a readable name from an internal id.

    Only a fallback: for everything the export knows, its own spelling is
    better. The catalog does occasionally run ahead of the
    community-maintained export though, and "Blood Bond" still beats
    ``Trait_BloodBond`` in a list.
    """
    bare = _PREFIX_RE.sub("", raw)
    spaced = _LOWER_UPPER_RE.sub(" ", bare)
    spaced = _UPPER_UPPER_LOWER_RE.sub(" ", spaced)
    return spaced.replace("_", " ").strip() or raw


def _slug_from_wiki_link(link: str) -> str | None:
    """The path of a wiki.gg URL (without the domain) is the image path name.

    A simple ``rsplit("/", 1)`` would go wrong if the page title itself
    contains a slash (e.g. "Alpha / Omega") - the path must therefore be cut
    off after the host, not at the last "/". A slug with a remaining "/"
    could not be saved as a flat filename though; such outliers are
    therefore left without an icon instead of creating a directory.
    """
    path = urlsplit(link.strip()).path.strip("/")
    return path if path and "/" not in path else None


def load_rows(path: str | os.PathLike[str] = DEFAULT_ITEMINFO_CSV) -> list[ItemInfo]:
    """Read the CSV export. If the file is missing, there simply is no metadata."""
    path = Path(path)
    if not path.is_file():
        return []

    rows: list[ItemInfo] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            link = (raw.get("wikiLinks") or "").strip()
            rows.append(
                ItemInfo(
                    name=raw["name"],
                    category=raw["category"],
                    wiki_link=link or None,
                    toolkit_id=(raw.get("id") or "").strip() or None,
                )
            )
    return rows


def wiki_page_url(page: str) -> str:
    """The address of a wiki page, from its title.

    Same short form the CSV export uses; ``remnant.wiki`` redirects to
    ``remnant2.wiki.gg``.
    """
    return "https://remnant.wiki/" + quote(page.strip().replace(" ", "_"), safe="'()!*,-._~")


def load_manual_links(
    path: str | os.PathLike[str] = DEFAULT_MANUAL_LINKS_CSV,
) -> dict[str, str]:
    """Read the hand-collected wiki pages, keyed by the game's own item ID."""
    path = Path(path)
    if not path.is_file():
        return {}

    links: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            item_id = (raw.get("item_id") or "").strip()
            page = (raw.get("wiki_page") or "").strip()
            if item_id and page:
                links[item_id] = page
    return links


def load_portraits(
    path: str | os.PathLike[str] = DEFAULT_PORTRAITS_CSV,
) -> dict[str, Portrait]:
    """Read the portrait table, keyed by the name the save writes."""
    path = Path(path)
    if not path.is_file():
        return {}

    portraits: dict[str, Portrait] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("name") or "").strip()
            if not name:
                continue
            portraits[name.casefold()] = Portrait(
                name=name,
                image_file=(raw.get("image_file") or "").strip(),
                wiki_page=(raw.get("wiki_page") or "").strip(),
            )
    return portraits


def load_toolkit_rows(
    path: str | os.PathLike[str] = DEFAULT_TOOLKIT_CSV,
) -> list[ToolkitEntry]:
    """Read the toolkit export. Missing file means: no save-file-slug matching."""
    path = Path(path)
    if not path.is_file():
        return []

    rows: list[ToolkitEntry] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            slug = (raw.get("save_file_slug") or "").strip()
            if not slug:
                continue
            rows.append(
                ToolkitEntry(
                    save_file_slug=slug,
                    toolkit_id=(raw.get("toolkit_id") or "").strip(),
                    name=(raw.get("name") or "").strip(),
                    image_path=(raw.get("image_path") or "").strip() or None,
                )
            )
    return rows


class ItemInfoIndex:
    """Lookup table from a catalog item to its CSV metadata."""

    def __init__(self, rows: list[ItemInfo], toolkit: list[ToolkitEntry] | None = None) -> None:
        self._by_name: dict[str, list[ItemInfo]] = defaultdict(list)
        for row in rows:
            self._by_name[_normalize(row.name)].append(row)

        by_toolkit_id = {row.toolkit_id: row for row in rows if row.toolkit_id}

        # Keyed by save-file slug, which equals the analyzer's catalog ID.
        # A list, because the toolkit's data has a couple of slugs sitting on
        # two different items - those get decided by name at lookup time
        # rather than guessed here.
        self._by_slug: dict[str, list[ItemInfo]] = defaultdict(list)
        for entry in toolkit or ():
            base = by_toolkit_id.get(entry.toolkit_id)
            if base is not None:
                info = replace(base, image_path=entry.image_path)
            else:
                # Known to the toolkit but absent from the CSV export: still
                # good for an icon, just without a wiki link.
                info = ItemInfo(
                    name=entry.name,
                    category="",
                    wiki_link=None,
                    toolkit_id=entry.toolkit_id or None,
                    image_path=entry.image_path,
                )
            self._by_slug[entry.save_file_slug.casefold()].append(info)

    def lookup(self, item: Lookupable) -> ItemInfo | None:
        """Find the CSV row for a catalog item, if any.

        The save-file slug is tried first - it is what the game writes into
        the save, so it matches exactly. Only if that finds nothing does the
        name comparison take over: first the name the analyzer provides,
        then - if that is just the internal ID - the ID with its category
        prefix stripped.
        """
        exact = self._by_slug.get(item.id.casefold())
        if exact:
            resolved = self._disambiguate(exact, item)
            if resolved is not None:
                return resolved

        for key in self._candidate_keys(item):
            candidates = self._by_name.get(key)
            if candidates:
                return self._pick(candidates, item.category)
        return None

    @classmethod
    def _disambiguate(cls, candidates: list[ItemInfo], item: Lookupable) -> ItemInfo | None:
        """Pick between entries sharing one slug - or give up rather than guess."""
        if len(candidates) == 1:
            return candidates[0]

        keys = set(cls._candidate_keys(item))
        for candidate in candidates:
            if _normalize(candidate.name) in keys:
                return candidate
        return None

    @staticmethod
    def _candidate_keys(item: Lookupable) -> list[str]:
        keys = [_normalize(item.name)]
        bare_id = _PREFIX_RE.sub("", item.id)
        if bare_id != item.name:
            keys.append(_normalize(bare_id))
        return keys

    @staticmethod
    def _pick(candidates: list[ItemInfo], category: str) -> ItemInfo:
        wanted = {category} | CATEGORY_ALIASES.get(category, frozenset())
        for candidate in candidates:
            if candidate.category in wanted:
                return candidate
        return candidates[0]


def build_index(
    path: str | os.PathLike[str] = DEFAULT_ITEMINFO_CSV,
    toolkit_path: str | os.PathLike[str] = DEFAULT_TOOLKIT_CSV,
) -> ItemInfoIndex:
    return ItemInfoIndex(load_rows(path), load_toolkit_rows(toolkit_path))
