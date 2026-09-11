"""Where the application's data files live.

Run from the working directory they sit next to the sources, in ``data/``
and ``build/icons/``. Installed they sit under a prefix - ``/app/share/r2wa``
in a Flatpak - and the package itself is somewhere in ``site-packages``,
from where no relative path leads back to them.

Both layouts are found without configuration: the candidates are tried in
order and the first one that exists wins. ``R2WA_DATA_DIR`` and
``R2WA_ICONS_DIR`` override everything, for tests and for layouts nobody
has thought of yet.

Nothing here raises when a directory is missing. A missing data directory
costs icons, links and display names, but the application still starts and
still analyzes save games - that is worth more than a clean error.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Directory of the installed package, i.e. ``.../r2wa``.
_PACKAGE_DIR = Path(__file__).resolve().parent

#: Root of the working directory, two levels up from ``src/r2wa/``.
_REPO_ROOT = _PACKAGE_DIR.parents[1]

#: Subdirectory under a prefix's ``share``. Matches the app id's last part
#: in lowercase, as is customary.
_SHARE_NAME = "r2wa"


def _first_existing(candidates: list[Path], fallback: Path) -> Path:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return fallback


def _prefixes() -> list[Path]:
    """Plausible install prefixes, most specific first.

    ``/app`` is where a Flatpak puts everything the application brings
    along; ``sys.prefix`` covers a virtualenv or a system-wide install.
    """
    return [Path("/app"), Path(sys.prefix), Path.home() / ".local"]


def data_dir() -> Path:
    """The directory with the shipped CSV tables and hand-picked icons."""
    override = os.environ.get("R2WA_DATA_DIR")
    if override:
        return Path(override)

    repo = _REPO_ROOT / "data"
    return _first_existing(
        [repo, *(prefix / "share" / _SHARE_NAME / "data" for prefix in _prefixes())],
        repo,
    )


def icons_dir() -> Path:
    """The directory with the downloaded item icons.

    In the working directory this is a build artifact under ``build/``; in
    an installed copy the icons are shipped along, because there is no
    writable place to download them to and no network at hand.
    """
    override = os.environ.get("R2WA_ICONS_DIR")
    if override:
        return Path(override)

    repo = _REPO_ROOT / "build" / "icons"
    return _first_existing(
        [repo, *(prefix / "share" / _SHARE_NAME / "icons" for prefix in _prefixes())],
        repo,
    )
