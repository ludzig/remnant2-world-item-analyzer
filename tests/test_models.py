"""Tests of the data model against the fixture."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from r2wa import models  # noqa: E402
from r2wa.models import Analysis  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "analysis_minimal.json"


@pytest.fixture(scope="module")
def analysis() -> Analysis:
    return Analysis.from_json(json.loads(FIXTURE.read_text(encoding="utf-8")))


class TestAnalysis:
    def test_liest_kopfdaten(self, analysis: Analysis) -> None:
        assert analysis.schema_version == 1
        assert analysis.active_character_index == 1
        assert len(analysis.catalog) == 7
        assert len(analysis.characters) == 2
        assert analysis.warnings == (
            "Slot 0: reachability of 'Amulet_OneTrueKingSigil' could not be determined.",
        )

    def test_aktiver_charakter(self, analysis: Analysis) -> None:
        assert analysis.active_character is not None
        assert analysis.active_character.index == 1

    def test_faellt_auf_ersten_charakter_zurueck(self, analysis: Analysis) -> None:
        # An index that doesn't exist must not leave the UI empty.
        broken = Analysis(
            schema_version=1,
            save_dir="",
            active_character_index=99,
            catalog=analysis.catalog,
            characters=analysis.characters,
        )

        assert broken.active_character is not None
        assert broken.active_character.index == 0

    def test_ohne_charaktere_kein_aktiver(self) -> None:
        assert Analysis(schema_version=1, save_dir="").active_character is None


class TestCharacter:
    def test_verbindet_zustand_mit_katalog(self, analysis: Analysis) -> None:
        character = analysis.character(0)
        assert character is not None

        ring = next(i for i in character.items if i.id == "Ring_ProbabilityCord")
        assert ring.name == "Probability Cord"
        assert ring.category == "ring"
        assert ring.acquired is True
        assert ring.catalog.drop_reference == "The Far Woods"

    def test_titel_aus_archetypen(self, analysis: Analysis) -> None:
        assert analysis.character(0).title == "Invoker / Ritualist"
        assert analysis.character(1).title == "Invader"

    def test_titel_faellt_auf_slotnummer_zurueck(self) -> None:
        assert models.Character(index=2).title == "Slot 3"

    def test_zaehler_aus_json(self, analysis: Analysis) -> None:
        counts = analysis.character(0).counts
        assert (counts.acquired, counts.missing, counts.total) == (3, 4, 7)
        assert counts.by_category["weapon"].acquired == 1
        assert counts.by_category["weapon"].missing == 1
        assert counts.fraction == pytest.approx(3 / 7)

    def test_welt_nach_slot(self, analysis: Analysis) -> None:
        character = analysis.character(0)
        campaign = character.world("campaign")

        assert campaign is not None
        assert campaign.difficulty == "Veteran"
        assert campaign.label == "Campaign"
        assert character.world("adventure").label == "Adventure"
        assert character.world("gibtsnicht") is None

    def test_zeitstempel_wird_geparst(self, analysis: Analysis) -> None:
        stamp = analysis.character(0).save_datetime
        assert stamp is not None
        assert (stamp.year, stamp.month, stamp.day) == (2026, 1, 10)

    def test_zustand_ohne_katalogeintrag_wird_uebersprungen(self) -> None:
        character = models.Character.from_json(
            {"index": 0, "item_states": [{"id": "gibt_es_nicht", "acquired": True}]},
            catalog={},
        )

        assert character.items == ()


class TestItem:
    def test_suche_findet_name_und_fundstelle(self, analysis: Analysis) -> None:
        character = analysis.character(0)
        ring = next(i for i in character.items if i.id == "Ring_RingOfTheAdmiral")

        assert ring.matches("admiral")
        assert ring.matches("ADMIRAL")
        assert ring.matches("reggie")
        assert ring.matches("")
        assert not ring.matches("yaesha")

    def test_subkategorie_geht_in_die_suche_ein(self, analysis: Analysis) -> None:
        weapon = next(i for i in analysis.character(0).items if i.id == "Weapon_AlphaOmega")

        assert weapon.matches("long gun")

    def test_erreichbarkeit(self, analysis: Analysis) -> None:
        items = {i.id: i for i in analysis.character(0).items}

        assert items["Ring_RingOfTheAdmiral"].state.obtainable_now is True
        assert items["Amulet_ButchersFetish"].state.obtainable_now is False
        # Reachable in the campaign alone is enough.
        assert items["Weapon_DecayedClaws"].state.obtainable_now is True
        # Unknown (null) must not count as reachable.
        assert items["Consumable_MysteryItem"].state.obtainable_now is False

    def test_herkunftstext(self, analysis: Analysis) -> None:
        catalog = analysis.catalog

        assert catalog["Ring_RingOfTheAdmiral"].source == "Vendor: Reggie"
        assert catalog["Weapon_DecayedClaws"].source == ""


class TestAggregation:
    def test_item_gilt_als_gefunden_wenn_ein_charakter_es_hat(self, analysis: Analysis) -> None:
        aggregate = {i.id: i for i in analysis.aggregate_items()}

        # Slot 0 has the ring, slot 1 doesn't.
        assert aggregate["Ring_ProbabilityCord"].acquired is True
        # The other way around: only slot 1 has the amulet.
        assert aggregate["Amulet_ButchersFetish"].acquired is True
        # Nobody has it.
        assert aggregate["Consumable_MysteryItem"].acquired is False

    def test_aggregat_enthaelt_jedes_item_genau_einmal(self, analysis: Analysis) -> None:
        items = analysis.aggregate_items()

        assert len(items) == 7
        assert len({i.id for i in items}) == 7

    def test_aggregierte_zaehler(self, analysis: Analysis) -> None:
        counts = analysis.aggregate_counts()

        # Slot 0 has 3, slot 1 has 2, none of them identical -> 5 found.
        assert counts.acquired == 5
        assert counts.missing == 2
        assert counts.total == 7

    def test_aggregat_ist_sortiert(self, analysis: Analysis) -> None:
        categories = [i.category for i in analysis.aggregate_items()]

        # weapon comes before ring in CATEGORY_ORDER, ring before amulet.
        assert categories.index("weapon") < categories.index("ring")
        assert categories.index("ring") < categories.index("amulet")


class TestSortierungUndGruppierung:
    def test_gruppiert_nach_kategorie_in_anzeigereihenfolge(self, analysis: Analysis) -> None:
        groups = models.group_by_category(analysis.character(0).items)

        assert [name for name, _ in groups] == [
            "weapon",
            "ring",
            "amulet",
            "trait",
            "consumable",
        ]

    def test_gruppen_sind_alphabetisch(self, analysis: Analysis) -> None:
        groups = dict(models.group_by_category(analysis.character(0).items))

        assert [i.name for i in groups["weapon"]] == ["Alpha / Omega", "Decayed Claws"]

    def test_unbekannte_kategorie_landet_hinten(self) -> None:
        key_known = models.category_sort_key("weapon")
        key_unknown = models.category_sort_key("dlc_neuheit")

        assert key_known < key_unknown

    def test_kategorielabel(self) -> None:
        assert models.category_label("ring") == "Rings"
        assert models.category_label("fragment") == "Relic Fragments"
        # Unknown falls back to something readable instead of failing.
        assert models.category_label("dlc_neuheit") == "Dlc_neuheit"


class TestWelten:
    def test_zonen_und_orte(self, analysis: Analysis) -> None:
        campaign = analysis.character(0).world("campaign")

        assert [z.name for z in campaign.zones] == ["Ward 13", "Yaesha"]
        yaesha = campaign.zones[1]
        assert yaesha.story == "Empress"
        assert yaesha.finished is False
        assert yaesha.locations[0].name == "The Far Woods"

    def test_marker_am_ort(self, analysis: Analysis) -> None:
        location = analysis.character(0).world("campaign").zones[1].locations[0]

        assert location.trait_book is True
        assert location.trait_book_looted is False
        assert location.simulacrum_looted is True
        assert location.bloodmoon is True
        assert location.vendors == ()
        assert location.connections == ("The Nameless Nest",)

    def test_offene_items_werden_gezaehlt(self, analysis: Analysis) -> None:
        campaign = analysis.character(0).world("campaign")
        yaesha = campaign.zones[1]

        # Probability Cord has been collected, Chakra hasn't.
        assert yaesha.locations[0].open_item_count() == 1
        assert yaesha.open_item_count() == 1
        assert campaign.zones[0].open_item_count() == 1

    def test_bereits_besessene_items_zaehlen_nicht_als_offen(self, analysis: Analysis) -> None:
        """An item owned from elsewhere is no reason to walk there.

        `is_looted` only covers this one roll - it says the drop is gone
        from here, not that the player has the item. Somebody who picked it
        up in an earlier roll still sees the drop lying around.
        """
        location = analysis.character(0).world("campaign").zones[1].locations[0]
        (still_open,) = location.open_items()

        assert location.open_item_count({still_open.id}) == 0
        assert still_open.is_looted is False

    def test_owned_ids_nennt_nur_vorhandenes(self, analysis: Analysis) -> None:
        character = analysis.character(0)
        owned = character.owned_ids

        assert owned == {item.id for item in character.items if item.acquired}
        assert all(not item.acquired for item in character.items if item.id not in owned)

    def test_loot_group_label(self, analysis: Analysis) -> None:
        campaign = analysis.character(0).world("campaign")

        assert campaign.zones[0].locations[0].loot_groups[0].label == "Reggie"
        # Without a name, the event reference takes over.
        assert campaign.zones[1].locations[0].loot_groups[0].label == "Quest_Yaesha_Empress"


class TestFormat:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (None, "-"),
            (0, "-"),
            (90, "1 min"),
            (3600, "1 h 00 min"),
            (57420, "15 h 57 min"),
        ],
    )
    def test_spielzeit(self, seconds: float | None, expected: str) -> None:
        assert models.format_playtime(seconds) == expected
