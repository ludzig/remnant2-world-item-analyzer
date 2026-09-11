"""Tests of the matching between catalog items and the CSV export."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from r2wa import iteminfo  # noqa: E402
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


def _index(tmp_path: Path, rows, toolkit_rows=None) -> iteminfo.ItemInfoIndex:
    """Index over the given rows only - never the repository's real data files."""
    toolkit_path = (
        _write_toolkit_csv(tmp_path, toolkit_rows)
        if toolkit_rows
        else tmp_path / "kein-toolkit.csv"
    )
    return iteminfo.build_index(_write_csv(tmp_path, rows), toolkit_path)


class TestLoadRows:
    def test_fehlende_datei_liefert_leere_liste(self, tmp_path: Path) -> None:
        assert iteminfo.load_rows(tmp_path / "gibt-es-nicht.csv") == []

    def test_wiki_link_wird_zum_slug(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
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

        rows = iteminfo.load_rows(csv_path)

        assert rows[0].wiki_slug == "Abrasive_Whetstone"
        assert rows[0].has_icon

    def test_leerer_wiki_link_ergibt_keinen_slug(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path, [{"id": "x", "name": "Longevity", "category": "fusion", "wikiLinks": ""}]
        )

        rows = iteminfo.load_rows(csv_path)

        assert rows[0].wiki_slug is None
        assert not rows[0].has_icon


class TestItemInfoIndex:
    def test_findet_ueber_huebschen_namen(self, tmp_path: Path) -> None:
        index = _index(
            tmp_path,
            [
                {
                    "id": "x",
                    "name": "Academic's Gloves",
                    "category": "gloves",
                    "wikiLinks": "https://remnant.wiki/Academic%27s_Gloves",
                }
            ],
        )
        # The analyzer already delivers the pretty name as CatalogItem.name here.
        item = _item("Armor_Gloves_Alchemist", "Academic's Gloves", "armor")

        result = index.lookup(item)

        assert result is not None
        assert result.wiki_slug == "Academic%27s_Gloves"

    def test_findet_ueber_interne_id_ohne_praefix(self, tmp_path: Path) -> None:
        index = _index(
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
        # The analyzer only delivers the internal ID as name here (the most common case).
        item = _item("Amulet_AbrasiveWhetstone", "Amulet_AbrasiveWhetstone", "amulet")

        result = index.lookup(item)

        assert result is not None
        assert result.name == "Abrasive Whetstone"

    def test_kein_treffer_liefert_none(self, tmp_path: Path) -> None:
        index = _index(
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
        item = _item("Weapon_NichtImExport", "Weapon_NichtImExport", "weapon")

        assert index.lookup(item) is None

    def test_gleicher_name_in_anderer_kategorie_wird_ueber_kategorie_entschieden(
        self, tmp_path: Path
    ) -> None:
        # Real case in the export: "Vigor" exists as a pylon and as a trait.
        index = _index(
            tmp_path,
            [
                {
                    "id": "a",
                    "name": "Vigor",
                    "category": "pylon",
                    "wikiLinks": "https://remnant.wiki/Vigor_(Pylon)",
                },
                {
                    "id": "b",
                    "name": "Vigor",
                    "category": "trait",
                    "wikiLinks": "https://remnant.wiki/Vigor",
                },
            ],
        )
        item = _item("Trait_Vigor", "Trait_Vigor", "trait")

        result = index.lookup(item)

        assert result is not None
        assert result.category == "trait"

    def test_ruestungskategorien_werden_ueber_alias_gefunden(self, tmp_path: Path) -> None:
        index = _index(
            tmp_path,
            [
                {
                    "id": "x",
                    "name": "Cultist Gloves",
                    "category": "gloves",
                    "wikiLinks": "https://remnant.wiki/Cultist_Gloves",
                }
            ],
        )
        item = _item("Armor_Gloves_Cultist", "Cultist Gloves", "armor")

        result = index.lookup(item)

        assert result is not None
        assert result.wiki_slug == "Cultist_Gloves"


class TestSaveFileSlug:
    """Matching via the slug the game itself writes into the save."""

    CSV = [
        {
            "id": "umb305",
            "name": "Feral Judgement",
            "category": "weapon",
            "wikiLinks": "https://remnant.wiki/Feral_Judgement",
        }
    ]
    TOOLKIT = [
        {
            "save_file_slug": "Weapon_FeralJudgment",
            "toolkit_id": "umb305",
            "name": "Feral Judgement",
            "image_path": "/items/weapons/feraljudgement.png",
        }
    ]

    def test_schreibvariante_wird_ueber_slug_gefunden(self, tmp_path: Path) -> None:
        # The export spells it "Judgement", the analyzer "Judgment" - no
        # amount of name normalization bridges that, the slug does.
        index = _index(tmp_path, self.CSV, self.TOOLKIT)

        result = index.lookup(_item("Weapon_FeralJudgment", "Weapon_FeralJudgment", "weapon"))

        assert result is not None
        assert result.wiki_slug == "Feral_Judgement"
        assert result.image_path == "/items/weapons/feraljudgement.png"

    def test_ohne_toolkit_bleibt_die_schreibvariante_unauffindbar(self, tmp_path: Path) -> None:
        index = _index(tmp_path, self.CSV)

        assert index.lookup(_item("Weapon_FeralJudgment", "Weapon_FeralJudgment", "weapon")) is None

    def test_eintrag_ohne_csv_zeile_liefert_wenigstens_das_bild(self, tmp_path: Path) -> None:
        index = _index(tmp_path, [], self.TOOLKIT)

        result = index.lookup(_item("Weapon_FeralJudgment", "Weapon_FeralJudgment", "weapon"))

        assert result is not None
        assert result.wiki_link is None
        assert result.image_path == "/items/weapons/feraljudgement.png"

    def test_mehrdeutiger_slug_wird_ueber_den_namen_entschieden(self, tmp_path: Path) -> None:
        # Real flaw in the toolkit's data: "Consumable Duration" carries the
        # slug of "Critical Damage".
        toolkit = [
            {
                "save_file_slug": "RelicFragment_CriticalDamage",
                "toolkit_id": "a",
                "name": "Consumable Duration",
                "image_path": "/items/relicfragments/consumable-duration-on.png",
            },
            {
                "save_file_slug": "RelicFragment_CriticalDamage",
                "toolkit_id": "b",
                "name": "Critical Damage",
                "image_path": "/items/relicfragments/critical-damage-on.png",
            },
        ]
        index = _index(tmp_path, [], toolkit)

        result = index.lookup(
            _item("RelicFragment_CriticalDamage", "RelicFragment_CriticalDamage", "fragment")
        )

        assert result is not None
        assert result.name == "Critical Damage"

    def test_mehrdeutiger_slug_wird_notfalls_ueber_die_id_entschieden(self, tmp_path: Path) -> None:
        # The toolkit's other duplicate: "Lucky" and "Scavenger" share a slug.
        # Here the ID's own suffix settles it.
        toolkit = [
            {
                "save_file_slug": "Perk_Lucky",
                "toolkit_id": "a",
                "name": "Lucky",
                "image_path": "/a.png",
            },
            {
                "save_file_slug": "Perk_Lucky",
                "toolkit_id": "b",
                "name": "Scavenger",
                "image_path": "/b.png",
            },
        ]
        index = _index(tmp_path, [], toolkit)

        result = index.lookup(_item("Perk_Lucky", "Perk_Lucky", "perk"))

        assert result is not None
        assert result.name == "Lucky"

    def test_unaufloesbar_mehrdeutiger_slug_wird_nicht_geraten(self, tmp_path: Path) -> None:
        toolkit = [
            {
                "save_file_slug": "Perk_Mystery",
                "toolkit_id": "a",
                "name": "Alpha",
                "image_path": "/a.png",
            },
            {
                "save_file_slug": "Perk_Mystery",
                "toolkit_id": "b",
                "name": "Beta",
                "image_path": "/b.png",
            },
        ]
        index = _index(tmp_path, [], toolkit)

        # Neither name resembles the item, so picking one would be a coin
        # flip - and a wrong icon is worse than none.
        assert index.lookup(_item("Perk_Mystery", "Perk_Mystery", "perk")) is None


@pytest.mark.parametrize(
    ("item_id", "csv_name"),
    [
        ("Amulet_BrokenPocketWatch", "Broken Pocket Watch"),
        ("Ring_ProbabilityCord", "Probability Cord"),
        ("Relic_Consumable_BloodlessHeart", "Bloodless Heart"),
    ],
)
def test_praefixe_werden_vollstaendig_abgeschnitten(
    tmp_path: Path, item_id: str, csv_name: str
) -> None:
    index = _index(
        tmp_path, [{"id": "x", "name": csv_name, "category": "misc", "wikiLinks": "https://x/y"}]
    )

    item = _item(item_id, item_id, "misc")

    assert index.lookup(item) is not None


class TestPrettifyId:
    def test_prefix_faellt_weg_und_camelcase_wird_getrennt(self) -> None:
        assert iteminfo.prettify_id("Trait_BloodBond") == "Blood Bond"

    def test_mehrfaches_praefix(self) -> None:
        assert iteminfo.prettify_id("Quest_Item_CrimsonKingCoin") == "Crimson King Coin"

    def test_grossbuchstabenfolge_bleibt_zusammen(self) -> None:
        # "N'Erudian" and the like must not be torn apart letter by letter.
        assert iteminfo.prettify_id("Weapon_XMGCarbine") == "XMG Carbine"

    def test_ohne_praefix_bleibt_der_name(self) -> None:
        assert iteminfo.prettify_id("Amplitude") == "Amplitude"
