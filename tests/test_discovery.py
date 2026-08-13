"""Tests der Save-Discovery gegen nachgebaute Verzeichnisbaeume."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from r2wa import discovery  # noqa: E402
from r2wa.discovery import GAME_APP_ID, SAVE_SUBPATH  # noqa: E402


def make_save_dir(base: Path, slots: int = 2, profile: bool = True) -> Path:
    """Lege ein Savegame-Verzeichnis mit *slots* Charakteren an."""
    base.mkdir(parents=True, exist_ok=True)
    if profile:
        (base / "profile.sav").write_bytes(b"\x00")
    for index in range(slots):
        (base / f"save_{index}.sav").write_bytes(b"\x00")
    return base


def make_proton_tree(root: Path, steam_id: str = "76561198000000001", slots: int = 2) -> Path:
    """Baue einen vollstaendigen Steam-/Proton-Baum unterhalb von *root*."""
    (root / "steamapps").mkdir(parents=True, exist_ok=True)
    save_dir = root.joinpath("steamapps", "compatdata", GAME_APP_ID, *SAVE_SUBPATH, steam_id)
    return make_save_dir(save_dir, slots=slots)


class TestValidate:
    def test_akzeptiert_vollstaendiges_verzeichnis(self, tmp_path: Path) -> None:
        save_dir = make_save_dir(tmp_path / "76561198000000001", slots=3)

        location = discovery.validate(save_dir)

        assert location is not None
        assert location.steam_id == "76561198000000001"
        assert location.slot_count == 3
        assert location.profile.name == "profile.sav"

    def test_sortiert_slots_numerisch(self, tmp_path: Path) -> None:
        save_dir = make_save_dir(tmp_path / "acct", slots=0)
        for index in (10, 2, 0):
            (save_dir / f"save_{index}.sav").write_bytes(b"\x00")

        location = discovery.validate(save_dir)

        assert location is not None
        assert [p.name for p in location.slots] == ["save_0.sav", "save_2.sav", "save_10.sav"]

    def test_verwirft_verzeichnis_ohne_profil(self, tmp_path: Path) -> None:
        save_dir = make_save_dir(tmp_path / "acct", slots=2, profile=False)

        assert discovery.validate(save_dir) is None

    def test_verwirft_verzeichnis_ohne_slots(self, tmp_path: Path) -> None:
        save_dir = make_save_dir(tmp_path / "acct", slots=0)

        assert discovery.validate(save_dir) is None

    def test_verwirft_nicht_existierenden_pfad(self, tmp_path: Path) -> None:
        assert discovery.validate(tmp_path / "gibt-es-nicht") is None

    def test_ignoriert_backup_dateien(self, tmp_path: Path) -> None:
        save_dir = make_save_dir(tmp_path / "acct", slots=1)
        (save_dir / "save_1.bak").write_bytes(b"\x00")
        (save_dir / "profile.bak").write_bytes(b"\x00")

        location = discovery.validate(save_dir)

        assert location is not None
        assert location.slot_count == 1


class TestSteamRoots:
    def test_findet_native_installation(self, tmp_path: Path) -> None:
        (tmp_path / ".steam" / "steam" / "steamapps").mkdir(parents=True)

        roots = discovery.steam_roots(tmp_path)

        assert [r.name for r in roots] == ["steam"]

    def test_findet_flatpak_installation(self, tmp_path: Path) -> None:
        flatpak = tmp_path / ".var/app/com.valvesoftware.Steam/data/Steam"
        (flatpak / "steamapps").mkdir(parents=True)

        roots = discovery.steam_roots(tmp_path)

        assert roots == [flatpak]

    def test_ignoriert_wurzel_ohne_steamapps(self, tmp_path: Path) -> None:
        (tmp_path / ".local" / "share" / "Steam").mkdir(parents=True)

        assert discovery.steam_roots(tmp_path) == []

    def test_ohne_steam_leer(self, tmp_path: Path) -> None:
        assert discovery.steam_roots(tmp_path) == []


class TestLibraryFolders:
    def test_liest_zusaetzliche_bibliotheken(self, tmp_path: Path) -> None:
        root = tmp_path / "Steam"
        (root / "steamapps").mkdir(parents=True)
        extern = tmp_path / "mnt" / "games" / "SteamLibrary"
        (extern / "steamapps").mkdir(parents=True)
        (root / "steamapps" / "libraryfolders.vdf").write_text(
            '"libraryfolders"\n'
            "{\n"
            '\t"0"\n'
            "\t{\n"
            f'\t\t"path"\t\t"{root.as_posix()}"\n'
            "\t}\n"
            '\t"1"\n'
            "\t{\n"
            f'\t\t"path"\t\t"{extern.as_posix()}"\n'
            "\t}\n"
            "}\n",
            encoding="utf-8",
        )

        folders = discovery.library_folders(root)

        assert extern.resolve() in [f.resolve() for f in folders]

    def test_ignoriert_eingetragene_aber_fehlende_bibliothek(self, tmp_path: Path) -> None:
        root = tmp_path / "Steam"
        (root / "steamapps").mkdir(parents=True)
        (root / "steamapps" / "libraryfolders.vdf").write_text(
            '"libraryfolders" { "0" { "path" "/gibt/es/nicht" } }', encoding="utf-8"
        )

        assert discovery.library_folders(root) == []

    def test_fehlende_vdf_ist_kein_fehler(self, tmp_path: Path) -> None:
        root = tmp_path / "Steam"
        (root / "steamapps").mkdir(parents=True)

        assert discovery.library_folders(root) == []


class TestDiscover:
    def test_findet_save_im_proton_prefix(self, tmp_path: Path) -> None:
        save_dir = make_proton_tree(tmp_path / ".steam" / "steam")

        locations = discovery.discover(home=tmp_path)

        assert len(locations) == 1
        assert locations[0].path.resolve() == save_dir.resolve()
        assert locations[0].source == "proton"

    def test_findet_save_in_zweiter_bibliothek(self, tmp_path: Path) -> None:
        root = tmp_path / ".steam" / "steam"
        (root / "steamapps").mkdir(parents=True)
        extern = tmp_path / "mnt" / "SteamLibrary"
        save_dir = make_proton_tree(extern)
        (root / "steamapps" / "libraryfolders.vdf").write_text(
            f'"libraryfolders" {{ "0" {{ "path" "{extern.as_posix()}" }} }}', encoding="utf-8"
        )

        locations = discovery.discover(home=tmp_path)

        assert [loc.path.resolve() for loc in locations] == [save_dir.resolve()]

    def test_findet_mehrere_accounts(self, tmp_path: Path) -> None:
        root = tmp_path / ".steam" / "steam"
        make_proton_tree(root, steam_id="76561198000000001")
        make_proton_tree(root, steam_id="76561198000000002")

        locations = discovery.discover(home=tmp_path)

        assert len(locations) == 2
        assert {loc.steam_id for loc in locations} == {
            "76561198000000001",
            "76561198000000002",
        }

    def test_sortiert_nach_letzter_aenderung(self, tmp_path: Path) -> None:
        root = tmp_path / ".steam" / "steam"
        alt = make_proton_tree(root, steam_id="76561198000000001")
        neu = make_proton_tree(root, steam_id="76561198000000002")
        import os

        os.utime(alt / "profile.sav", (1_000_000, 1_000_000))
        os.utime(neu / "profile.sav", (2_000_000, 2_000_000))

        locations = discovery.discover(home=tmp_path)

        assert locations[0].steam_id == "76561198000000002"

    def test_manueller_pfad_steht_vorne(self, tmp_path: Path) -> None:
        make_proton_tree(tmp_path / ".steam" / "steam")
        manual = make_save_dir(tmp_path / "woanders" / "76561198000000009")

        locations = discovery.discover(home=tmp_path, extra_paths=(manual,))

        assert locations[0].path.resolve() == manual.resolve()
        assert locations[0].source == "manual"
        assert len(locations) == 2

    def test_manueller_pfad_wird_nicht_doppelt_gelistet(self, tmp_path: Path) -> None:
        save_dir = make_proton_tree(tmp_path / ".steam" / "steam")

        locations = discovery.discover(home=tmp_path, extra_paths=(save_dir,))

        assert len(locations) == 1
        assert locations[0].source == "manual"

    def test_ungueltiger_manueller_pfad_wird_verworfen(self, tmp_path: Path) -> None:
        locations = discovery.discover(home=tmp_path, extra_paths=(tmp_path / "nix",))

        assert locations == []

    def test_ohne_treffer_leer(self, tmp_path: Path) -> None:
        assert discovery.discover(home=tmp_path) == []

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows-Zweig liefert Zusatztreffer")
    def test_leeres_home_findet_nichts(self, tmp_path: Path) -> None:
        (tmp_path / ".steam" / "steam" / "steamapps").mkdir(parents=True)

        assert discovery.discover(home=tmp_path) == []

    def test_ohne_bestimmbares_home_nur_manuelle_pfade(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ohne Home entfaellt die automatische Suche, uebergebene Pfade
        # muessen aber weiterhin gefunden werden.
        manual = make_save_dir(tmp_path / "76561198000000009")
        monkeypatch.setattr(discovery, "user_home", lambda: None)

        locations = discovery.discover(extra_paths=(manual,))

        assert [loc.path.resolve() for loc in locations] == [manual.resolve()]

    def test_ohne_home_und_ohne_pfade_leer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(discovery, "user_home", lambda: None)

        assert discovery.discover() == []
