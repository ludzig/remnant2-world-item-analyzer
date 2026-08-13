"""Tests der dateibasierten Einstellungen."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from r2wa.config import Settings, config_dir, user_home  # noqa: E402


class TestSettings:
    def test_speichern_und_lesen(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        Settings(save_dir="/saves/123", character_index=2).save(target)

        loaded = Settings.load(target)

        assert loaded.save_dir == "/saves/123"
        assert loaded.character_index == 2

    def test_legt_verzeichnis_an(self, tmp_path: Path) -> None:
        target = tmp_path / "tief" / "verschachtelt" / "settings.json"
        Settings(save_dir="/x").save(target)

        assert target.is_file()

    def test_fehlende_datei_ergibt_leere_einstellungen(self, tmp_path: Path) -> None:
        loaded = Settings.load(tmp_path / "gibt-es-nicht.json")

        assert loaded.save_dir is None
        assert loaded.character_index is None

    def test_kaputte_datei_wird_ignoriert(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text("{ kein json", encoding="utf-8")

        assert Settings.load(target).save_dir is None

    def test_unerwarteter_inhalt_wird_ignoriert(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text('["eine", "liste"]', encoding="utf-8")

        assert Settings.load(target).save_dir is None

    def test_falsche_typen_werden_verworfen(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text('{"save_dir": 42, "character_index": "zwei"}', encoding="utf-8")

        loaded = Settings.load(target)

        assert loaded.save_dir is None
        assert loaded.character_index is None

    def test_hinterlaesst_keine_temporaerdatei(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        Settings(save_dir="/x").save(target)

        assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]

    def test_nicht_schreibbares_ziel_wirft_nicht(self, tmp_path: Path) -> None:
        # Ein Verzeichnis anstelle der Datei laesst das Schreiben scheitern;
        # die Anwendung darf daran nicht sterben.
        target = tmp_path / "settings.json"
        target.mkdir()

        Settings(save_dir="/x").save(target)


class TestConfigDir:
    def test_folgt_xdg_config_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        assert config_dir() == tmp_path / "r2wa"

    def test_faellt_auf_punkt_config_zurueck(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        assert config_dir() == tmp_path / ".config" / "r2wa"

    def test_ohne_home_kein_verzeichnis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ohne bestimmbares Home gibt es keinen Speicherort - das darf keine
        # Ausnahme werfen, sondern muss None liefern.
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("HOME", raising=False)
        monkeypatch.delenv("USERPROFILE", raising=False)
        monkeypatch.setattr(Path, "home", _raise_runtime_error)

        assert config_dir() is None


class TestUserHome:
    def test_bevorzugt_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))

        assert user_home() == tmp_path

    def test_faellt_auf_userprofile_zurueck(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HOME", raising=False)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        assert user_home() == tmp_path

    def test_ohne_alles_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOME", raising=False)
        monkeypatch.delenv("USERPROFILE", raising=False)
        monkeypatch.setattr(Path, "home", _raise_runtime_error)

        assert user_home() is None


class TestEinstellungenOhneHome:
    """Ohne Speicherort muss die Anwendung trotzdem starten koennen."""

    def test_laden_liefert_voreinstellung(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _remove_home(monkeypatch)

        assert Settings.load().save_dir is None

    def test_speichern_wirft_nicht(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _remove_home(monkeypatch)

        Settings(save_dir="/irgendwo").save()


def _raise_runtime_error(*_args, **_kwargs):
    raise RuntimeError("Could not determine home directory.")


def _remove_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.setattr(Path, "home", _raise_runtime_error)
