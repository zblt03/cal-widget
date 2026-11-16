"""The "Start with Windows" option: an entry in the current user's Run registry key.

Windows starts every program listed under
``HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`` when
the user signs in. It needs no admin rights and shows up in Task Manager's
"Startup apps" tab, where it can also be disabled.
"""

from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "cal-widget"


def launch_command() -> str:
    """The command line Windows should run at sign-in.

    For the packaged .exe that is the exe itself. When running from source it
    is ``pythonw.exe -m cal_widget`` (pythonw, so no console window appears).
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" -m cal_widget'


def is_enabled(key_path: str = RUN_KEY) -> bool:
    """True if our Run entry exists."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool, key_path: str = RUN_KEY) -> None:
    """Add or remove our Run entry. Raises OSError if the registry refuses."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
            log.info("Enabled start with Windows")
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass  # already off
            log.info("Disabled start with Windows")
