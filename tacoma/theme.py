"""Apply Omarchy palette accents to the app's own widget classes."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import omarchy  # noqa: E402

# Above GTK's own theme/user providers, so our freshly re-read copy wins over
# the stale parse GTK is holding.
_DISK_PRIORITY = Gtk.STYLE_PROVIDER_PRIORITY_USER + 50
_WATCH_DEBOUNCE_MS = 350

_CSS = """\
.mixer-section-title {{ font-weight: 700; font-size: 0.95em; opacity: 0.85; }}
.mixer-device-name {{ font-weight: 600; }}
.mixer-sub {{ opacity: 0.6; font-size: 0.9em; }}
.mixer-badge {{
  background-color: {accent};
  color: {on_accent};
  border-radius: 6px;
  padding: 1px 7px;
  font-size: 0.78em;
  font-weight: 700;
}}
.mixer-percent {{ opacity: 0.7; font-variant-numeric: tabular-nums; }}
.mixer-row {{ padding: 8px 12px; }}
.mixer-empty {{ opacity: 0.55; padding: 6px 14px 12px 14px; }}
"""


def _hex(value: str | None, default: str) -> str:
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        try:
            int(value[1:], 16)
        except ValueError:
            return default
        return value
    return default


def _contrast(hex_color: str) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return "#000000" if (r + g + b) / 3 > 140 else "#ffffff"


class ThemeManager:
    def __init__(self) -> None:
        self.palette: dict[str, str] | None = None
        self._provider = Gtk.CssProvider()
        self._disk_providers: list[Gtk.CssProvider] = []
        self._monitors: list[Gio.FileMonitor] = []
        self._watch_timeout = 0

    def install(self) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        self._load_css()

    def refresh(self) -> None:
        """Re-read the palette and the GTK theme from disk.

        GTK loads the named theme once and caches the parse; Omarchy rebuilds
        those files in place under the same name, so GTK never re-reads them.
        We therefore re-load the theme CSS ourselves into a provider we control.
        """
        self._apply_dark_preference()
        self._load_css()
        self._reload_disk_theme()

    def _load_css(self) -> None:
        self.palette = omarchy.palette()
        accent = _hex((self.palette or {}).get("accent"), "#3584e4")
        css = _CSS.format(accent=accent, on_accent=_contrast(accent))
        try:
            self._provider.load_from_string(css)
        except (AttributeError, TypeError):
            self._provider.load_from_data(css, -1)

    def _is_dark(self) -> bool:
        value = omarchy.gtk_settings().get("gtk-application-prefer-dark-theme")
        if value is not None:
            return value.strip().lower() in ("1", "true", "yes")
        settings = Gtk.Settings.get_default()
        return bool(settings.get_property("gtk-application-prefer-dark-theme")) if settings else False

    def _apply_dark_preference(self) -> None:
        settings = Gtk.Settings.get_default()
        value = omarchy.gtk_settings().get("gtk-application-prefer-dark-theme")
        if settings is not None and value is not None:
            settings.set_property(
                "gtk-application-prefer-dark-theme",
                value.strip().lower() in ("1", "true", "yes"),
            )

    def _reload_disk_theme(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        for provider in self._disk_providers:
            Gtk.StyleContext.remove_provider_for_display(display, provider)
        self._disk_providers = []

        for path in omarchy.gtk_css_files(self._is_dark()):
            provider = Gtk.CssProvider()
            try:
                provider.load_from_path(str(path))
            except GLib.Error:
                continue
            Gtk.StyleContext.add_provider_for_display(display, provider, _DISK_PRIORITY)
            self._disk_providers.append(provider)

    # -- automatic refresh on theme switch -------------------------------- #
    def start_watching(self) -> None:
        self._arm_monitors()

    def _watch_dirs(self) -> list[Path]:
        dirs = [omarchy.gtk_config_dir(), omarchy.watch_path()]
        for path in omarchy.gtk_css_files(self._is_dark()):
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            dirs.append(resolved.parent)
        seen: set[Path] = set()
        out: list[Path] = []
        for directory in dirs:
            if directory.is_dir() and directory not in seen:
                seen.add(directory)
                out.append(directory)
        return out

    def _arm_monitors(self) -> None:
        for monitor in self._monitors:
            monitor.cancel()
        self._monitors = []
        for directory in self._watch_dirs():
            try:
                monitor = Gio.File.new_for_path(str(directory)).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None
                )
            except GLib.Error:
                continue
            monitor.connect("changed", self._on_theme_fs_event)
            self._monitors.append(monitor)

    def _on_theme_fs_event(self, *_args) -> None:
        if self._watch_timeout:
            return
        self._watch_timeout = GLib.timeout_add(_WATCH_DEBOUNCE_MS, self._do_watch_refresh)

    def _do_watch_refresh(self) -> bool:
        self._watch_timeout = 0
        self.refresh()
        self._arm_monitors()
        return GLib.SOURCE_REMOVE
