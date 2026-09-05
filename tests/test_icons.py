"""Tests of the icon lookup, including the manual-icon override."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from r2wa import iteminfo  # noqa: E402
from r2wa.icons import IconLookup  # noqa: E402
from r2wa.models import CatalogItem  # noqa: E402


def _item(item_id: str, name: str, category: str) -> CatalogItem:
    return CatalogItem(id=item_id, name=name, category=category)


def _write_csv(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    path = tmp_path / "iteminfo.csv"
    header = "id,name,category,description,wikiLinks\n"
    body = "\n".join(
        f"{r['id']},{r['name']},{r['category']},{r.get('description', '')},{r.get('wikiLinks', '')}"
        for r in rows
    )
    path.write_text(header + body + "\n", encoding="utf-8")
    return path


def _write_toolkit_csv(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    path = tmp_path / "toolkit_items.csv"
    header = "save_file_slug,toolkit_id,name,image_path\n"
    body = "\n".join(
        f"{r['save_file_slug']},{r.get('toolkit_id', '')},{r.get('name', '')},"
        f"{r.get('image_path', '')}"
        for r in rows
    )
    path.write_text(header + body + "\n", encoding="utf-8")
    return path


def _write_links_csv(tmp_path: Path, rows: dict[str, str]) -> Path:
    path = tmp_path / "manual_links.csv"
    body = "\n".join(f"{k},{v}" for k, v in rows.items())
    path.write_text("item_id,wiki_page\n" + body + "\n", encoding="utf-8")
    return path


def _write_portraits_csv(tmp_path: Path, rows: dict[str, tuple[str, str]]) -> Path:
    path = tmp_path / "portraits.csv"
    writer_rows = "\n".join(f'"{name}","{f}","{page}"' for name, (f, page) in rows.items())
    path.write_text("name,image_file,wiki_page\n" + writer_rows + "\n", encoding="utf-8")
    return path


def _make_lookup(
    tmp_path: Path,
    csv_rows: list[dict[str, str]],
    toolkit_rows: list[dict[str, str]] | None = None,
    link_rows: dict[str, str] | None = None,
    portrait_rows: dict[str, tuple[str, str]] | None = None,
) -> IconLookup:
    # Explicit paths throughout, so no test ever reaches the real data files.
    toolkit_path = (
        _write_toolkit_csv(tmp_path, toolkit_rows)
        if toolkit_rows
        else tmp_path / "kein-toolkit.csv"
    )
    links_path = _write_links_csv(tmp_path, link_rows) if link_rows else tmp_path / "keine.csv"
    portraits_path = (
        _write_portraits_csv(tmp_path, portrait_rows)
        if portrait_rows
        else tmp_path / "keine-portraits.csv"
    )
    index = iteminfo.build_index(_write_csv(tmp_path, csv_rows), toolkit_path)
    icons_dir = tmp_path / "icons"
    icons_dir.mkdir()
    manual_dir = tmp_path / "manual_icons"
    manual_dir.mkdir()
    return IconLookup(
        index=index,
        icons_dir=icons_dir,
        manual_icons_dir=manual_dir,
        manual_links_path=links_path,
        portraits_path=portraits_path,
    )


class TestIconLookup:
    def test_manueller_pfad_hat_vorrang_vor_wiki_slug(self, tmp_path: Path) -> None:
        lookup = _make_lookup(
            tmp_path,
            [
                {
                    "id": "x",
                    "name": "Alpha / Omega",
                    "category": "weapon",
                    "wikiLinks": "https://remnant.wiki/Alpha_/_Omega",
                }
            ],
        )
        # The "/" in the wiki title means no wiki_slug can be derived at all -
        # the manual icon is the only way this item ever gets a picture.
        manual = lookup._manual_icons_dir / "Weapon_AlphaOmega.png"
        manual.write_bytes(b"not-a-real-png")

        item = _item("Weapon_AlphaOmega", "Alpha / Omega", "weapon")

        assert lookup.path_for(item) == manual

    def test_ohne_manuelles_icon_wird_der_abgeleitete_pfad_verwendet(self, tmp_path: Path) -> None:
        lookup = _make_lookup(
            tmp_path,
            [
                {
                    "id": "x",
                    "name": "Abrasive Whetstone",
                    "category": "amulet",
                    "wikiLinks": "https://remnant.wiki/Abrasive_Whetstone",
                }
            ],
        )
        derived = lookup._icons_dir / "Abrasive_Whetstone.png"
        derived.write_bytes(b"not-a-real-png")

        item = _item("Amulet_AbrasiveWhetstone", "Amulet_AbrasiveWhetstone", "amulet")

        assert lookup.path_for(item) == derived

    def test_ohne_jedes_icon_gibt_es_none(self, tmp_path: Path) -> None:
        lookup = _make_lookup(
            tmp_path,
            [
                {
                    "id": "x",
                    "name": "Abrasive Whetstone",
                    "category": "amulet",
                    "wikiLinks": "https://remnant.wiki/Abrasive_Whetstone",
                }
            ],
        )
        item = _item("Amulet_AbrasiveWhetstone", "Amulet_AbrasiveWhetstone", "amulet")

        assert lookup.path_for(item) is None


class TestToolkitFallback:
    CSV = [
        {
            "id": "3aqiq5",
            "name": "Ammo Reserves",
            "category": "relicfragment",
            "wikiLinks": "https://remnant.wiki/Relic_Fragment",
        }
    ]
    TOOLKIT = [
        {
            "save_file_slug": "RelicFragment_AmmoReserves",
            "toolkit_id": "3aqiq5",
            "name": "Ammo Reserves",
            "image_path": "/items/relicfragments/ammo-reserves-on.png",
        }
    ]

    def test_cdn_bild_wird_genutzt_wenn_das_wiki_nichts_hat(self, tmp_path: Path) -> None:
        lookup = _make_lookup(tmp_path, self.CSV, self.TOOLKIT)
        cdn = lookup._icons_dir / "toolkit" / "ammo-reserves-on.png"
        cdn.parent.mkdir()
        cdn.write_bytes(b"not-a-real-png")

        item = _item("RelicFragment_AmmoReserves", "RelicFragment_AmmoReserves", "fragment")

        assert lookup.path_for(item) == cdn

    def test_wiki_bild_hat_vorrang_vor_dem_cdn(self, tmp_path: Path) -> None:
        lookup = _make_lookup(tmp_path, self.CSV, self.TOOLKIT)
        wiki = lookup._icons_dir / "Relic_Fragment.png"
        wiki.write_bytes(b"not-a-real-png")
        cdn = lookup._icons_dir / "toolkit" / "ammo-reserves-on.png"
        cdn.parent.mkdir()
        cdn.write_bytes(b"not-a-real-png")

        item = _item("RelicFragment_AmmoReserves", "RelicFragment_AmmoReserves", "fragment")

        # The wiki image is the larger one and its licence is the clear one.
        assert lookup.path_for(item) == wiki


class TestWikiLink:
    CSV = [
        {
            "id": "x",
            "name": "Abrasive Whetstone",
            "category": "amulet",
            "wikiLinks": "https://remnant.wiki/Abrasive_Whetstone",
        }
    ]

    def test_link_aus_dem_export(self, tmp_path: Path) -> None:
        lookup = _make_lookup(tmp_path, self.CSV)

        item = _item("Amulet_AbrasiveWhetstone", "Amulet_AbrasiveWhetstone", "amulet")

        assert lookup.wiki_url_for(item) == "https://remnant.wiki/Abrasive_Whetstone"

    def test_handgepflegter_link_fuer_unbekanntes_item(self, tmp_path: Path) -> None:
        # Quest items and materials appear in no data source at all, so this
        # mapping is the only way they ever get a link.
        lookup = _make_lookup(
            tmp_path, self.CSV, link_rows={"Material_ShinningEssenceEcho": "Shining Essence Echo"}
        )

        item = _item("Material_ShinningEssenceEcho", "Shining Essence Echo", "material")

        assert lookup.wiki_url_for(item) == "https://remnant.wiki/Shining_Essence_Echo"

    def test_handgepflegter_link_hat_vorrang(self, tmp_path: Path) -> None:
        lookup = _make_lookup(
            tmp_path, self.CSV, link_rows={"Amulet_AbrasiveWhetstone": "Somewhere Else"}
        )

        item = _item("Amulet_AbrasiveWhetstone", "Amulet_AbrasiveWhetstone", "amulet")

        assert lookup.wiki_url_for(item) == "https://remnant.wiki/Somewhere_Else"

    def test_ohne_jede_quelle_kein_link(self, tmp_path: Path) -> None:
        lookup = _make_lookup(tmp_path, self.CSV)

        assert lookup.wiki_url_for(_item("Weapon_Unbekannt", "Weapon_Unbekannt", "weapon")) is None


class TestWikiPageUrl:
    def test_leerzeichen_werden_unterstriche(self) -> None:
        assert (
            iteminfo.wiki_page_url("Crimson King Coin") == "https://remnant.wiki/Crimson_King_Coin"
        )

    def test_apostroph_bleibt_erhalten(self) -> None:
        # Escaping it would break the link; the wiki serves it verbatim.
        assert iteminfo.wiki_page_url("Kolket's Key") == "https://remnant.wiki/Kolket's_Key"


class TestPortraits:
    CSV: list[dict[str, str]] = []
    PORTRAITS = {
        "Reggie": ("Reginald_Reggie_Malone.jpg", "Reggie"),
        "Wallace": ("Wallace.jpg", "Wallace"),
        "Bruin, Blade of The King": ("Bruin,_Blade_of_the_King.jpg", "Bruin, Blade of the King"),
        "Cinderclad Forge": ("Cinderclad_Forge.jpg", "Cinderclad Forge"),
        "Cinderclad Monolith": ("Cinderclad_Forge.jpg", "Cinderclad Forge"),
        "Norah": ("Dr._Norah.jpg", "Dr. Norah"),
    }

    def _mit_portraet(self, tmp_path: Path, *image_files: str) -> IconLookup:
        lookup = _make_lookup(tmp_path, self.CSV, portrait_rows=self.PORTRAITS)
        for image_file in image_files:
            portrait = lookup._icons_dir / "portraits" / image_file
            portrait.parent.mkdir(exist_ok=True)
            portrait.write_bytes(b"not-a-real-jpeg")
        return lookup

    def test_portraet_wird_ueber_den_namen_gefunden(self, tmp_path: Path) -> None:
        lookup = self._mit_portraet(tmp_path, "Wallace.jpg")

        assert lookup.portrait_for("Wallace") == lookup._icons_dir / "portraits" / "Wallace.jpg"

    def test_dateiname_muss_nicht_dem_namen_entsprechen(self, tmp_path: Path) -> None:
        # The save says "Reggie"; the wiki files him under his full name.
        lookup = self._mit_portraet(tmp_path, "Reginald_Reggie_Malone.jpg")

        found = lookup.portrait_for("Reggie")

        assert found is not None and found.name == "Reginald_Reggie_Malone.jpg"

    def test_komma_im_namen_ueberlebt_die_csv(self, tmp_path: Path) -> None:
        # "Bruin, Blade of The King" - a quoted field, not two columns.
        lookup = self._mit_portraet(tmp_path, "Bruin,_Blade_of_the_King.jpg")

        assert lookup.portrait_for("Bruin, Blade of The King") is not None

    def test_zwei_namen_duerfen_sich_ein_bild_teilen(self, tmp_path: Path) -> None:
        # The wiki redirects "Cinderclad Monolith" to "Cinderclad Forge".
        lookup = self._mit_portraet(tmp_path, "Cinderclad_Forge.jpg")

        assert lookup.portrait_for("Cinderclad Monolith") == lookup.portrait_for("Cinderclad Forge")

    def test_gross_kleinschreibung_egal(self, tmp_path: Path) -> None:
        # The name arrives as a loot group's label, not as an id.
        lookup = self._mit_portraet(tmp_path, "Wallace.jpg")

        assert lookup.portrait_for("  wallace ") is not None

    def test_ohne_heruntergeladenes_bild_gibt_es_none(self, tmp_path: Path) -> None:
        lookup = _make_lookup(tmp_path, self.CSV, portrait_rows=self.PORTRAITS)

        assert lookup.portrait_for("Wallace") is None

    def test_unbekannter_name_gibt_none(self, tmp_path: Path) -> None:
        lookup = self._mit_portraet(tmp_path, "Wallace.jpg")

        assert lookup.portrait_for("World Drop") is None

    def test_wiki_seite_kommt_aus_der_tabelle(self, tmp_path: Path) -> None:
        # The save says "Norah"; the wiki has no such page, only "Dr. Norah".
        lookup = _make_lookup(tmp_path, self.CSV, portrait_rows=self.PORTRAITS)

        assert lookup.portrait_wiki_url_for("Norah") == "https://remnant.wiki/Dr._Norah"

    def test_link_auch_ohne_heruntergeladenes_bild(self, tmp_path: Path) -> None:
        # The two are independent: the table knows the page either way.
        lookup = _make_lookup(tmp_path, self.CSV, portrait_rows=self.PORTRAITS)

        assert lookup.portrait_for("Wallace") is None
        assert lookup.portrait_wiki_url_for("Wallace") == "https://remnant.wiki/Wallace"

    def test_ohne_eintrag_kein_link(self, tmp_path: Path) -> None:
        lookup = _make_lookup(tmp_path, self.CSV, portrait_rows=self.PORTRAITS)

        assert lookup.portrait_wiki_url_for("World Drop") is None
