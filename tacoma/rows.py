"""Rows for devices (sinks/sources) and streams (playback/recording)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import audio  # noqa: E402

_MAX_PERCENT = 150
_DEBOUNCE_MS = 180


class VolumeControl(Gtk.Box):
    """Slider + percent label that debounces writes to the audio server."""

    def __init__(self, on_commit) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._on_commit = on_commit
        self._syncing = False
        self._pending: int | None = None
        self._timer = 0

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, _MAX_PERCENT, 1)
        self.scale.set_draw_value(False)
        self.scale.set_size_request(170, -1)
        self.scale.set_valign(Gtk.Align.CENTER)
        self.scale.connect("value-changed", self._on_value_changed)

        self.percent = Gtk.Label(label="0%")
        self.percent.add_css_class("mixer-percent")
        self.percent.set_width_chars(5)
        self.percent.set_xalign(1.0)

        self.append(self.scale)
        self.append(self.percent)

    def set_value(self, percent: int) -> None:
        self._syncing = True
        self.scale.set_value(percent)
        self.percent.set_label(f"{percent}%")
        self._syncing = False

    def _on_value_changed(self, scale) -> None:
        if self._syncing:
            return
        percent = int(round(scale.get_value()))
        self.percent.set_label(f"{percent}%")
        self._pending = percent
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(_DEBOUNCE_MS, self._flush)

    def _flush(self) -> bool:
        self._timer = 0
        if self._pending is not None:
            self._on_commit(self._pending)
            self._pending = None
        return GLib.SOURCE_REMOVE


class _MuteButton(Gtk.ToggleButton):
    def __init__(self, on_toggle) -> None:
        super().__init__()
        self.add_css_class("flat")
        self.set_tooltip_text("Mute")
        self._syncing = False
        self._on_toggle = on_toggle
        self.set_icon_name("audio-volume-high-symbolic")
        self.connect("toggled", self._on_toggled)

    def set_muted(self, muted: bool) -> None:
        self._syncing = True
        self.set_active(muted)
        self._syncing = False
        self._sync_icon(muted)

    def _on_toggled(self, _button) -> None:
        if self._syncing:
            return
        self._sync_icon(self.get_active())
        self._on_toggle(self.get_active())

    def _sync_icon(self, muted: bool) -> None:
        self.set_icon_name("audio-volume-muted-symbolic" if muted else "audio-volume-high-symbolic")


def _ellipsize(label: Gtk.Label) -> None:
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_xalign(0.0)


class ChoiceMenu(Gtk.MenuButton):
    """Compact menu of exclusive choices; unavailable ones are insensitive."""

    def __init__(self, on_select) -> None:
        super().__init__()
        self.add_css_class("flat")
        self._on_select = on_select

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._label = Gtk.Label()
        self._label.set_ellipsize(Pango.EllipsizeMode.END)
        self._label.set_max_width_chars(28)
        self._label.add_css_class("mixer-sub")
        content.append(self._label)
        content.append(Gtk.Image.new_from_icon_name("pan-down-symbolic"))
        self.set_child(content)

        self._popover = Gtk.Popover()
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.connect("row-activated", self._on_activated)
        self._popover.set_child(self._list)
        self.set_popover(self._popover)

    def set_choices(self, fallback_label: str, choices: list[tuple]) -> None:
        """``choices`` is a list of ``(key, label, available, active)``."""
        while (child := self._list.get_first_child()) is not None:
            self._list.remove(child)

        active_label: str | None = None
        for key, label, available, active in choices:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            text = Gtk.Label(label=label, xalign=0)
            text.set_hexpand(True)
            check = Gtk.Image.new_from_icon_name("object-select-symbolic")
            check.set_visible(active)
            box.append(text)
            box.append(check)
            row.set_child(box)
            row._key = key  # type: ignore[attr-defined]
            if not available:
                row.set_sensitive(False)
                text.add_css_class("mixer-sub")
            self._list.append(row)
            if active:
                active_label = label

        self._label.set_label(active_label or fallback_label)

    def _on_activated(self, _list, row) -> None:
        key = getattr(row, "_key", None)
        if key is None:
            return
        self._popover.popdown()
        self._on_select(key)


class PortSelector(ChoiceMenu):
    def __init__(self, controller, device: audio.Device) -> None:
        super().__init__(self._chosen)
        self.set_tooltip_text("Active port")
        self._controller = controller
        self._device = device
        self.update(device)

    def _chosen(self, name: str) -> None:
        self._controller.set_port(self._device, name)

    def update(self, device: audio.Device) -> None:
        self._device = device
        choices = [(p.name, p.description, p.available, p.active) for p in device.ports]
        self.set_choices(device.active_port_description or "Port", choices)


class ProfileSelector(ChoiceMenu):
    def __init__(self, controller, card: audio.Card) -> None:
        super().__init__(self._chosen)
        self.set_tooltip_text("Card profile")
        self._controller = controller
        self._card = card
        self.update(card)

    def _chosen(self, name: str) -> None:
        self._controller.set_card_profile(self._card, name)

    def update(self, card: audio.Card) -> None:
        self._card = card
        choices = [(p.name, p.description, p.available, p.active) for p in card.profiles]
        self.set_choices(card.active_profile_description or "Profile", choices)


class DeviceRow(Gtk.Box):
    def __init__(self, controller, device: audio.Device) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("mixer-row")
        self._controller = controller
        self._device = device

        icon_name = "audio-speakers-symbolic" if device.kind == "sink" else "audio-input-microphone-symbolic"
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(22)
        self.append(icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        self._name = Gtk.Label(label=device.description)
        self._name.add_css_class("mixer-device-name")
        self._name.set_tooltip_text(device.name)
        _ellipsize(self._name)
        self._sub = Gtk.Label(label=device.active_port_description or device.subtitle)
        self._sub.add_css_class("mixer-sub")
        _ellipsize(self._sub)
        text.append(self._name)
        text.append(self._sub)
        self.append(text)

        self._ports: PortSelector | None = None
        if device.has_port_choice:
            self._ports = PortSelector(controller, device)
            self._ports.set_valign(Gtk.Align.CENTER)
            self.append(self._ports)

        self._badge = Gtk.Label(label="Default")
        self._badge.add_css_class("mixer-badge")
        self._badge.set_valign(Gtk.Align.CENTER)
        self.append(self._badge)

        self._default_button = Gtk.Button(label="Set default")
        self._default_button.add_css_class("flat")
        self._default_button.set_valign(Gtk.Align.CENTER)
        self._default_button.connect("clicked", lambda *_: self._controller.set_default(self._device))
        self.append(self._default_button)

        self._mute = _MuteButton(lambda muted: self._controller.set_mute(self._device, muted))
        self._mute.set_valign(Gtk.Align.CENTER)
        self.append(self._mute)

        self._volume = VolumeControl(lambda percent: self._controller.set_volume(self._device, percent))
        self.append(self._volume)

        self.update(device)

    def update(self, device: audio.Device) -> None:
        self._device = device
        self._name.set_label(device.description)
        self._name.set_tooltip_text(device.name)
        self._sub.set_label(device.active_port_description or device.subtitle)
        self._volume.set_value(device.volume)
        self._mute.set_muted(device.muted)
        self._badge.set_visible(device.is_default)
        self._default_button.set_visible(not device.is_default)
        if self._ports is not None:
            self._ports.update(device)


class CardRow(Gtk.Box):
    def __init__(self, controller, card: audio.Card) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("mixer-row")
        self._controller = controller
        self._card = card

        icon = Gtk.Image.new_from_icon_name("audio-card-symbolic")
        icon.set_pixel_size(22)
        self.append(icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        self._name = Gtk.Label(label=card.description)
        self._name.add_css_class("mixer-device-name")
        self._name.set_tooltip_text(card.name)
        _ellipsize(self._name)
        self._sub = Gtk.Label(label=card.active_profile_description)
        self._sub.add_css_class("mixer-sub")
        _ellipsize(self._sub)
        text.append(self._name)
        text.append(self._sub)
        self.append(text)

        self._profiles: ProfileSelector | None = (
            ProfileSelector(controller, card) if card.profiles else None
        )
        if self._profiles is not None:
            self._profiles.set_valign(Gtk.Align.CENTER)
            self.append(self._profiles)

        self.update(card)

    def update(self, card: audio.Card) -> None:
        self._card = card
        self._name.set_label(card.description)
        self._name.set_tooltip_text(card.name)
        self._sub.set_label(card.active_profile_description)
        if self._profiles is not None:
            self._profiles.update(card)


class StreamRow(Gtk.Box):
    def __init__(self, controller, stream: audio.Stream, targets: list[audio.Device]) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("mixer-row")
        self._controller = controller
        self._stream = stream
        self._targets = targets
        self._syncing = False

        self._icon = Gtk.Image.new_from_icon_name(stream.icon)
        self._icon.set_pixel_size(22)
        self.append(self._icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        self._app = Gtk.Label(label=stream.app)
        self._app.add_css_class("mixer-device-name")
        _ellipsize(self._app)
        self._media = Gtk.Label(label=stream.media or stream.kind)
        self._media.add_css_class("mixer-sub")
        _ellipsize(self._media)
        text.append(self._app)
        text.append(self._media)
        self.append(text)

        self._dropdown: Gtk.DropDown | None = None
        self._target_index: list[int] = []
        if targets:
            model = Gtk.StringList()
            for device in targets:
                model.append(device.description)
            self._target_index = [device.index for device in targets]
            self._dropdown = Gtk.DropDown(model=model)
            self._dropdown.set_valign(Gtk.Align.CENTER)
            self._dropdown.set_tooltip_text("Route to")
            try:
                selected = self._target_index.index(stream.device_index)
            except ValueError:
                selected = Gtk.INVALID_LIST_POSITION
            self._dropdown.set_selected(selected)
            self._dropdown.connect("notify::selected", self._on_route)
            self.append(self._dropdown)

        self._mute = _MuteButton(lambda muted: self._controller.set_mute(self._stream, muted))
        self._mute.set_valign(Gtk.Align.CENTER)
        self.append(self._mute)

        self._volume = VolumeControl(lambda percent: self._controller.set_volume(self._stream, percent))
        self.append(self._volume)

        self._mute.set_muted(stream.muted)
        self._volume.set_value(stream.volume)

    def update(self, stream: audio.Stream, targets: list[audio.Device]) -> None:
        self._stream = stream
        self._app.set_label(stream.app)
        self._media.set_label(stream.media or stream.kind)
        self._icon.set_from_icon_name(stream.icon)
        self._mute.set_muted(stream.muted)
        self._volume.set_value(stream.volume)

        if self._dropdown is None:
            return
        indices = [device.index for device in targets]
        if indices != self._target_index:
            self._target_index = indices
            model = Gtk.StringList()
            for device in targets:
                model.append(device.description)
            self._syncing = True
            self._dropdown.set_model(model)
            self._syncing = False
        try:
            selected = self._target_index.index(stream.device_index)
        except ValueError:
            selected = Gtk.INVALID_LIST_POSITION
        self._syncing = True
        self._dropdown.set_selected(selected)
        self._syncing = False

    def _on_route(self, dropdown, _param) -> None:
        if self._syncing:
            return
        selected = dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION or selected >= len(self._target_index):
            return
        self._controller.move_stream(self._stream, self._target_index[selected])
