"""Small widget builders shared between the views."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, Gtk  # noqa: E402


def open_uri(url: str | None) -> None:
    """Open a URL in the default browser; a missing default handler is not fatal."""
    if url is None:
        return
    try:
        Gio.AppInfo.launch_default_for_uri(url, None)
    except GLib.Error:
        pass


def toggle_group(
    entries: list[tuple[str, object]],
    active: object,
    on_change,
    tooltips: list[str] | None = None,
) -> Gtk.Widget:
    """A row of linked toggle buttons with radio behavior.

    Adw.ToggleGroup only exists from libadwaita 1.7 onward; linked
    Gtk.ToggleButtons look practically the same and work everywhere.
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
        # "toggled" also fires on deselection - only activation counts.
        button.connect(
            "toggled",
            lambda btn, val=value: on_change(val) if btn.get_active() else None,
        )
        box.append(button)

    return box
