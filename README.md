# r2wa — Remnant 2 World & Item Analyzer

A GNOME application that **only reads** Remnant 2 save games and shows which
items a character has found and which are still missing — plus the
currently rolled worlds with their zones, locations, and loot spots.

No backups, no saving, no touching the save game.

![The worlds view: characters on the left, then the zones of the rolled
campaign, the locations of the selected zone, and its loot - each item with
its icon, a note on where to find it, and a link to the
wiki](docs/screenshot.png)

## Architecture

The save game parser only exists as a C# library. Instead of reimplementing
it, it's embedded as a lightweight subprocess:

```
┌──────────────────────────────────────────┐
│ r2wa  —  Python + GTK4 / libadwaita      │
│   ├ discovery.py    find the Proton prefix │
│   ├ parser_bridge   subprocess + JSON    │
│   ├ models.py       plain dataclasses    │
│   └ views/          items · worlds       │
└─────────────────┬────────────────────────┘
                  │ JSON on stdout (schema v1)
┌─────────────────▼────────────────────────┐
│ r2wa-parser  —  C# .NET 10               │
│   └ lib.remnant2.analyzer (MIT)          │
│       └ db.json — all 849 items          │
└──────────────────────────────────────────┘
```

The parser does **not** emit the library's data model raw, but its own,
versioned schema. If something changes upstream, the fix stays confined to
`parser/DatasetMapper.cs`.

### Where an item comes from

The catalog carries a note for 839 of the 849 items saying where and how to
get them ("Found in an outdoor location on Yaesha. There will be a big Doe
statue. Wear the Red Doe Sigil amulet to open"). Both views show it under
the item name, over at most two lines so the rows stay an even height, with
the full text on the row's tooltip.

A location's loot names only the item, so the worlds view joins it against
the catalog by id — which is why `WorldsView.set_analysis()` takes the whole
analysis and not just the character.

## Requirements

- GNOME 46 or newer (GTK 4.12+, libadwaita 1.5+)
- Python 3.11+ with PyGObject — `python3-gobject` on Fedora,
  `python3-gi python3-gi-cairo gir1.2-adw-1` on Debian/Ubuntu
- .NET SDK 10 to build the parser
- [just](https://github.com/casey/just) for the build tasks (optional)

## First start on the Linux machine

```bash
just build-parser && just smoke && just run
```

These three steps build the parser for `linux-x64`, check the UI (18
self-tests covering filters, search, the tree, and character switching),
and then start the application. If `just smoke` passes, the GTK layer
works; if `just run` still fails afterward, the problem is in the save
game search.

Without `just`:

```bash
dotnet publish parser/R2waParser.csproj -c Release -r linux-x64 \
    --self-contained -p:PublishSingleFile=true -o build/parser
PYTHONPATH=src python3 tests/smoke_ui.py
PYTHONPATH=src python3 -m r2wa.main
```

### Transferring the folder from Windows

The working directory can be copied directly, all files use LF line
endings. Don't bring these along — or run `just clean` first:

| Directory | why |
|---|---|
| `build/`, `parser/bin/`, `parser/obj/` | contain the Windows binary, gets rebuilt |
| `.venv/` | Windows interpreter, useless on Linux |
| `__pycache__/` | platform-dependent |

On GNOME, PyGObject comes from the distribution and **does not** belong in
a venv — the application runs directly against the system Python.

The save game is found automatically. A different path can be passed as an
argument or chosen in the window via *Open Folder…*:

```bash
PYTHONPATH=src python3 -m r2wa.main ~/path/to/savegame
```

### Where the save games live

On Linux, inside the game's Proton prefix (app ID 1282100):

```
~/.steam/steam/steamapps/compatdata/1282100/pfx/drive_c/users/steamuser/
    Saved Games/Remnant2/Steam/<steam-id>/
```

`discovery.py` also searches `~/.local/share/Steam`, the Flatpak
installation of Steam, and every library listed in `libraryfolders.vdf`.
To see what was found:

```bash
just discover
```

## Development

Developed on Windows, built and tested on a Linux machine:

```bash
export R2WA_REMOTE=user@host:~/dev/r2wa
just sync
```

The C# part also builds on Windows and cross-publishes for `linux-x64`;
the GTK UI needs Linux.

```bash
just test     # pytest
just lint     # ruff
just check    # both
just smoke    # actually build and check the UI
```

`just smoke` builds the views, hangs them in a window, runs the main loop,
and checks filters, search, expanding, and character switching. That needs
PyGObject and a display, so it doesn't run under `just test`. With `--show`
the window stays open to look at; with `--save-dir` it runs against a real
save game instead of the fixture.

The data layer (`models.py`, `parser_bridge.py`, `discovery.py`) doesn't
need PyGObject and is therefore testable on any platform. For the
integration test against a real save game:

```bash
R2WA_TEST_SAVE_DIR=/path/to/savegame just test
```

### Useful environment variables

| Variable | Effect |
|---|---|
| `R2WA_PARSER` | Path to the parser binary, overrides the search |
| `R2WA_SAVE_DIR` | Additional save game paths for `just discover` |
| `R2WA_TEST_SAVE_DIR` | Enables the integration test |

### The parser as a standalone tool

```bash
build/parser/r2wa-parser analyze --save-dir <path> --pretty
build/parser/r2wa-parser catalog --pretty    # item catalog without a save game
build/parser/r2wa-parser version
```

stdout carries nothing but JSON. On failure, a
`{"error":{"kind":…,"message":…}}` with exit code 1.

## Item icons and portraits

The items list shows an icon per item where one is available. Icons are
matched via `data/iteminfo.csv` (a Remnant2Toolkit export: item name,
category, and a link to the matching page on the Remnant wiki, wiki.gg) —
`src/r2wa/iteminfo.py` matches a catalog item to its CSV row (the internal
catalog ID and the CSV name don't always agree, so the match normalizes
both sides and compares), and derives the wiki image path from the page
name.

The actual image files are not fetched at UI runtime; `just fetch-icons`
(or automatically as part of `just build-parser`) downloads them once into
`build/icons/` (gitignored, like the parser binary). `src/r2wa/icons.py`
then only does a local file lookup — showing items never depends on a
network connection.

The export also supplies the **names**. For roughly 500 of the 849 catalog
entries the analyzer has no display name and puts the internal id in `name`
instead — all 40 traits among them, which is why the item list used to read
`Trait_BloodBond`. Where the analyzer does deliver a name it wins; it comes
from the game itself. Row title, search and sort order all use the resolved
name, so they can't drift apart.

Three sources fill in what the CSV export doesn't cover, in this order:
hand-picked files in `data/manual_icons/` (for items whose image filename
can't be derived — a slash in the page title, a typo in the link, or a quest
item that appears in no export at all), then the wiki, then Remnant2Toolkit's
CDN for the individual relic fragments and prisms, which the wiki only has
colour-coded placeholders for.

Loot groups get the same treatment in the worlds view: a group headed by a
vendor, a boss or a miniboss shows that character's portrait. Their filenames
on the wiki can't be derived either — "Reggie" is filed under
`Reginald_Reggie_Malone.jpg`, "Nightweaver" under `The_Nightweaver.jpg` — so
`data/portraits.csv` maps the name the save writes to the file to fetch and
to the wiki page, and the heading gets the same link button the items have.
The group type decides whether either is looked up at all, so a location that
happens to share a boss's name can't pick up that boss's picture.

The page is not derivable either: the save's "Norah" is "Dr. Norah" on the
wiki, "Blood Moon Altar" is "Bloodmoon Altar", and the database's own
"Gwentdil The Unburnt" is a typo for "Gwendil: The Unburnt". Every one of
the 46 entries was checked against the wiki's API rather than guessed.

## Flatpak

`just flatpak` builds the application into a Flatpak and installs it for the
current user; `just flatpak-bundle` additionally writes `r2wa.flatpak`, a
single file that someone else installs with

```
flatpak install --user ./r2wa.flatpak
```

That is the point of it: the recipient needs neither a .NET SDK nor
PyGObject, only Flatpak itself. Build the parser and fetch the icons first
(`just build-parser`) — the manifest copies both in rather than building or
downloading them.

The sandbox gets read-only access to the three directories Steam installs
itself into, and no network at all. A Steam library on another drive is
reached through the file chooser, which grants access to exactly the
directory the user picks.

**Not yet ready for Flathub.** Two things would have to be solved first: the
parser is built outside the manifest, because the .NET 10 SDK is not
available as a Flatpak extension, and the item pictures are copied into the
bundle instead of being built from source. See the comments in
`packaging/io.github.ludzig.R2wa.yml`.

## License

The code is MIT — see [LICENSE](LICENSE).

Not everything in this repository is, and an MIT badge alone would promise
more than it can keep:

| | Origin | Terms |
| --- | --- | --- |
| `data/manual_icons/` (32 PNG) | [Remnant 2 Wiki](https://remnant2.wiki.gg/) | CC BY-NC-SA 4.0 — **non-commercial**, share alike |
| `data/iteminfo.csv`, `data/toolkit_items.csv` | [Remnant2Toolkit](https://github.com/joshpayette/remnant2-toolkit) (GPL-3.0) | used with the maintainer's explicit permission, [issue #248](https://github.com/joshpayette/remnant2-toolkit/issues/248) |

Reusing those two rows is therefore not simply MIT, whatever this file says
about the code around them. The item pictures the application downloads at
build time come from the same two places and are covered by the same terms.

Both the data and the pictures trace back to the **Remnant 2 Wiki**, whose
community compiled them by hand and deliberately kept them free of
datamining. [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) has the
detail: which fields were taken, from where, and what was permitted.
