"""User configuration (config.json): defaults, loading and validation.

The file lives in ``%LOCALAPPDATA%\\cal-widget\\config.json`` and is created
with the defaults on first run. Every field is validated on its own: a bad
value falls back to its default (and the log says why) without throwing away
the rest of the file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    """All user-tunable settings, with their defaults."""

    refresh_minutes: int = 5  # how often to ask Google for events
    show_tomorrow: bool = True  # show tomorrow's first event when today is done
    bar_uses_calendar_color: bool = False  # bar in the calendar's colour instead of white
    max_title_chars: int = 40  # longer titles are cut with "…"
    excluded_calendars: list[str] = field(default_factory=list)  # names or IDs to skip


# Allowed ranges for the integer settings (inclusive).
INT_RANGES: dict[str, tuple[int, int]] = {
    "refresh_minutes": (1, 120),
    "max_title_chars": (5, 200),
}


def _validate(name: str, value: Any, default: Any) -> Any:
    """Return ``value`` if it is valid for setting ``name``, else ``default``."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        log.warning("config: %s must be true or false; using %s", name, json.dumps(default))
        return default

    if isinstance(default, int):
        low, high = INT_RANGES[name]
        # bool is a subclass of int in Python, so rule it out explicitly.
        if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
            return value
        log.warning("config: %s must be a whole number from %d to %d; using %d", name, low, high, default)
        return default

    if isinstance(default, list):
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value
        log.warning("config: %s must be a list of strings; using []", name)
        return default

    raise TypeError(f"no validation rule for setting {name!r}")


def parse_config(data: Any) -> Config:
    """Build a Config from decoded JSON, replacing invalid values by defaults."""
    defaults = Config()
    if not isinstance(data, dict):
        log.warning("config: expected a JSON object; using all defaults")
        return defaults

    known = {f.name for f in fields(Config)}
    for unknown in sorted(set(data) - known):
        log.warning("config: unknown setting %r is ignored", unknown)

    values = {}
    for f in fields(Config):
        default = getattr(defaults, f.name)
        values[f.name] = _validate(f.name, data[f.name], default) if f.name in data else default
    return Config(**values)


def save_config(config: Config, path: Path) -> None:
    """Write the config as pretty-printed JSON."""
    path.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")


def load_config(path: Path) -> Config:
    """Read config.json, creating it with the defaults if it does not exist.

    A file that cannot be parsed is left untouched (so the user's edits are
    not lost) and the defaults are used until it is fixed.
    """
    if not path.exists():
        config = Config()
        try:
            save_config(config, path)
            log.info("Created %s with default settings", path)
        except OSError:
            log.exception("Could not create %s", path)
        return config

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("config: cannot read %s (%s); using defaults", path, exc)
        return Config()
    return parse_config(data)
