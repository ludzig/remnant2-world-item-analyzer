# Third-Party Components

This application would not be possible without the following prior work.
Remnant 2's save game format is Unreal Engine based and undocumented; the
real achievement lies in the parser and the item database.

## lib.remnant2.analyzer

- Author: AndrewSav
- Source: https://github.com/AndrewSav/lib.remnant2.analyzer
- License: MIT
- Included as a NuGet package in `parser/R2waParser.csproj`

Provides the save game analysis and contains the embedded `db.json` with
every item in the game, plus the logic for which of them a character is
still missing.

## lib.remnant2.saves

- Author: AndrewSav
- Source: https://github.com/AndrewSav/lib.remnant2.saves
- License: MIT
- Transitive dependency of `lib.remnant2.analyzer`

The actual format work: container decompression, CRC32 checking, and
Unreal property serialization.

## remnant-item-finder

- Author: t1nky
- Source: https://github.com/t1nky/remnant-item-finder

The original documentation of the file format that the two libraries above
build on.

## Remnant2Toolkit

- Author: joshpayette and contributors
- Source: https://github.com/joshpayette/remnant2-toolkit
- License: GPL-3.0

Two data files come from this project:

- `data/iteminfo.csv` - an item export from its database: item names,
  categories, and a link to the matching wiki page per item. The export's
  `description` column held the game's own item text; it was never read and
  has been removed, so none of it is redistributed here.
- `data/toolkit_items.csv` - extracted from the project's sources
  (`src/app/(items)/_constants/*-items.ts`, commit `8be610d`): the slug the
  game writes into the save file, plus the path of the item's image on the
  project's own CDN.

Neither lists quest items or crafting materials, which appear only in a
location's loot, nor the vendors and bosses a loot group is named after.
`data/manual_links.csv` names the wiki page of the former by hand, and
doubles as the record of where each file in `data/manual_icons/` came from;
`data/portraits.csv` does the same for the vendors and bosses: their portrait
file and their wiki page.

Both are used to match the parser's internal catalog IDs against item
metadata (see `src/r2wa/iteminfo.py`). The save-file slug is the reliable
key - display names differ between the two sources often enough
("Judgement" vs. "Judgment") that name comparison alone leaves gaps.

## Item icons and portraits

These are renders and screenshots of the game's own assets, made and hosted
by the wikis, not by us. Two sources, in this order of preference:

- Everything in `data/manual_icons/`, and everything `just fetch-icons`
  downloads (see `src/r2wa/icon_fetch.py`): the **Remnant 2 Wiki**,
  https://remnant2.wiki.gg/ (`remnant.wiki` redirects there). Licensed
  CC BY-NC-SA 4.0 - reuse with attribution is permitted, and this notice is
  that attribution. The hand-saved ones cover items whose image filename
  can't be derived from the CSV's wiki link: a slash in the page title, a
  typo in the link, or several items pointing at one generic page. The
  vendor and boss portraits come from here too - the wiki files them under
  names the game never uses ("Reggie" is `Reginald_Reggie_Malone.jpg`,
  "Nightweaver" is `The_Nightweaver.jpg`), which is what
  `data/portraits.csv` records.
- Only for the gaps the wiki leaves: **Remnant2Toolkit's** own CDN (see
  above). 75 images, fetched item by item and never for the whole catalog.
  The bulk of them are what the wiki has only colour-coded placeholders
  for - 46 relic fragments and 7 prisms - and the remaining 22 are items it
  carries no usable picture of at all (12 skills, 4 perks, 3 consumables,
  and one each of a weapon, a mod and an armour piece).

  They are cached under `build/` and are **not** in this repository. They
  **are**, however, inside the Flatpak bundle `just flatpak-bundle`
  produces, because that copies `build/icons` wholesale (see
  `packaging/io.github.ludzig.R2wa.yml`) - so handing someone the bundle
  does redistribute them.

  Their terms are not stated anywhere. Rather than assume, the question of
  whether both this and the two derived CSVs above are welcome has been put
  to the project's maintainer; the answer will be recorded here.

## Further dependencies of the parser

Pulled in transitively via `lib.remnant2.analyzer`:

- Newtonsoft.Json — MIT
- Serilog, SerilogTimings — Apache-2.0

The full license texts ship with the respective NuGet packages and can be
found at the sources linked above.

## Not affiliated

This application is not affiliated with Gunfire Games or Gearbox
Publishing. Remnant II is a trademark of its respective rights holders.

The application icon in `data/icons/` is our own work and deliberately does
not imitate the game's logo mark, which is part of that trademark. The item
pictures the application shows are the wikis' renders, credited above; none
of the game's own branding is reproduced anywhere.
