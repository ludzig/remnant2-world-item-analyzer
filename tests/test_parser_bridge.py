"""Tests of the bridge to the C# parser.

The error paths matter more here than the happy path: the UI must be able
to display every kind of parser failure instead of crashing.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from r2wa import parser_bridge  # noqa: E402
from r2wa.parser_bridge import ParserError, ParserNotFoundError  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "analysis_minimal.json"


class TestParseOutput:
    def test_liest_gueltige_ausgabe(self) -> None:
        analysis = parser_bridge.parse_output(FIXTURE.read_text(encoding="utf-8"))

        assert analysis.schema_version == 1
        assert len(analysis.characters) == 2

    def test_ignoriert_umgebende_leerzeichen(self) -> None:
        payload = "\n  " + FIXTURE.read_text(encoding="utf-8") + "  \n"

        assert parser_bridge.parse_output(payload).schema_version == 1

    def test_leere_ausgabe(self) -> None:
        with pytest.raises(ParserError) as excinfo:
            parser_bridge.parse_output("   \n")

        assert excinfo.value.kind == "empty_output"

    def test_kaputtes_json(self) -> None:
        with pytest.raises(ParserError) as excinfo:
            parser_bridge.parse_output("{ das ist kein json")

        assert excinfo.value.kind == "invalid_json"

    def test_json_ist_kein_objekt(self) -> None:
        with pytest.raises(ParserError) as excinfo:
            parser_bridge.parse_output("[1, 2, 3]")

        assert excinfo.value.kind == "invalid_json"

    def test_fehlerobjekt_des_parsers(self) -> None:
        payload = json.dumps(
            {
                "schema_version": 1,
                "error": {
                    "kind": "save_dir_not_found",
                    "message": "Directory not found: /gone",
                    "detail": "Stacktrace",
                },
            }
        )

        with pytest.raises(ParserError) as excinfo:
            parser_bridge.parse_output(payload)

        assert excinfo.value.kind == "save_dir_not_found"
        assert "Directory not found" in str(excinfo.value)
        assert excinfo.value.detail == "Stacktrace"

    def test_falsche_schemaversion(self) -> None:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data["schema_version"] = 99

        with pytest.raises(ParserError) as excinfo:
            parser_bridge.parse_output(json.dumps(data))

        assert excinfo.value.kind == "schema_mismatch"
        assert "99" in str(excinfo.value)

    def test_fehlende_schemaversion(self) -> None:
        with pytest.raises(ParserError) as excinfo:
            parser_bridge.parse_output('{"characters": []}')

        assert excinfo.value.kind == "schema_mismatch"


class TestFindParser:
    def test_expliziter_pfad_gewinnt(self, tmp_path: Path) -> None:
        binary = tmp_path / "r2wa-parser"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")

        assert parser_bridge.find_parser(binary) == binary

    def test_umgebungsvariable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        binary = tmp_path / "r2wa-parser"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setenv("R2WA_PARSER", str(binary))

        assert parser_bridge.find_parser() == binary

    def test_fehlermeldung_nennt_gesuchte_pfade(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without redirecting the repo root, an actually built binary in the
        # working directory would be found and the test would test nothing.
        monkeypatch.delenv("R2WA_PARSER", raising=False)
        monkeypatch.setattr(parser_bridge, "REPO_ROOT", tmp_path / "empty-repo")
        monkeypatch.setattr(parser_bridge.shutil, "which", lambda _: None)

        with pytest.raises(ParserNotFoundError) as excinfo:
            parser_bridge.find_parser(tmp_path / "does-not-exist")

        assert excinfo.value.kind == "parser_not_found"
        assert "does-not-exist" in str(excinfo.value)

    def test_findet_binary_im_build_verzeichnis(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("R2WA_PARSER", raising=False)
        monkeypatch.setattr(parser_bridge, "REPO_ROOT", tmp_path)
        build_dir = tmp_path / "build" / "parser"
        build_dir.mkdir(parents=True)
        binary = build_dir / parser_bridge.PARSER_NAME
        binary.write_text("#!/bin/sh\n", encoding="utf-8")

        assert parser_bridge.find_parser() == binary


class TestBuildCommand:
    def test_kommandozeile(self, tmp_path: Path) -> None:
        command = parser_bridge.build_command("/saves/123", tmp_path / "r2wa-parser")

        assert command[1:] == ["analyze", "--save-dir", "/saves/123"]


@pytest.fixture(scope="module")
def real_analysis():
    """Analysis of a real save game - only if one is configured."""
    save_dir = os.environ.get("R2WA_TEST_SAVE_DIR")
    if not save_dir:
        pytest.skip("Set R2WA_TEST_SAVE_DIR to a real save game directory")
    return parser_bridge.analyze(save_dir)


class TestGegenEchtesSavegame:
    """Integration test against a real save game and the built binary.

    Only checks invariants that hold regardless of the specific save game -
    that way the test stays valid even with a different save.
    """

    def test_katalog_ist_vollstaendig(self, real_analysis) -> None:
        # The catalog comes from db.json and is independent of the character.
        assert len(real_analysis.catalog) > 800
        assert real_analysis.characters

    def test_jeder_charakter_kennt_jedes_item(self, real_analysis) -> None:
        for character in real_analysis.characters:
            assert len(character.items) == len(real_analysis.catalog)

    def test_zaehler_sind_in_sich_schluessig(self, real_analysis) -> None:
        for character in real_analysis.characters:
            counts = character.counts
            assert counts.acquired + counts.missing == counts.total
            assert counts.total == len(real_analysis.catalog)
            assert counts.acquired == sum(1 for i in character.items if i.acquired)

    def test_zaehler_je_kategorie_summieren_sich(self, real_analysis) -> None:
        for character in real_analysis.characters:
            counts = character.counts
            assert sum(c.total for c in counts.by_category.values()) == counts.total
            assert sum(c.acquired for c in counts.by_category.values()) == counts.acquired

    def test_aggregat_ist_mindestens_so_gut_wie_jeder_einzelne(self, real_analysis) -> None:
        aggregate = real_analysis.aggregate_counts()
        best = max(c.counts.acquired for c in real_analysis.characters)

        assert aggregate.acquired >= best
        assert aggregate.total == len(real_analysis.catalog)

    def test_erworbene_items_gelten_nicht_als_erreichbarkeitsfrage(self, real_analysis) -> None:
        # Reachability is not checked for items already found; it must
        # therefore stay unknown.
        for character in real_analysis.characters:
            for item in character.items:
                if item.acquired:
                    assert item.state.obtainable_in_campaign is None
                    assert item.state.obtainable_in_adventure is None
