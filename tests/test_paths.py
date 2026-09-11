"""Tests of the data directory lookup - source tree versus installed copy."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from r2wa import paths  # noqa: E402


class TestDataDir:
    def test_umgebungsvariable_schlaegt_alles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("R2WA_DATA_DIR", str(tmp_path / "woanders"))

        # Deliberately not required to exist: whoever sets it means it.
        assert paths.data_dir() == tmp_path / "woanders"

    def test_arbeitsverzeichnis_wird_gefunden(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("R2WA_DATA_DIR", raising=False)
        repo = tmp_path / "repo"
        (repo / "data").mkdir(parents=True)
        monkeypatch.setattr(paths, "_REPO_ROOT", repo)

        assert paths.data_dir() == repo / "data"

    def test_installierte_kopie_wird_gefunden(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No source tree next to the package - the installed case.
        monkeypatch.delenv("R2WA_DATA_DIR", raising=False)
        monkeypatch.setattr(paths, "_REPO_ROOT", tmp_path / "gibt-es-nicht")
        prefix = tmp_path / "app"
        (prefix / "share" / "r2wa" / "data").mkdir(parents=True)
        monkeypatch.setattr(paths, "_prefixes", lambda: [prefix])

        assert paths.data_dir() == prefix / "share" / "r2wa" / "data"

    def test_ohne_jeden_fund_bleibt_der_quellbaum_pfad(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Nothing exists anywhere. The caller checks the file itself and
        # simply finds nothing - the application must not fail to start.
        monkeypatch.delenv("R2WA_DATA_DIR", raising=False)
        monkeypatch.setattr(paths, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(paths, "_prefixes", lambda: [tmp_path / "leer"])

        assert paths.data_dir() == tmp_path / "data"


class TestIconsDir:
    def test_umgebungsvariable_schlaegt_alles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("R2WA_ICONS_DIR", str(tmp_path / "bilder"))

        assert paths.icons_dir() == tmp_path / "bilder"

    def test_im_arbeitsverzeichnis_unter_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("R2WA_ICONS_DIR", raising=False)
        repo = tmp_path / "repo"
        (repo / "build" / "icons").mkdir(parents=True)
        monkeypatch.setattr(paths, "_REPO_ROOT", repo)

        assert paths.icons_dir() == repo / "build" / "icons"

    def test_installiert_neben_den_daten(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("R2WA_ICONS_DIR", raising=False)
        monkeypatch.setattr(paths, "_REPO_ROOT", tmp_path / "gibt-es-nicht")
        prefix = tmp_path / "app"
        (prefix / "share" / "r2wa" / "icons").mkdir(parents=True)
        monkeypatch.setattr(paths, "_prefixes", lambda: [prefix])

        assert paths.icons_dir() == prefix / "share" / "r2wa" / "icons"
