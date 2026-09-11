"""Links catalog items to locally cached icon files.

The icons themselves are downloaded once by ``just fetch-icons`` (see
:mod:`r2wa.icon_fetch`); at UI runtime only a local lookup happens, so
showing the items doesn't depend on a network connection.

A handful of items can't be resolved that way at all - a literal "/" in the
wiki title, a spelling variant between the CSV export and the analyzer, a
typo in the CSV's link - their icons were saved by hand instead, into
``data/manual_icons/`` under the catalog item's own id. Those take priority
over the derived-slug lookup.

Whole categories can be missing too: neither data source lists crafting
materials, and quest items only appear in a location's loot, never in the
catalog. Anything found there needs a hand-picked icon, named after the id
the game itself uses - typos included (``Material_ShinningEssenceEcho``).

Vendors and bosses are not items and appear in neither source, so their
portraits go through :meth:`IconLookup.portrait_for` and their own mapping
file.
"""

from __future__ import annotations

from pathlib import Path

from .icon_fetch import DEFAULT_ICONS_DIR, icon_path, portrait_path, toolkit_icon_path
from .iteminfo import (
    DEFAULT_MANUAL_LINKS_CSV,
    DEFAULT_PORTRAITS_CSV,
    ItemInfoIndex,
    Lookupable,
    build_index,
    load_manual_links,
    load_portraits,
    prettify_id,
    wiki_page_url,
)
from .paths import data_dir

#: Hand-picked icons for items the automated pipeline can't derive a slug for.
DEFAULT_MANUAL_ICONS_DIR = data_dir() / "manual_icons"


class IconLookup:
    """Maps a catalog item to its local icon file, if any."""

    def __init__(
        self,
        index: ItemInfoIndex | None = None,
        icons_dir: str | Path = DEFAULT_ICONS_DIR,
        manual_icons_dir: str | Path = DEFAULT_MANUAL_ICONS_DIR,
        manual_links_path: str | Path = DEFAULT_MANUAL_LINKS_CSV,
        portraits_path: str | Path = DEFAULT_PORTRAITS_CSV,
    ) -> None:
        self._index = index if index is not None else build_index()
        self._icons_dir = Path(icons_dir)
        self._manual_icons_dir = Path(manual_icons_dir)
        self._manual_links = load_manual_links(manual_links_path)
        self._portraits = load_portraits(portraits_path)

    def path_for(self, item: Lookupable) -> Path | None:
        """The best icon available, in descending order of preference.

        Hand-picked first, then the wiki's (the larger image, under a clear
        licence), and only then the toolkit's CDN copy - which is the only
        source for things like the individual relic fragments.
        """
        manual = self._manual_icons_dir / f"{item.id}.png"
        if manual.is_file():
            return manual

        info = self._index.lookup(item)
        if info is None:
            return None

        if info.wiki_slug:
            path = icon_path(info.wiki_slug, self._icons_dir)
            if path.is_file():
                return path

        if info.image_path:
            path = toolkit_icon_path(info.image_path, self._icons_dir)
            if path.is_file():
                return path

        return None

    def wiki_url_for(self, item: Lookupable) -> str | None:
        """The wiki page for an item, if one is known.

        Independent of :meth:`path_for`: a page can exist even where the
        image filename couldn't be derived (see ``_slug_from_wiki_link``),
        and quest items and materials have a page but appear in no data
        source - those are the hand-collected ones.
        """
        page = self._manual_links.get(item.id)
        if page:
            return wiki_page_url(page)

        info = self._index.lookup(item)
        return info.wiki_link if info else None

    def portrait_for(self, name: str) -> Path | None:
        """The portrait of a vendor or boss, by the name the save file uses.

        Matched case-insensitively, because that name reaches us as a loot
        group's label rather than as an id.
        """
        entry = self._portraits.get(name.strip().casefold())
        if entry is None or not entry.image_file:
            return None

        path = portrait_path(entry.image_file, self._icons_dir)
        return path if path.is_file() else None

    def portrait_wiki_url_for(self, name: str) -> str | None:
        """The wiki page of a vendor or boss.

        Independent of :meth:`portrait_for`: the page is known from the
        table alone, whether or not the picture has been downloaded.
        """
        entry = self._portraits.get(name.strip().casefold())
        if entry is None or not entry.wiki_page:
            return None
        return wiki_page_url(entry.wiki_page)

    def display_name_for(self, item: Lookupable) -> str:
        """The name a player would recognise.

        For a good half of the catalog the analyzer has no display name and
        puts the internal id in ``name`` instead - every single trait among
        them. The metadata export is what knows the real one. Where the
        analyzer does deliver a name it is kept: it comes from the game
        itself and is the more authoritative spelling of the two.
        """
        if item.name != item.id:
            return item.name

        info = self._index.lookup(item)
        if info is not None and info.name:
            return info.name
        return prettify_id(item.id)
