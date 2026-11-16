"""Filesystem locations used by the app.

User data (OAuth token, event cache, config, logs) lives in
``%LOCALAPPDATA%\\cal-widget\\`` so it never ends up inside the git repo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "cal-widget"


def data_dir() -> Path:
    """Return the per-user data directory, creating it if needed."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def token_path() -> Path:
    """Path of the stored OAuth token (refresh + access token)."""
    return data_dir() / "token.json"


def cache_path() -> Path:
    """Path of the cache holding the last successful event fetch."""
    return data_dir() / "events.cache.json"


def config_path() -> Path:
    """Path of the user-editable configuration file."""
    return data_dir() / "config.json"


def log_path() -> Path:
    """Path of the rotating log file."""
    return data_dir() / "cal-widget.log"


def app_dir() -> Path:
    """Directory that holds the program itself.

    When frozen by PyInstaller this is the folder containing the .exe;
    when running from source it is the project root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def credentials_candidates() -> list[Path]:
    """Places where ``credentials.json`` is looked for, in priority order."""
    return [data_dir() / "credentials.json", app_dir() / "credentials.json"]
