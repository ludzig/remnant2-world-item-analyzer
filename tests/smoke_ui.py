"""Smoke test of the GTK UI.

Not pytest: the test needs PyGObject and a display, neither of which is
available everywhere. The filename deliberately doesn't start with
``test_`` so pytest doesn't pick it up.

The test actually builds the views, hangs them in a window, and lets the
main loop run - only then do the setup/bind factories run, where most bugs
live.

    python tests/smoke_ui.py               # fixture, closes itself
    python tests/smoke_ui.py --show        # leaves the window open
    python tests/smoke_ui.py --save-dir X  # real save game through the parser
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from r2wa.models import Analysis  # noqa: E402
from r2wa.views.items import ItemsView, Scope, Status  # noqa: E402
from r2wa.views.worlds import PORTRAIT_GROUP_TYPES, ItemStatus, WorldsView  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "analysis_minimal.json"

failures: list[str] = []
checks = 0


def check(condition: bool, description: str) -> None:
    global checks
    checks += 1
    if condition:
        print(f"  ok    {description}")
    else:
        print(f"  FAIL  {description}")
        failures.append(description)


def load_analysis(save_dir: str | None) -> Analysis:
    if save_dir:
        from r2wa.parser_bridge import analyze

        print(f"Analyzing {save_dir} ...")
        return analyze(save_dir)

    return Analysis.from_json(json.loads(FIXTURE.read_text(encoding="utf-8")))


def pump(seconds: float = 0.05) -> None:
    """Let the main loop run for a real amount of time.

    It's not enough to just process pending events: Gtk.SearchEntry only
    fires ``search-changed`` after a short typing pause, via a timeout.
    Without actual time passing, the search would never trigger in the test.
    """
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)


def pump_until(condition, seconds: float = 10.0) -> bool:
    """Pump the main loop until `condition` holds, or the time runs out.

    Waiting a fixed span instead makes the search checks flaky: the entry's
    debounce timeout only fires once the machine gets around to it, and on a
    cold start that can take a while. The ceiling is generous because it
    costs nothing - this returns the moment the condition holds.
    """
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def loaded_items(view: ItemsView) -> list:
    """Every item the view holds, across all categories."""
    return [obj for category in view._categories for obj in category.store]


def visible_items(view: ItemsView) -> int:
    """Item rows left by the filters. The category rows are not counted."""
    return sum(category.items.get_n_items() for category in view._categories)


def pump_search(view: ItemsView, needle: str, expected: int) -> None:
    """Type into the search entry and wait for the list to reflect it.

    Two delays sit in the way: the entry debounces typing before reporting a
    change, and the filter/sort models update in idle callbacks afterwards.
    Waiting for the visible outcome covers both - a fixed span covers
    neither reliably.

    The retry guards against something less obvious: this test presents a
    real window, which takes focus. Anything typed on the machine while it
    runs - a game in the background, say - lands in this entry and corrupts
    the search term.
    """
    for _ in range(3):
        view._search.set_text(needle)
        pump_until(lambda: view._needle == needle.strip())
        pump_until(lambda: visible_items(view) == expected)

        if view._search.get_text() == needle and visible_items(view) == expected:
            return
        print(f"  (retrying search: entry became {view._search.get_text()!r})")


def run_checks(analysis: Analysis, show: bool, save_dir: str | None) -> None:
    character = analysis.active_character
    print(f"\nCharacter: {character.title}, {len(character.items)} items")

    items_view = ItemsView()
    worlds_view = WorldsView()

    stack = Adw.ViewStack()
    stack.add_titled_with_icon(items_view, "items", "Items", "view-list-bullet-symbolic")
    stack.add_titled_with_icon(worlds_view, "worlds", "Worlds", "map-symbolic")

    window = Gtk.Window(title="r2wa Smoke Test", default_width=1100, default_height=760)
    window.set_child(stack)
    window.present()
    pump()

    print("\nItems view:")
    items_view.set_analysis(analysis, character)
    pump()

    total = len(character.items)
    check(len(loaded_items(items_view)) == total, f"store holds {total} items")
    check(visible_items(items_view) == total, "all visible without a filter")

    # The filter must leave exactly the missing items.
    missing = sum(1 for i in character.items if not i.acquired)
    items_view._on_status_changed(Status.MISSING)
    pump()
    check(visible_items(items_view) == missing, f"'Missing' filter shows {missing}")

    acquired = total - missing
    items_view._on_status_changed(Status.ACQUIRED)
    pump()
    check(visible_items(items_view) == acquired, f"'Found' filter shows {acquired}")

    items_view._on_status_changed(Status.ALL)
    pump()

    # Names: the analyzer leaves the internal id in `name` for a good half
    # of the catalog, traits for all of them. Nothing may reach a row raw.
    raw_named = [obj.item.id for obj in loaded_items(items_view) if obj.display_name == obj.item.id]
    check(
        not raw_named,
        f"every row has a real name, not an internal id ({len(raw_named)} raw: {raw_named[:3]})",
    )

    # "Reroll needed" must not be claimed where reachability is merely
    # undecided - the analyzer gives up on a few items with prerequisites.
    undecided = [
        i
        for i in character.items
        if not i.acquired
        and any(
            character.world(slot) is not None and obtainable is None
            for slot, obtainable in (
                ("campaign", i.state.obtainable_in_campaign),
                ("adventure", i.state.obtainable_in_adventure),
            )
        )
    ]
    if undecided:
        labels = [label for label, _ in items_view._badges_for(undecided[0])]
        check(
            "Reachability unknown" in labels and "Reroll needed" not in labels,
            f"undecided reachability says so instead of 'Reroll needed' ({labels})",
        )

    # Search
    sample = next((i for i in character.items if i.name and " " in i.name), character.items[0])
    needle = sample.name.split(" ")[0]

    def would_match(item, text: str) -> bool:
        """Mirror of ItemsView._match - the raw index plus the shown name."""
        shown = items_view._display_names.get(item.id, item.name)
        return item.matches(text) or text.casefold() in shown.casefold()

    expected = sum(1 for i in character.items if would_match(i, needle))
    pump_search(items_view, needle, expected)
    hits = visible_items(items_view)
    check(
        hits == expected,
        f"search '{needle}' finds {expected} (got {hits}, "
        f"needle={items_view._needle!r}, entry={items_view._search.get_text()!r}, "
        f"store={len(loaded_items(items_view))})",
    )

    # A name that only exists after resolving: "Blood Bond" is
    # `Trait_BloodBond` in the save, so the space finds nothing without it.
    two_word = next(
        (
            items_view._display_names[i.id]
            for i in character.items
            if i.name == i.id and " " in items_view._display_names.get(i.id, "")
        ),
        None,
    )
    if two_word:
        wanted = sum(1 for i in character.items if would_match(i, two_word))
        pump_search(items_view, two_word, wanted)
        check(
            visible_items(items_view) == wanted and wanted > 0,
            f"search finds the resolved name {two_word!r}",
        )

    pump_search(items_view, "zzz-does-not-exist-zzz", 0)
    check(visible_items(items_view) == 0, "nonsense search yields nothing")
    check(items_view._empty.get_visible(), "empty state is shown")

    pump_search(items_view, "", total)
    check(not items_view._empty.get_visible(), "empty state disappears again")
    check(visible_items(items_view) == total, "all visible again after clearing")

    # Folding. The categories are rows of the list now, so collapsing one
    # takes its items out of the list without taking the heading with them.
    categories = [obj.category for obj in items_view._categories]
    unfolded = items_view._tree.get_n_items()
    check(
        unfolded == total + len(categories),
        f"{len(categories)} category rows on top of {total} items (got {unfolded})",
    )

    items_view._toggle_all.emit("clicked")
    pump()
    check(
        items_view._tree.get_n_items() == len(categories),
        "collapsing all leaves nothing but the category rows",
    )
    check(visible_items(items_view) == total, "... while the items stay in the model")

    # A search has to be able to show what it found, so it opens the folded
    # categories - and folds them back when the search box is empty again.
    pump_search(items_view, needle, expected)
    check(
        items_view._tree.get_n_items() > items_view._visible.get_n_items(),
        "a search opens the folded categories",
    )
    pump_search(items_view, "", total)
    check(
        items_view._collapsed == set(categories),
        "clearing the search folds them back the way they were",
    )

    items_view._toggle_all.emit("clicked")
    pump()
    check(items_view._tree.get_n_items() == unfolded, "expanding all brings the items back")

    # Account-wide view
    if len(analysis.characters) > 1:
        items_view._on_scope_changed(Scope.ACCOUNT)
        pump()
        aggregate = analysis.aggregate_items()
        check(
            len(loaded_items(items_view)) == len(aggregate),
            f"'All Characters' view shows {len(aggregate)} items",
        )
        items_view._on_scope_changed(Scope.CHARACTER)
        pump()

    print("\nWorlds view:")
    stack.set_visible_child_name("worlds")

    # Prefer the selected character; only fall back to another one if they
    # have no rolled world.
    with_world = character
    if not character.world("campaign"):
        with_world = next((c for c in analysis.characters if c.world("campaign")), character)
        print(f"  (using {with_world.title}, the active character has no world)")
    worlds_view.set_analysis(analysis, with_world)
    pump()

    campaign = with_world.world("campaign")
    check(campaign is not None, "a character with a rolled campaign exists")
    if campaign:
        check(
            worlds_view._zone_store.get_n_items() == len(campaign.zones),
            f"campaign has {len(campaign.zones)} zones",
        )

        # Picking the first zone must fill the locations column, and picking
        # its first location must fill the items column.
        worlds_view._zone_selection.set_selected(0)
        pump()
        first_zone = campaign.zones[0]
        check(
            worlds_view._location_store.get_n_items() == len(first_zone.locations),
            f"selecting a zone shows its {len(first_zone.locations)} locations",
        )

        if first_zone.locations:
            first_location = first_zone.locations[0]
            expected_items = sum(len(g.items) for g in first_location.loot_groups)
            check(
                worlds_view._item_store.get_n_items() == expected_items,
                f"selecting a location shows its {expected_items} items",
            )

            # The item list's own status filter.
            missing = sum(1 for i in first_location.items if not i.is_looted)
            worlds_view._on_item_status_changed(ItemStatus.MISSING)
            pump()
            check(
                worlds_view._item_model.get_n_items() == missing,
                f"item list 'Missing' filter shows {missing}",
            )
            worlds_view._on_item_status_changed(ItemStatus.ALL)
            pump()

        if len(campaign.zones) > 1:
            # A live save-game reload must restore the drill-down the user
            # had, not reset to the first zone - regression test for that.
            last_index = len(campaign.zones) - 1
            worlds_view._zone_selection.set_selected(last_index)
            pump()
            expected_zone = campaign.zones[last_index]
            expected_location = expected_zone.locations[0] if expected_zone.locations else None

            # Re-run the same loading path used to build `analysis` in the
            # first place, so this simulates an actual save-game reload
            # instead of always reloading the fixture regardless of --save-dir.
            reloaded = load_analysis(save_dir)
            reloaded_character = next(c for c in reloaded.characters if c.index == with_world.index)

            # The window rebuilds its character list on a reload, and an
            # emptied Gtk.ListBox reports "nothing selected" on the way -
            # so the views really do see a None before the new character.
            # Restoring has to survive that; leaving it out here is what let
            # the bug through the first time.
            worlds_view.set_analysis(reloaded, None)
            pump()
            worlds_view.set_analysis(reloaded, reloaded_character)
            pump()

            selected_zone = worlds_view._zone_selection.get_selected_item()
            check(
                selected_zone is not None and selected_zone.zone.name == expected_zone.name,
                f"reload restores the selected zone ({expected_zone.name!r})",
            )
            if expected_location is not None:
                selected_location = worlds_view._location_selection.get_selected_item()
                check(
                    selected_location is not None
                    and selected_location.location.name == expected_location.name,
                    f"reload restores the selected location ({expected_location.name!r})",
                )

        # The loot only names an item; its note on where and how to find it
        # comes from the account-wide catalog and has to survive the join.
        if first_zone.locations:
            noted = [obj for obj in worlds_view._item_store if obj.note]

            def catalog_note(item_id: str) -> str | None:
                entry = analysis.catalog.get(item_id)
                return entry.note if entry else None

            mismatched = [
                obj.item.name
                for obj in worlds_view._item_store
                if obj.note != catalog_note(obj.item.id)
            ]
            check(
                bool(noted) and not mismatched,
                f"{len(noted)} loot items carry the catalog's note"
                + (f" - wrong: {mismatched[:3]}" if mismatched else ""),
            )

        # Vendor and boss headings get a portrait. Checked end to end: drill
        # down to a location that actually has one and read back what the
        # list model carries.
        portrait_spot = next(
            (
                (zone_index, location_index, group.label)
                for zone_index, zone in enumerate(campaign.zones)
                for location_index, location in enumerate(zone.locations)
                for group in location.loot_groups
                if (group.type or "").casefold() in PORTRAIT_GROUP_TYPES and group.items
            ),
            None,
        )
        if portrait_spot is not None:
            zone_index, location_index, label = portrait_spot
            worlds_view._zone_selection.set_selected(zone_index)
            pump()
            worlds_view._location_selection.set_selected(location_index)
            pump()
            headed = [
                obj
                for obj in worlds_view._item_store
                if obj.group_type.casefold() in PORTRAIT_GROUP_TYPES
            ]
            check(
                bool(headed)
                and all(
                    o.group_icon_path is not None and o.group_icon_path.is_file() for o in headed
                ),
                f"loot group heading carries a portrait ({label!r})",
            )
            check(
                bool(headed) and all(o.group_wiki_url for o in headed),
                f"loot group heading carries a wiki link ({label!r})",
            )

        # And every such group in the whole campaign, not just that one.
        named = {
            group.label
            for zone in campaign.zones
            for location in zone.locations
            for group in location.loot_groups
            if (group.type or "").casefold() in PORTRAIT_GROUP_TYPES
        }
        if named:
            missing_portraits = sorted(
                name for name in named if worlds_view._icons.portrait_for(name) is None
            )
            check(
                not missing_portraits,
                f"all {len(named)} vendors/bosses have a portrait"
                + (f" - missing: {missing_portraits}" if missing_portraits else ""),
            )
            missing_links = sorted(
                name for name in named if worlds_view._icons.portrait_wiki_url_for(name) is None
            )
            check(
                not missing_links,
                f"all {len(named)} vendors/bosses have a wiki link"
                + (f" - missing: {missing_links}" if missing_links else ""),
            )

        # "Open Only" hides fully collected zones/locations, never adds rows.
        before = worlds_view._zone_selection.get_n_items()
        worlds_view._only_open = True
        worlds_view._zone_filter.changed(Gtk.FilterChange.DIFFERENT)
        worlds_view._location_filter.changed(Gtk.FilterChange.DIFFERENT)
        pump()
        check(
            worlds_view._zone_selection.get_n_items() <= before,
            "'Open Only' filter doesn't show anything extra",
        )
        worlds_view._only_open = False
        worlds_view._zone_filter.changed(Gtk.FilterChange.DIFFERENT)
        worlds_view._location_filter.changed(Gtk.FilterChange.DIFFERENT)
        pump()

    if with_world.world("adventure"):
        worlds_view._set_slot("adventure")
        pump()
        check(True, "switching to adventure without crashing")
        worlds_view._set_slot("campaign")
        pump()

    # Character switching: the most common source of rebuild bugs.
    print("\nCharacter switching:")
    for other in analysis.characters:
        items_view.set_analysis(analysis, other)
        worlds_view.set_analysis(analysis, other)
        pump()
    check(True, "cycled through all characters")

    # Empty state
    items_view.set_analysis(None, None)
    worlds_view.set_analysis(analysis, None)
    pump()
    check(not loaded_items(items_view), "empty selection clears the list")
    check(items_view._tree.get_n_items() == 0, "... category rows and all")

    if show:
        print("\nWindow stays open - close it to quit.")
        loop = GLib.MainLoop()
        window.connect("close-request", lambda *_: (loop.quit(), False)[1])
        loop.run()
    else:
        window.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test of the GTK UI")
    parser.add_argument("--show", action="store_true", help="Leave the window open")
    parser.add_argument("--save-dir", help="Use a real save game instead of the fixture")
    args = parser.parse_args()

    Adw.init()

    print(
        f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}, "
        f"libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}"
    )

    try:
        analysis = load_analysis(args.save_dir)
    except Exception as exc:  # noqa: BLE001 - diagnosis is the point here
        print(f"Analysis failed: {exc}")
        return 2

    try:
        run_checks(analysis, args.show, args.save_dir)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        failures.append("Exception while building the UI")

    print(f"\n{checks - len(failures)} of {checks} checks passed.")
    for failure in failures:
        print(f"  failed: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
