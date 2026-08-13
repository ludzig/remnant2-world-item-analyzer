"""Die Weltenansicht: was steckt in den aktuell gerollten Welten."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from ..gobjects import TreeNode, build_world_nodes  # noqa: E402
from ..models import Character, World, format_playtime  # noqa: E402


class WorldsView(Gtk.Box):
    """Kampagne und Abenteuer als aufklappbarer Baum Zone -> Ort -> Fundstelle."""

    __gtype_name__ = "R2waWorldsView"

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._character: Character | None = None
        self._slot = "campaign"
        self._only_open = False

        self._root = Gio.ListStore.new(TreeNode)

        tree = Gtk.TreeListModel.new(
            self._root,
            False,  # passthrough: die Zeilen liefern Gtk.TreeListRow
            False,  # autoexpand: der Baum startet zugeklappt
            _create_child_model,
        )
        self._filter = Gtk.CustomFilter.new(self._match)
        self._model = Gtk.FilterListModel.new(tree, self._filter)

        self.append(self._build_toolbar())

        self._scroller = self._build_tree(self._model)
        self.append(self._scroller)

        self._empty = Adw.StatusPage(
            icon_name="map-symbolic",
            title="Keine Welt gerollt",
            description="Für diesen Charakter liegt in diesem Slot keine Welt vor.",
            vexpand=True,
            visible=False,
        )
        self.append(self._empty)

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

        self._slot_switch = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, css_classes=["linked"])
        self._campaign_button = Gtk.ToggleButton(label="Kampagne", active=True)
        self._adventure_button = Gtk.ToggleButton(label="Abenteuer")
        self._adventure_button.set_group(self._campaign_button)
        self._campaign_button.connect(
            "toggled", lambda b: self._set_slot("campaign") if b.get_active() else None
        )
        self._adventure_button.connect(
            "toggled", lambda b: self._set_slot("adventure") if b.get_active() else None
        )
        self._slot_switch.append(self._campaign_button)
        self._slot_switch.append(self._adventure_button)
        bar.append(self._slot_switch)

        open_toggle = Gtk.ToggleButton(
            label="Nur Offenes",
            tooltip_text="Nur Zonen und Orte mit noch nicht eingesammelten Items",
        )
        open_toggle.connect("toggled", self._on_open_toggled)
        bar.append(open_toggle)

        self._info = Gtk.Label(css_classes=["dim-label"], xalign=1.0, hexpand=True)
        bar.append(self._info)

        expand = Gtk.Button(
            icon_name="view-list-symbolic",
            tooltip_text="Alle Zonen aufklappen",
            css_classes=["flat"],
        )
        expand.connect("clicked", lambda _b: self._set_all_expanded(True))
        bar.append(expand)

        collapse = Gtk.Button(
            icon_name="view-compact-symbolic",
            tooltip_text="Alle Zonen zuklappen",
            css_classes=["flat"],
        )
        collapse.connect("clicked", lambda _b: self._set_all_expanded(False))
        bar.append(collapse)

        return bar

    def _build_tree(self, model: Gio.ListModel) -> Gtk.Widget:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", _setup_row)
        factory.connect("bind", _bind_row)

        self._list = Gtk.ListView(
            model=Gtk.NoSelection.new(model),
            factory=factory,
            vexpand=True,
        )

        return Gtk.ScrolledWindow(
            child=self._list,
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
        )

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _match(self, row: Gtk.TreeListRow, _user_data=None) -> bool:
        if not self._only_open:
            return True

        node: TreeNode = row.get_item()
        # Ein Knoten bleibt sichtbar, solange unter ihm noch etwas offen ist;
        # ``dim`` markiert genau die abgehakten Zweige.
        return not node.dim

    def _on_open_toggled(self, button: Gtk.ToggleButton) -> None:
        self._only_open = button.get_active()
        self._filter.changed(Gtk.FilterChange.DIFFERENT)

    def _set_slot(self, slot: str) -> None:
        if slot == self._slot:
            return
        self._slot = slot
        self._reload()

    def _set_all_expanded(self, expanded: bool) -> None:
        """Klappe alle Zonen der obersten Ebene auf oder zu.

        Erst sammeln, dann umschalten: das Aufklappen fuegt Kindzeilen ins
        Modell ein, wodurch sich waehrend einer Schleife ueber die Indizes
        alles Nachfolgende verschieben wuerde.
        """
        model = self._list.get_model()
        rows = [
            row
            for index in range(model.get_n_items())
            if isinstance(row := model.get_item(index), Gtk.TreeListRow) and row.get_depth() == 0
        ]

        for row in rows:
            row.set_expanded(expanded)

    # ------------------------------------------------------------------
    # Befuellen
    # ------------------------------------------------------------------

    def set_character(self, character: Character | None) -> None:
        self._character = character
        self._update_slot_buttons()
        self._reload()

    def _update_slot_buttons(self) -> None:
        """Deaktiviere einen Slot, wenn der Charakter dort keine Welt hat."""
        has_campaign = bool(self._character and self._character.world("campaign"))
        has_adventure = bool(self._character and self._character.world("adventure"))

        self._campaign_button.set_sensitive(has_campaign)
        self._adventure_button.set_sensitive(has_adventure)

        if self._slot == "adventure" and not has_adventure and has_campaign:
            self._slot = "campaign"
            self._campaign_button.set_active(True)

    def _reload(self) -> None:
        world = self._character.world(self._slot) if self._character else None

        self._root.remove_all()
        if world is not None:
            nodes = build_world_nodes(world)
            if nodes:
                self._root.splice(0, 0, list(nodes))

        self._info.set_label(_world_summary(world))

        has_content = self._root.get_n_items() > 0
        self._scroller.set_visible(has_content)
        self._empty.set_visible(not has_content)


def _world_summary(world: World | None) -> str:
    if world is None:
        return ""

    parts = [world.label]
    if world.difficulty:
        parts.append(world.difficulty)
    if world.playtime_seconds:
        parts.append(format_playtime(world.playtime_seconds))

    open_items = sum(zone.open_item_count for zone in world.zones)
    if open_items:
        parts.append(f"{open_items} offen")

    return " · ".join(parts)


def _create_child_model(node: TreeNode, *_user_data) -> Gio.ListStore | None:
    """Kinder eines Knotens - Gtk.TreeListModel fragt beim Aufklappen danach."""
    return node.child_model()


def _setup_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    expander = Gtk.TreeExpander(
        indent_for_depth=True,
        indent_for_icon=True,
    )

    box = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=12,
        margin_top=6,
        margin_bottom=6,
    )

    icon = Gtk.Image()
    box.append(icon)

    labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
    title = Gtk.Label(xalign=0.0)
    subtitle = Gtk.Label(xalign=0.0, css_classes=["caption", "dim-label"], visible=False)
    labels.append(title)
    labels.append(subtitle)
    box.append(labels)

    badge = Gtk.Label(css_classes=["caption", "accent", "numeric"], valign=Gtk.Align.CENTER)
    box.append(badge)

    expander.set_child(box)

    box.r2wa_icon = icon
    box.r2wa_title = title
    box.r2wa_subtitle = subtitle
    box.r2wa_badge = badge

    list_item.set_child(expander)


def _bind_row(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
    row: Gtk.TreeListRow = list_item.get_item()
    node: TreeNode = row.get_item()

    expander: Gtk.TreeExpander = list_item.get_child()
    expander.set_list_row(row)

    box = expander.get_child()

    if node.icon:
        box.r2wa_icon.set_from_icon_name(node.icon)
        box.r2wa_icon.set_visible(True)
    else:
        box.r2wa_icon.set_visible(False)

    # Gtk.Label stellt Text ohne Markup dar - hier darf nicht maskiert werden,
    # sonst erschiene ein "&" im Item-Namen als "&amp;".
    box.r2wa_title.set_label(node.title)
    box.r2wa_title.set_css_classes(["dim-label"] if node.dim else [])

    box.r2wa_subtitle.set_label(node.subtitle)
    box.r2wa_subtitle.set_visible(bool(node.subtitle))

    box.r2wa_badge.set_label(node.badge)
    box.r2wa_badge.set_visible(bool(node.badge))
