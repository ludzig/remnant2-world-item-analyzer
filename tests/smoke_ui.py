"""Smoke-Test der GTK-Oberflaeche.

Kein pytest: der Test braucht PyGObject und eine Anzeige, beides ist nicht
ueberall vorhanden. Der Dateiname beginnt bewusst nicht mit ``test_``, damit
pytest ihn nicht einsammelt.

Der Test baut die Ansichten wirklich auf, haengt sie in ein Fenster und laesst
den Main-Loop laufen - nur dann rufen die Factories setup/bind auf, wo die
meisten Fehler stecken.

    python tests/smoke_ui.py               # Fixture, schliesst sich selbst
    python tests/smoke_ui.py --show        # Fenster offen lassen
    python tests/smoke_ui.py --save-dir X  # echtes Savegame durch den Parser
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
from r2wa.views.worlds import WorldsView  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "analysis_minimal.json"

failures: list[str] = []
checks = 0


def check(condition: bool, description: str) -> None:
    global checks
    checks += 1
    if condition:
        print(f"  ok    {description}")
    else:
        print(f"  FEHLT {description}")
        failures.append(description)


def load_analysis(save_dir: str | None) -> Analysis:
    if save_dir:
        from r2wa.parser_bridge import analyze

        print(f"Analysiere {save_dir} ...")
        return analyze(save_dir)

    return Analysis.from_json(json.loads(FIXTURE.read_text(encoding="utf-8")))


def pump(seconds: float = 0.05) -> None:
    """Lass den Main-Loop echte Zeit lang laufen.

    Es reicht nicht, nur anstehende Ereignisse abzuarbeiten: Gtk.SearchEntry
    feuert ``search-changed`` erst nach einer kurzen Tipppause ueber einen
    Timeout. Ohne vergehende Zeit wuerde die Suche im Test nie greifen.
    """
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)


def pump_search() -> None:
    """Warte lange genug, dass die verzoegerte Suche ausgeloest hat."""
    pump(0.5)


def run_checks(analysis: Analysis, show: bool) -> None:
    character = analysis.active_character
    print(f"\nCharakter: {character.title}, {len(character.items)} Items")

    items_view = ItemsView()
    worlds_view = WorldsView()

    stack = Adw.ViewStack()
    stack.add_titled_with_icon(items_view, "items", "Items", "view-list-bullet-symbolic")
    stack.add_titled_with_icon(worlds_view, "worlds", "Welten", "map-symbolic")

    window = Gtk.Window(title="r2wa Smoke-Test", default_width=1100, default_height=760)
    window.set_child(stack)
    window.present()
    pump()

    print("\nItems-Ansicht:")
    items_view.set_analysis(analysis, character)
    pump()

    total = len(character.items)
    check(items_view._store.get_n_items() == total, f"Speicher enthaelt {total} Items")
    check(items_view._model.get_n_items() == total, "ohne Filter sind alle sichtbar")

    # Der Filter muss genau die fehlenden Items uebrig lassen.
    missing = sum(1 for i in character.items if not i.acquired)
    items_view._on_status_changed(Status.MISSING)
    pump()
    check(items_view._model.get_n_items() == missing, f"Filter 'Fehlend' zeigt {missing}")

    acquired = total - missing
    items_view._on_status_changed(Status.ACQUIRED)
    pump()
    check(items_view._model.get_n_items() == acquired, f"Filter 'Gefunden' zeigt {acquired}")

    items_view._on_status_changed(Status.ALL)
    pump()

    # Suche
    sample = next((i for i in character.items if i.name and " " in i.name), character.items[0])
    needle = sample.name.split(" ")[0]
    items_view._search.set_text(needle)
    pump_search()
    hits = items_view._model.get_n_items()
    expected = sum(1 for i in character.items if i.matches(needle))
    check(hits == expected, f"Suche '{needle}' findet {expected} (war {hits})")

    items_view._search.set_text("zzz-gibt-es-nicht-zzz")
    pump_search()
    check(items_view._model.get_n_items() == 0, "unsinnige Suche liefert nichts")
    check(items_view._empty.get_visible(), "Leerzustand wird eingeblendet")

    items_view._search.set_text("")
    pump_search()
    check(not items_view._empty.get_visible(), "Leerzustand verschwindet wieder")
    check(items_view._model.get_n_items() == total, "nach dem Leeren wieder alle sichtbar")

    # Kontoweite Sicht
    if len(analysis.characters) > 1:
        items_view._on_scope_changed(Scope.ACCOUNT)
        pump()
        aggregate = analysis.aggregate_items()
        check(
            items_view._store.get_n_items() == len(aggregate),
            f"Sicht 'Alle Charaktere' zeigt {len(aggregate)} Items",
        )
        items_view._on_scope_changed(Scope.CHARACTER)
        pump()

    print("\nWelten-Ansicht:")
    stack.set_visible_child_name("worlds")

    # Bevorzugt der gewaehlte Charakter; nur wenn der keine gerollte Welt hat,
    # wird auf einen anderen ausgewichen.
    with_world = character
    if not character.world("campaign"):
        with_world = next((c for c in analysis.characters if c.world("campaign")), character)
        print(f"  (nutze {with_world.title}, der aktive Charakter hat keine Welt)")
    worlds_view.set_character(with_world)
    pump()

    campaign = with_world.world("campaign")
    check(campaign is not None, "ein Charakter mit gerollter Kampagne vorhanden")
    if campaign:
        check(
            worlds_view._root.get_n_items() == len(campaign.zones),
            f"Kampagne hat {len(campaign.zones)} Zonen",
        )

        # Aufklappen muss die Orte sichtbar machen.
        before = worlds_view._model.get_n_items()
        worlds_view._set_all_expanded(True)
        pump()
        after = worlds_view._model.get_n_items()
        check(after > before, f"Aufklappen zeigt mehr Zeilen ({before} -> {after})")

        worlds_view._set_all_expanded(False)
        pump()
        check(
            worlds_view._model.get_n_items() == before,
            "Zuklappen stellt den Ausgangszustand her",
        )

        worlds_view._set_all_expanded(True)
        pump()
        worlds_view._only_open = True
        worlds_view._filter.changed(Gtk.FilterChange.DIFFERENT)
        pump()
        check(
            worlds_view._model.get_n_items() <= after,
            "Filter 'Nur Offenes' blendet nichts zusaetzlich ein",
        )
        worlds_view._only_open = False
        worlds_view._filter.changed(Gtk.FilterChange.DIFFERENT)
        pump()

    if with_world.world("adventure"):
        worlds_view._set_slot("adventure")
        pump()
        check(True, "Wechsel auf Abenteuer ohne Absturz")
        worlds_view._set_slot("campaign")
        pump()

    # Charakterwechsel: haeufigste Quelle fuer Fehler beim Neuaufbau.
    print("\nCharakterwechsel:")
    for other in analysis.characters:
        items_view.set_analysis(analysis, other)
        worlds_view.set_character(other)
        pump()
    check(True, "alle Charaktere durchgeschaltet")

    # Leerer Zustand
    items_view.set_analysis(None, None)
    worlds_view.set_character(None)
    pump()
    check(items_view._store.get_n_items() == 0, "leere Auswahl raeumt die Liste")

    if show:
        print("\nFenster bleibt offen - schliessen zum Beenden.")
        loop = GLib.MainLoop()
        window.connect("close-request", lambda *_: (loop.quit(), False)[1])
        loop.run()
    else:
        window.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-Test der GTK-Oberflaeche")
    parser.add_argument("--show", action="store_true", help="Fenster offen lassen")
    parser.add_argument("--save-dir", help="echtes Savegame statt des Fixtures")
    args = parser.parse_args()

    Adw.init()

    print(
        f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}, "
        f"libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}"
    )

    try:
        analysis = load_analysis(args.save_dir)
    except Exception as exc:  # noqa: BLE001 - Diagnose ist hier der Zweck
        print(f"Analyse fehlgeschlagen: {exc}")
        return 2

    try:
        run_checks(analysis, args.show)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        failures.append("Ausnahme waehrend des Aufbaus")

    print(f"\n{checks - len(failures)} von {checks} Prüfungen bestanden.")
    for failure in failures:
        print(f"  fehlgeschlagen: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
