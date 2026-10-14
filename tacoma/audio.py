"""PipeWire / PulseAudio control via ``pactl``.

Everything is read from ``pactl --format=json list ...`` and changed with the
regular ``pactl`` control commands. Live updates come from ``pactl subscribe``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

PACTL = "pactl"
_UNITS = 65536.0  # 100% in pactl's internal scale


class AudioError(Exception):
    pass


def available() -> bool:
    return shutil.which(PACTL) is not None


def _run(args: list[str], timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(
            [PACTL, *args], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioError(str(exc)) from exc
    if proc.returncode != 0:
        raise AudioError(proc.stderr.strip() or f"pactl {' '.join(args)} failed")
    return proc.stdout


def _json(args: list[str]):
    try:
        return json.loads(_run(["--format=json", *args]))
    except json.JSONDecodeError as exc:
        raise AudioError(f"unexpected pactl output: {exc}") from exc


def _percent(volume) -> int:
    if not isinstance(volume, dict):
        return 0
    if isinstance(volume.get("value"), (int, float)):
        values = [float(volume["value"])]
    else:
        values = [
            float(ch["value"])
            for ch in volume.values()
            if isinstance(ch, dict) and isinstance(ch.get("value"), (int, float))
        ]
    if not values:
        return 0
    return round(sum(values) / len(values) / _UNITS * 100)


def default_names() -> tuple[str, str]:
    """(default sink name, default source name), best effort."""
    def one(kind: str) -> str:
        try:
            return _run([f"get-default-{kind}"]).strip()
        except AudioError:
            return ""

    return one("sink"), one("source")


@dataclass
class Port:
    name: str
    description: str
    available: bool
    active: bool


@dataclass
class Device:
    index: int
    name: str
    description: str
    kind: str  # "sink" | "source"
    is_default: bool
    muted: bool
    volume: int
    ports: list["Port"] = field(default_factory=list)

    @property
    def subtitle(self) -> str:
        return self.name

    @property
    def active_port_description(self) -> str:
        for port in self.ports:
            if port.active:
                return port.description
        return ""

    @property
    def has_port_choice(self) -> bool:
        return len(self.ports) > 1


@dataclass
class Stream:
    index: int
    app: str
    media: str
    icon: str
    kind: str  # "sink-input" | "source-output"
    device_index: int
    muted: bool
    volume: int


@dataclass
class Profile:
    name: str
    description: str
    available: bool
    active: bool


@dataclass
class Card:
    index: int
    name: str
    description: str
    active_profile: str
    profiles: list["Profile"] = field(default_factory=list)

    @property
    def active_profile_description(self) -> str:
        for profile in self.profiles:
            if profile.active:
                return profile.description
        return self.active_profile


def _ports(raw: dict) -> list[Port]:
    active = raw.get("active_port")
    ports: list[Port] = []
    for entry in raw.get("ports") or []:
        name = entry.get("name", "")
        availability = str(entry.get("availability", "")).strip().lower()
        ports.append(
            Port(
                name=name,
                description=entry.get("description") or name,
                available=availability != "not available",
                active=name == active,
            )
        )
    return ports


def _device(raw: dict, kind: str, default_name: str) -> Device:
    return Device(
        index=int(raw.get("index", -1)),
        name=raw.get("name", ""),
        description=raw.get("description") or raw.get("name", ""),
        kind=kind,
        is_default=raw.get("name", "") == default_name,
        muted=bool(raw.get("mute", False)),
        volume=_percent(raw.get("volume")),
        ports=_ports(raw),
    )


def _stream(raw: dict, kind: str) -> Stream:
    props = raw.get("properties", {}) or {}
    app = props.get("application.name") or props.get("application.process.binary") or "Unknown application"
    device_key = "sink" if kind == "sink-input" else "source"
    return Stream(
        index=int(raw.get("index", -1)),
        app=app,
        media=props.get("media.name", ""),
        icon=props.get("application.icon_name", "") or "application-x-executable",
        kind=kind,
        device_index=int(raw.get(device_key, -1)),
        muted=bool(raw.get("mute", False)),
        volume=_percent(raw.get("volume")),
    )


def sinks(default_name: str = "") -> list[Device]:
    if not default_name:
        default_name = default_names()[0]
    return [_device(r, "sink", default_name) for r in _json(["list", "sinks"])]


def sources(default_name: str = "") -> list[Device]:
    if not default_name:
        default_name = default_names()[1]
    return [_device(r, "source", default_name) for r in _json(["list", "sources"])]


def playback_streams() -> list[Stream]:
    return [_stream(r, "sink-input") for r in _json(["list", "sink-inputs"])]


def recording_streams() -> list[Stream]:
    return [_stream(r, "source-output") for r in _json(["list", "source-outputs"])]


def cards() -> list[Card]:
    """Sound cards and their profiles (a card-level control, not per-sink)."""
    result: list[Card] = []
    for raw in _json(["list", "cards"]):
        properties = raw.get("properties") or {}
        active = raw.get("active_profile") or ""
        profiles: list[Profile] = []
        for name, info in (raw.get("profiles") or {}).items():
            info = info or {}
            availability = str(info.get("availability") or "").strip().lower()
            profiles.append(
                Profile(
                    name=name,
                    description=info.get("description") or name,
                    available=availability != "not available",
                    active=name == active,
                )
            )
        result.append(
            Card(
                index=int(raw.get("index", -1)),
                name=raw.get("name", ""),
                description=properties.get("device.description") or raw.get("name", ""),
                active_profile=active,
                profiles=profiles,
            )
        )
    return result


# -- control ---------------------------------------------------------------- #
def set_volume(kind: str, index: int, percent: int) -> None:
    _run([f"set-{kind}-volume", str(index), f"{percent}%"])


def set_mute(kind: str, index: int, muted: bool) -> None:
    _run([f"set-{kind}-mute", str(index), "1" if muted else "0"])


def set_default(kind: str, name: str) -> None:
    _run([f"set-default-{kind}", name])


def set_port(kind: str, index: int, port_name: str) -> None:
    _run([f"set-{kind}-port", str(index), port_name])


def set_card_profile(card_name: str, profile_name: str) -> None:
    _run(["set-card-profile", card_name, profile_name])


def move_stream(kind: str, index: int, device_index: int) -> None:
    _run([f"move-{kind}", str(index), str(device_index)])


class Watcher:
    """Runs ``pactl subscribe`` and calls ``on_change`` on each event line."""

    def __init__(self, on_change) -> None:
        self._on_change = on_change
        self._proc: Gio.Subprocess | None = None
        self._stream: Gio.DataInputStream | None = None

    @property
    def running(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self.running or not available():
            return
        try:
            self._proc = Gio.Subprocess.new(
                [PACTL, "subscribe"], Gio.SubprocessFlags.STDOUT_PIPE
            )
        except GLib.Error:
            return
        stdout = self._proc.get_stdout_pipe()
        if stdout is None:
            return
        self._stream = Gio.DataInputStream.new(stdout)
        self._read()

    def stop(self) -> None:
        self._stream = None
        if self._proc is not None:
            try:
                self._proc.force_exit()
            except GLib.Error:
                pass
            self._proc = None

    def _read(self) -> None:
        if self._stream is None:
            return
        self._stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def _on_line(self, stream, result) -> None:
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:
            self._stream = None
            return
        self._on_change()
        self._read()
