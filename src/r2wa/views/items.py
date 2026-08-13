"""Die Item-Checkliste: was habe ich, was fehlt mir noch."""

from __future__ import annotations

from enum import Enum

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..gobjects import ItemObject  # noqa: E402
from ..models import (  # noqa: E402
    Analysis,
    Character,
    Counts,
    Item,
    category_label,
    category_sort_key,
    counts_for,
)


class Status(Enum):
    """Welche Items die Liste zeigt."""

    ALL = "all"
    MISSING = "missing"
    ACQUIRED = "acquired"


class Scope(Enum):
    """Wessen Sammelstand die Liste zeigt."""

    CHARACTER = "character"
    ACCOUNT = "account"


class ItemsView(Gtk.Box):
    """Gefilterte, nach Kategorie gruppierte Liste aller Sammelobjekte."""

    __gtype_name__ = "R2waItemsView"

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._analysis: Analysis | None = None
        self._character: Character | None = None
        self._status = Status.ALL
        self._scope = Scope.CHARACTER
        self._needle = ""
        self._counts = Counts()

        # Datenkette: Speicher -> Filter -> Sortierung mit Abschnitten.
        # Gtk.SortListModel liefert die Abschnitte fuer die Kategorie-
        # Ueberschriften, sobald ein section-sorter gesetzt ist (GTK 4.12+).
        self._store = Gio.ListStore.new(ItemObject)

        self._filter = Gtk.CustomFilter.new(self._match)
        filtered = Gtk.FilterListModel.new(self._store, self._filter)

        self._model = Gtk.SortListModel.new(filtered, _build_sorter())
        self._model.set_section_sorter(_build_section_sorter())

        self.append(self._build_toolbar())

        self._scroller = self._build_list(self._model)
        self.append(self._scroller)

        self._empty = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title="Keine Treffer",
            description="Andere Suchbegriffe oder einen anderen Filter versuchen.",
            vexpand=True,
            visible=False,
        )
        self.append(self._empty)

        self._model.connect("items-changed", lambda *_: self._update_empty_state())

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> Gtk.Widget:
        bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        self._search = Gtk.SearchEntry(
            placeholder_text="Item, Kategorie oder Fundstelle suchen",
            hexpand=True,
        )
        self._search.connect("search-changed", self._on_search_changed)
        bar.append(self._search)

        bar.append(
            _toggle_group(
                [
                    ("Alle", Status.ALL),
                    ("Fehlend", Status.MISSING),
                    ("Gefunden", Status.ACQUIRED),
                ],
                active=Status.ALL,
                on_change=self._on_status_changed,
            )
        )

        self._scope_group = _toggle_group(
            [
                ("Charakter", Scope.CHARACTER),
                ("Alle", Scope.ACCOUNT),
            ],
            active=Scope.CHARACTER,
            on_change=self._on_scope_changed,
            tooltips=[
                "Nur der Sammelstand des gewählten Charakters",
                "Über alle Charaktere zusammengefasst",
            ],
        )
        bar.append(self._scope_group)

        self._summary = Gtk.Label(css_classes=["dim-label", "numeric"], xalign=1.0)
        bar.append(self._summary)

        return bar

    def _build_list(self, model: Gio.ListModel) -> Gtk.Widget:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", _setup_row)
        factory.connect("bind", self._bind_row)

        header_factory = Gtk.SignalListItemFactory()
        header_factory.connect("setup", _setup_header)
        header_factory.connect("bind", self._bind_header)

        self._list = Gtk.ListView(
            model=Gtk.NoSelection.new(model),
            factory=factory,
            header_factory=header_factory,
            vexpand=True,
            show_separators=False,
        )

        return Gtk.ScrolledWindow(
            child=self._list,
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
        )

    # ------------------------------------------------------------------
    # Zeilen
    # ------------------------------------------------------------------

    def _bind_row(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        obj: ItemObject = list_item.get_item()
        item = obj.item
        row: Adw.ActionRow = list_item.get_child()

        row.set_title(_escape(item.name))
        row.set_subtitle(_escape(self._subtitle_for(item)))

        check: Gtk.Image = row.r2wa_check
        check.set_from_icon_name("object-select-symbolic" if item.acquired else "checkbox-symbolic")
        check.set_css_classes(["success"] if item.acquired else ["dim-label"])

        # Erledigtes tritt zurueck, damit die offenen Zeilen ins Auge fallen.
        row.set_css_classes(["dim-label"] if item.acquired else [])

        badges: Gtk.Box = row.r2wa_badges
        _clear(badges)
        for label, style in self._badges_for(item):
            badges.append(Gtk.Label(label=label, css_classes=["caption", style]))

    @staticmethod
    def _subtitle_for(item: Item) -> str:
        parts: list[str] = []
        if item.subcategory:
            parts.append(item.subcategory)
        if item.catalog.source:
            parts.append(item.catalog.source)
        elif item.catalog.note:
            parts.append(item.catalog.note)
        return " · ".join(parts)

    def _badges_for(self, item: Item) -> list[tuple[str, str]]:
        """Kurzhinweise rechts in der Zeile."""
        badges: list[tuple[str, str]] = []

        if item.acquired:
            if item.state.is_equipped:
                badges.append(("ausgerüstet", "accent"))
            if item.state.level:
                badges.append((f"Stufe {item.state.level}", "dim-label"))
            return badges

        # Erreichbarkeit ist nur bei fehlenden Items interessant und nur dann
        # aussagekraeftig, wenn ein konkreter Charakter gewaehlt ist - die
        # Welten gehoeren dem Charakter, nicht dem Account.
        if self._scope is Scope.CHARACTER:
            if item.state.obtainable_in_campaign:
                badges.append(("Kampagne", "success"))
            if item.state.obtainable_in_adventure:
                badges.append(("Abenteuer", "success"))
            if not item.state.obtainable_now:
                badges.append(("Reroll nötig", "warning"))

        if item.catalog.coop_only:
            badges.append(("Koop", "accent"))

        return badges

    def _bind_header(
        self, _factory: Gtk.SignalListItemFactory, list_header: Gtk.ListHeader
    ) -> None:
        obj: ItemObject = list_header.get_item()
        category = obj.item.category
        box = list_header.get_child()

        box.r2wa_title.set_label(category_label(category))

        # Der Zaehler zeigt bewusst den vollen Bestand der Kategorie, nicht die
        # gerade sichtbare Teilmenge - sonst waere er beim Filtern wertlos.
        counts = self._counts.by_category.get(category)
        box.r2wa_count.set_label(f"{counts.acquired} / {counts.total}" if counts else "")

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _match(self, obj: ItemObject, _user_data=None) -> bool:
        item = obj.item

        if self._status is Status.MISSING and item.acquired:
            return False
        if self._status is Status.ACQUIRED and not item.acquired:
            return False

        return item.matches(self._needle)

    # ------------------------------------------------------------------
    # Signale
    # ------------------------------------------------------------------

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._needle = entry.get_text().strip()
        self._filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_status_changed(self, status: Status) -> None:
        self._status = status
        self._filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_scope_changed(self, scope: Scope) -> None:
        if scope is self._scope:
            return
        self._scope = scope
        self._reload_items()

    # ------------------------------------------------------------------
    # Befuellen
    # ------------------------------------------------------------------

    def set_analysis(self, analysis: Analysis | None, character: Character | None) -> None:
        """Zeige die Items eines Charakters (oder des ganzen Accounts)."""
        self._analysis = analysis
        self._character = character
        self._scope_group.set_sensitive(analysis is not None and len(analysis.characters) > 1)
        self._reload_items()

    def _reload_items(self) -> None:
        items = self._current_items()
        self._counts = counts_for(items)

        self._store.remove_all()
        if items:
            self._store.splice(0, 0, [ItemObject(item) for item in items])

        self._summary.set_label(f"{self._counts.acquired} / {self._counts.total}" if items else "")
        self._update_empty_state()

    def _current_items(self) -> list[Item]:
        if self._analysis is None:
            return []
        if self._scope is Scope.ACCOUNT:
            return list(self._analysis.aggregate_items())
        return list(self._character.items) if self._character else []

    def _update_empty_state(self) -> None:
        has_rows = self._model.get_n_items() > 0
        self._empty.set_visible(not has_rows)
        self._scroller.set_visible(has_rows)


# ----------------------------------------------------------------------
# Bausteine ohne Zustand
# ----------------------------------------------------------------------


def _setup_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    row = Adw.ActionRow(activatable=False)

    check = Gtk.Image(icon_name="checkbox-symbolic")
    row.add_prefix(check)

    badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
    row.add_suffix(badges)

    # Referenzen am Widget selbst ablegen, nicht am Gtk.ListItem: die Zeilen
    # werden beim Scrollen wiederverwendet, das Widget bleibt dabei bestehen.
    row.r2wa_check = check
    row.r2wa_badges = badges

    list_item.set_child(row)


def _setup_header(_factory: Gtk.SignalListItemFactory, list_header: Gtk.ListHeader) -> None:
    box = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=12,
        margin_top=18,
        margin_bottom=6,
        margin_start=12,
        margin_end=12,
    )
    title = Gtk.Label(xalign=0.0, hexpand=True, css_classes=["heading"])
    count = Gtk.Label(xalign=1.0, css_classes=["dim-label", "numeric"])
    box.append(title)
    box.append(count)

    box.r2wa_title = title
    box.r2wa_count = count

    list_header.set_child(box)


def _build_sorter() -> Gtk.Sorter:
    """Nach Kategorie in Anzeigereihenfolge, darin alphabetisch."""

    def compare(a: ItemObject, b: ItemObject, _user_data=None) -> int:
        key_a = (category_sort_key(a.item.category), a.item.name.casefold())
        key_b = (category_sort_key(b.item.category), b.item.name.casefold())
        return (key_a > key_b) - (key_a < key_b)

    return Gtk.CustomSorter.new(compare)


def _build_section_sorter() -> Gtk.Sorter:
    """Gruppiert die Liste nach Kategorie; muss zur Sortierung passen."""

    def compare(a: ItemObject, b: ItemObject, _user_data=None) -> int:
        key_a = category_sort_key(a.item.category)
        key_b = category_sort_key(b.item.category)
        return (key_a > key_b) - (key_a < key_b)

    return Gtk.CustomSorter.new(compare)


def _toggle_group(
    entries: list[tuple[str, object]],
    active: object,
    on_change,
    tooltips: list[str] | None = None,
) -> Gtk.Widget:
    """Eine Reihe verbundener Umschalter mit Radio-Verhalten.

    Adw.ToggleGroup gibt es erst ab libadwaita 1.7; verbundene
    Gtk.ToggleButtons sehen praktisch gleich aus und laufen ueberall.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, css_classes=["linked"])
    first: Gtk.ToggleButton | None = None

    for index, (label, value) in enumerate(entries):
        button = Gtk.ToggleButton(label=label, active=value == active)
        if tooltips and index < len(tooltips):
            button.set_tooltip_text(tooltips[index])
        if first is None:
            first = button
        else:
            button.set_group(first)
        # "toggled" feuert auch beim Abwaehlen - nur die Aktivierung zaehlt.
        button.connect(
            "toggled",
            lambda btn, val=value: on_change(val) if btn.get_active() else None,
        )
        box.append(button)

    return box


def _clear(box: Gtk.Box) -> None:
    """Entferne alle Kinder einer Box."""
    child = box.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        box.remove(child)
        child = following


def _escape(text: str) -> str:
    """Maskiere Markup-Zeichen.

    Adw.ActionRow interpretiert Titel und Untertitel als Pango-Markup; ein
    ``&`` im Item-Namen wuerde die Zeile sonst zerlegen.
    """
    return GLib.markup_escape_text(text) if text else ""
