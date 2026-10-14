"""Gtk.Application for the Omarchy mixer."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import omarchy  # noqa: E402
from .theme import ThemeManager  # noqa: E402
from .window import MainWindow  # noqa: E402

APP_ID = "dev.omarchy.mixer"
APP_NAME = "TACOMA"
APP_VERSION = "0.1.0"
APP_ICON = "audio-volume-high"


class MixerApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._theme = ThemeManager()
        self._window: MainWindow | None = None

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self._theme.install()
        self._theme.start_watching()

        for name, handler in (
            ("refresh", lambda *_: self._window_call("reload")),
            ("refresh-theme", lambda *_: self._theme.refresh()),
            ("about", self._on_about),
            ("quit", lambda *_: self.quit()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        self.set_accels_for_action("app.refresh", ["<Primary>r"])
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(self._theme, application=self)
        self._window.present()

    def _window_call(self, method: str) -> None:
        if self._window is not None:
            getattr(self._window, method)()

    def _on_about(self, *_args) -> None:
        theme = omarchy.read()
        mode = (self._theme.palette or {}).get("mode", "unknown")
        dialog = Gtk.AboutDialog(
            program_name=APP_NAME,
            version=APP_VERSION,
            comments=(
                "TACOMA \u2014 Theme Aware Comprehensive Omarchy Mixer Application.\n"
                f"Theme: {theme.name} (mode: {mode})."
            ),
            logo_icon_name=APP_ICON,
            modal=True,
            transient_for=self._window,
        )
        dialog.present()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    rest = argv[1:]

    if "--version" in rest:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if "-h" in rest or "--help" in rest:
        print(f"{APP_NAME} {APP_VERSION}")
        print()
        print("A native PipeWire/PulseAudio mixer for Omarchy.")
        print()
        print("Usage: tacoma [--version] [--help]")
        return 0

    GLib.set_application_name(APP_NAME)
    application = MixerApp()
    return application.run(argv)
