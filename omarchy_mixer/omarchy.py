"""Read the active Omarchy theme (name + palette) for accent theming.

Values come from the shared ``omarchy-theme-color`` resolver when present, with
a direct ``colors.toml`` fallback.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "omarchy" / "current"


@dataclass(frozen=True)
class ThemeInfo:
    slug: str | None
    name: str
    directory: Path

    @property
    def available(self) -> bool:
        return self.slug is not None


def read() -> ThemeInfo:
    current = _state_dir()
    slug = None
    name_file = current / "theme.name"
    if name_file.is_file():
        try:
            slug = name_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            slug = None
    if slug:
        name = re.sub(r"(^|-)([a-z])", lambda m: m.group(1) + m.group(2).upper(), slug)
        name = name.replace("-", " ")
    else:
        name = "Unknown"
    return ThemeInfo(slug=slug, name=name, directory=current / "theme")


def watch_path() -> Path:
    return _state_dir()


def _config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base) if base else Path.home() / ".config"


def gtk_config_dir() -> Path:
    return _config_home() / "gtk-4.0"


def gtk_settings() -> dict[str, str]:
    """Relevant GTK keys from ``~/.config/gtk-{4,3}.0/settings.ini``."""
    import configparser

    for version in ("4.0", "3.0"):
        ini = _config_home() / f"gtk-{version}" / "settings.ini"
        if not ini.is_file():
            continue
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(ini, encoding="utf-8")
        except (configparser.Error, OSError):
            continue
        if not parser.has_section("Settings"):
            continue
        values: dict[str, str] = {}
        for key in ("gtk-theme-name", "gtk-application-prefer-dark-theme"):
            if parser.has_option("Settings", key):
                values[key] = parser.get("Settings", key)
        return values
    return {}


def _xdg_data_home() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    return Path(base) if base else Path.home() / ".local" / "share"


def _xdg_data_dirs() -> list[Path]:
    raw = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(part) for part in raw.split(":") if part]


def gtk_css_files(dark: bool) -> list[Path]:
    """The CSS files GTK applies for the active theme, in load order.

    Omarchy (via the thpm compat plugin) writes/links the themed stylesheet into
    ``~/.config/gtk-4.0`` as well as the named theme directory. Both are
    returned so a refresh can re-read them; GTK caches the parsed theme by name
    and never touches disk again on its own.
    """
    files: list[Path] = []
    config = _config_home() / "gtk-4.0"
    for name in ("gtk.css", "gtk-dark.css") if dark else ("gtk.css",):
        path = config / name
        if path.is_file():
            files.append(path)

    if not files:
        theme = gtk_settings().get("gtk-theme-name", "")
        variant = "gtk-dark.css" if dark else "gtk.css"
        for base in (Path.home() / ".themes", _xdg_data_home() / "themes", *[d / "themes" for d in _xdg_data_dirs()]):
            candidate = base / theme / "gtk-4.0" / variant
            if theme and candidate.is_file():
                files.append(candidate)
                break

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in files:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _from_cli() -> dict[str, str] | None:
    resolver = shutil.which("omarchy-theme-color")
    if resolver is None:
        candidate = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "bin" / "omarchy-theme-color"
        if candidate.is_file():
            resolver = str(candidate)
    if resolver is None:
        return None
    try:
        proc = subprocess.run([resolver, "--all"], capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    palette: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition("\t")
        if key.strip() and value.strip():
            palette[key.strip()] = value.strip()
    return palette or None


def _from_toml() -> dict[str, str] | None:
    colors_file = read().directory / "colors.toml"
    if not colors_file.is_file():
        return None
    try:
        raw = tomllib.loads(colors_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    colors = {
        str(k).lower(): str(v).strip()
        for k, v in raw.items()
        if isinstance(v, str) and _HEX.match(str(v).strip())
    }
    if not colors:
        return None

    def pick(*keys, default):
        for key in keys:
            if key in colors:
                return colors[key]
        return default

    background = pick("background", "bg", "color0", default="#000000")
    return {
        "background": background,
        "foreground": pick("foreground", "fg", "color7", default="#ffffff"),
        "accent": pick("accent", "blue", "color4", default="#1d9bf0"),
        "muted": pick("muted", "color8", default="#888888"),
        "mode": colors.get("mode") or colors.get("theme_type") or "dark",
    }


def palette() -> dict[str, str] | None:
    return _from_cli() or _from_toml()
