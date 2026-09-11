"""One-time download of all item icons from the Remnant wiki.

The image paths follow a fixed scheme of the wiki.gg network:
``https://remnant2.wiki.gg/images/thumb/<Slug>.png/<Width>px-<Slug>.png``.
Cloudflare rejects requests without browser-typical headers, hence the
explicit user agent. Files that already exist are skipped, so a run can
safely be repeated to fill in gaps.

    python -m r2wa.icon_fetch
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .iteminfo import (
    DEFAULT_ITEMINFO_CSV,
    DEFAULT_PORTRAITS_CSV,
    DEFAULT_TOOLKIT_CSV,
    load_portraits,
    load_rows,
    load_toolkit_rows,
)
from .paths import icons_dir

#: Width of the downloaded thumbnails in pixels. The views draw icons at
#: 32 logical pixels, so this leaves room for a HiDPI display at scale 2 to
#: still have pixels to spare. Raising it does not re-fetch what is already
#: cached - delete the icons directory to pick up a new width.
ICON_WIDTH = 128

#: Target directory; in the working directory it sits next to the parser
#: binary, because both are regenerable, unversioned build artifacts. An
#: installed copy has them shipped along instead (see :mod:`r2wa.paths`).
DEFAULT_ICONS_DIR = icons_dir()

#: Portraits are drawn at twice the size of an item icon (see
#: ``PORTRAIT_SIZE`` in the worlds view), so they need their own width to
#: keep the same headroom on a HiDPI display.
PORTRAIT_WIDTH = 256

#: The toolkit's own image CDN. Only used for the handful of items the wiki
#: has no usable image for - their CDN is paid for by a community project,
#: so there is no reason to pull the other ~800 icons from it as well.
TOOLKIT_CDN = "https://d2sqltdcj8czo5.cloudfront.net/remnant2"

_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

#: Pause between requests, so as not to overload the wiki server.
_DELAY_SECONDS = 0.1


def icon_url(slug: str, width: int = ICON_WIDTH) -> str:
    return f"https://remnant2.wiki.gg/images/thumb/{slug}.png/{width}px-{slug}.png"


def icon_path(slug: str, icons_dir: Path = DEFAULT_ICONS_DIR) -> Path:
    return icons_dir / f"{slug}.png"


def portrait_url(image_file: str, width: int = PORTRAIT_WIDTH) -> str:
    """Thumbnail of a wiki file that is already a complete filename.

    Unlike an item icon, the portrait of a vendor or boss is not named after
    its page (Reggie's is ``Reginald_Reggie_Malone.jpg``) and is a JPEG, so
    the name including its extension comes from ``data/portraits.csv``
    instead of being derived.
    """
    return f"https://remnant2.wiki.gg/images/thumb/{image_file}/{width}px-{image_file}"


def portrait_path(image_file: str, icons_dir: Path = DEFAULT_ICONS_DIR) -> Path:
    """Own subdirectory, for the same reason as the toolkit's."""
    return icons_dir / "portraits" / image_file


def toolkit_icon_url(image_path: str) -> str:
    return f"{TOOLKIT_CDN}{image_path if image_path.startswith('/') else '/' + image_path}"


def toolkit_icon_path(image_path: str, icons_dir: Path = DEFAULT_ICONS_DIR) -> Path:
    """Own subdirectory, so a CDN filename can never collide with a wiki slug."""
    return icons_dir / "toolkit" / Path(image_path).name


def _candidate_slugs(slug: str) -> list[str]:
    """Alternative filenames the image might actually be stored under.

    The page name from the CSV export doesn't always match the image's
    filename: "of"/"the" are often capitalized in the filename even when
    the page itself is linked lowercase, and a disambiguation suffix in
    parentheses (e.g. "Bandit_(Mutator)") usually belongs only to the page
    title, not the image name.
    """
    candidates = [slug]

    title_cased = "_".join(
        part[:1].upper() + part[1:] if part[:1].islower() else part for part in slug.split("_")
    )
    if title_cased != slug:
        candidates.append(title_cased)

    if "_(" in slug:
        without_suffix = slug.split("_(", 1)[0]
        if without_suffix:
            candidates.append(without_suffix)

    return candidates


def _download(url: str, target: Path) -> tuple[bool, str | None]:
    """Fetch one image. Returns (success, error message for anything but a 404)."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    error: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            target.write_bytes(response.read())
        return True, None
    except urllib.error.HTTPError as exc:
        error = None if exc.code == 404 else f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        error = str(exc.reason)
    finally:
        time.sleep(_DELAY_SECONDS)
    return False, error


def fetch_all(
    icons_dir: Path = DEFAULT_ICONS_DIR,
    csv_path: Path = DEFAULT_ITEMINFO_CSV,
) -> tuple[int, int, int]:
    """Download every icon the CSV export has a wiki link for.

    Returns (downloaded, already present, failed).
    """
    icons_dir.mkdir(parents=True, exist_ok=True)

    slugs = sorted({row.wiki_slug for row in load_rows(csv_path) if row.wiki_slug})
    print(f"{len(slugs)} icons found in the export.")

    downloaded = skipped = failed = 0
    for index, slug in enumerate(slugs, start=1):
        target = icon_path(slug, icons_dir)
        if target.is_file():
            skipped += 1
            continue

        success = False
        last_error: str | None = None
        for candidate in _candidate_slugs(slug):
            success, last_error = _download(icon_url(candidate), target)
            if success:
                break

        if success:
            downloaded += 1
        else:
            failed += 1
            if last_error:
                print(f"  [{index}/{len(slugs)}] {slug}: {last_error}", file=sys.stderr)

        if index % 50 == 0:
            print(f"  [{index}/{len(slugs)}] {downloaded} downloaded, {failed} failed")

    return downloaded, skipped, failed


def fetch_toolkit_icons(
    icons_dir: Path = DEFAULT_ICONS_DIR,
    csv_path: Path = DEFAULT_ITEMINFO_CSV,
    toolkit_path: Path = DEFAULT_TOOLKIT_CSV,
) -> tuple[int, int, int]:
    """Fill the gaps the wiki leaves, from the toolkit's CDN.

    Deliberately only the gaps - anything the wiki already covers is left
    alone; see the note on :data:`TOOLKIT_CDN`. Run this after
    :func:`fetch_all`, which is what decides what is still missing.

    Returns (downloaded, already present, failed).
    """
    entries = [e for e in load_toolkit_rows(toolkit_path) if e.image_path]
    if not entries:
        return 0, 0, 0

    by_toolkit_id = {row.toolkit_id: row for row in load_rows(csv_path) if row.toolkit_id}

    gaps = []
    for entry in entries:
        info = by_toolkit_id.get(entry.toolkit_id)
        covered = (
            info is not None and info.wiki_slug and icon_path(info.wiki_slug, icons_dir).is_file()
        )
        if not covered:
            gaps.append(entry)

    if not gaps:
        return 0, 0, 0

    print(f"\n{len(gaps)} items without a wiki icon - trying the toolkit's CDN.")
    (icons_dir / "toolkit").mkdir(parents=True, exist_ok=True)

    downloaded = skipped = failed = 0
    for entry in gaps:
        target = toolkit_icon_path(entry.image_path, icons_dir)
        if target.is_file():
            skipped += 1
            continue

        success, error = _download(toolkit_icon_url(entry.image_path), target)
        if success:
            downloaded += 1
        else:
            failed += 1
            if error:
                print(f"  {entry.save_file_slug}: {error}", file=sys.stderr)

    return downloaded, skipped, failed


def fetch_portraits(
    icons_dir: Path = DEFAULT_ICONS_DIR,
    portraits_path: Path = DEFAULT_PORTRAITS_CSV,
) -> tuple[int, int, int]:
    """Download the vendor and boss portraits listed in ``data/portraits.csv``.

    Returns (downloaded, already present, failed).
    """
    portraits = load_portraits(portraits_path)
    if not portraits:
        return 0, 0, 0

    (icons_dir / "portraits").mkdir(parents=True, exist_ok=True)

    downloaded = skipped = failed = 0
    # Two names can share one file (the wiki redirects "Cinderclad Monolith"
    # to "Cinderclad Forge"), so fetch by file rather than by name.
    for image_file in sorted(
        {entry.image_file for entry in portraits.values() if entry.image_file}
    ):
        target = portrait_path(image_file, icons_dir)
        if target.is_file():
            skipped += 1
            continue

        success, error = _download(portrait_url(image_file), target)
        if success:
            downloaded += 1
        else:
            failed += 1
            print(f"  {image_file}: {error or 'not found'}", file=sys.stderr)

    return downloaded, skipped, failed


def main() -> int:
    downloaded, skipped, failed = fetch_all()
    print(f"\nDone: {downloaded} downloaded, {skipped} already present, {failed} not found/failed.")

    downloaded, skipped, failed = fetch_toolkit_icons()
    if downloaded or skipped or failed:
        print(f"Toolkit: {downloaded} downloaded, {skipped} already present, {failed} failed.")

    downloaded, skipped, failed = fetch_portraits()
    if downloaded or skipped or failed:
        print(f"Portraits: {downloaded} downloaded, {skipped} already present, {failed} failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
