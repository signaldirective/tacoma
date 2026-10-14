"""Main window: sections for output/input devices and playback/recording streams."""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import audio  # noqa: E402
from .rows import CardRow, DeviceRow, StreamRow  # noqa: E402

_REFRESH_DEBOUNCE_MS = 200
_WRITE_QUIET_S = 0.8  # ignore watcher churn briefly after we change something

_SECTIONS = (
    ("sink", "Output devices"),
    ("source", "Input devices"),
    ("sink-input", "Playback"),
    ("source-output", "Recording"),
    ("card", "Sound cards"),
)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, theme, **kwargs) -> None:
        super().__init__(**kwargs)
        self._theme = theme
        self._last_write = 0.0
        self._refresh_source = 0
        self._sinks: list[audio.Device] = []
        self._sources: list[audio.Device] = []
        self._rows: dict[str, list[Gtk.Widget]] = {}
        self._placeholders: dict[str, Gtk.Label | None] = {}

        self.set_title("Audio")
        self.set_default_size(820, 760)
        self._build()
        self.reload()
        self._watcher = audio.Watcher(self._schedule_refresh)
        self._watcher.start()

    # -- construction ----------------------------------------------------- #
    def _build(self) -> None:
        header = Gtk.HeaderBar()
        title = Gtk.Label(label="Audio")
        title.add_css_class("title")
        header.set_title_widget(title)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text("Refresh")
        refresh.connect("clicked", lambda *_: self.reload())
        header.pack_start(refresh)

        menu = Gio.Menu()
        menu.append("Refresh", "app.refresh")
        menu.append("Refresh theme", "app.refresh-theme")
        menu.append("About", "app.about")
        menu.append("Quit", "app.quit")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        self.set_titlebar(header)

        self._banner = Gtk.Label(xalign=0, wrap=True, visible=False)
        self._banner.add_css_class("mixer-empty")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.append(self._banner)

        self._sections: dict[str, Gtk.Box] = {}
        for key, heading in _SECTIONS:
            outer.append(self._section_header(heading))
            container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self._sections[key] = container
            outer.append(container)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(outer)
        self.set_child(scroller)

    def _section_header(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("mixer-section-title")
        label.set_margin_top(10)
        label.set_margin_start(12)
        return label

    # -- data ------------------------------------------------------------- #
    def reload(self) -> None:
        if not audio.available():
            self._show_error("pactl was not found. Install pipewire-pulse.")
            return
        try:
            default_sink, default_source = audio.default_names()
            self._sinks = audio.sinks(default_sink)
            self._sources = audio.sources(default_source)
            playback = audio.playback_streams()
            recording = audio.recording_streams()
            cards = audio.cards()
        except audio.AudioError as exc:
            self._show_error(str(exc))
            return

        self._hide_error()
        self._sync(
            "sink",
            self._sinks,
            lambda d: DeviceRow(self, d),
            lambda w, d: w.update(d),
            "No output devices",
        )
        self._sync(
            "source",
            self._sources,
            lambda d: DeviceRow(self, d),
            lambda w, d: w.update(d),
            "No input devices",
        )
        self._sync(
            "sink-input",
            playback,
            lambda s: StreamRow(self, s, self._sinks),
            lambda w, s: w.update(s, self._sinks),
            "Nothing is playing",
        )
        self._sync(
            "source-output",
            recording,
            lambda s: StreamRow(self, s, self._sources),
            lambda w, s: w.update(s, self._sources),
            "Nothing is recording",
        )
        self._sync(
            "card",
            cards,
            lambda c: CardRow(self, c),
            lambda w, c: w.update(c),
            "No sound cards",
        )

    def _sync(self, key, items, make_row, update_row, empty_text: str) -> None:
        """Reconcile a section in place so the scroll position survives refresh."""
        container = self._sections[key]
        rows = self._rows.setdefault(key, [])
        placeholder = self._placeholders.get(key)

        if not items:
            for widget in rows:
                container.remove(widget)
            rows.clear()
            if placeholder is None:
                label = Gtk.Label(label=empty_text, xalign=0)
                label.add_css_class("mixer-empty")
                container.append(label)
                self._placeholders[key] = label
            return

        if placeholder is not None:
            container.remove(placeholder)
            self._placeholders[key] = None

        while len(rows) < len(items):
            widget = make_row(items[len(rows)])
            container.append(widget)
            rows.append(widget)

        for widget, item in zip(rows, items):
            update_row(widget, item)

        if len(rows) > len(items):
            for widget in rows[len(items):]:
                container.remove(widget)
            del rows[len(items):]

    # -- watcher ---------------------------------------------------------- #
    def _schedule_refresh(self) -> None:
        if self._refresh_source:
            return
        self._refresh_source = GLib.timeout_add(_REFRESH_DEBOUNCE_MS, self._do_refresh)

    def _do_refresh(self) -> bool:
        self._refresh_source = 0
        if time.monotonic() - self._last_write < _WRITE_QUIET_S:
            self._refresh_source = GLib.timeout_add(_REFRESH_DEBOUNCE_MS, self._do_refresh)
            return GLib.SOURCE_REMOVE
        self.reload()
        return GLib.SOURCE_REMOVE

    def _guard(self) -> None:
        self._last_write = time.monotonic()

    # -- control ---------------------------------------------------------- #
    def set_volume(self, item, percent: int) -> None:
        self._guard()
        try:
            audio.set_volume(item.kind, item.index, percent)
        except audio.AudioError as exc:
            self._show_error(str(exc))

    def set_mute(self, item, muted: bool) -> None:
        self._guard()
        try:
            audio.set_mute(item.kind, item.index, muted)
        except audio.AudioError as exc:
            self._show_error(str(exc))

    def set_default(self, device: audio.Device) -> None:
        self._guard()
        try:
            audio.set_default(device.kind, device.name)
        except audio.AudioError as exc:
            self._show_error(str(exc))
        self.reload()

    def set_port(self, device: audio.Device, port_name: str) -> None:
        self._guard()
        try:
            audio.set_port(device.kind, device.index, port_name)
        except audio.AudioError as exc:
            self._show_error(str(exc))
        self.reload()

    def set_card_profile(self, card: audio.Card, profile_name: str) -> None:
        self._guard()
        try:
            audio.set_card_profile(card.name, profile_name)
        except audio.AudioError as exc:
            self._show_error(str(exc))
        self.reload()

    def move_stream(self, stream: audio.Stream, device_index: int) -> None:
        self._guard()
        try:
            audio.move_stream(stream.kind, stream.index, device_index)
        except audio.AudioError as exc:
            self._show_error(str(exc))

    # -- banner ----------------------------------------------------------- #
    def _show_error(self, text: str) -> None:
        self._banner.set_label(text)
        self._banner.set_visible(True)

    def _hide_error(self) -> None:
        self._banner.set_visible(False)
