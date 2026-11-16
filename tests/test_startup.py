"""Tests for cal_widget.startup, using a throwaway registry key (not the real Run key)."""

import winreg
from collections.abc import Iterator

import pytest

from cal_widget import startup

TEST_KEY = r"Software\cal-widget-tests\Run"


@pytest.fixture
def key() -> Iterator[str]:
    yield TEST_KEY
    for path in (TEST_KEY, r"Software\cal-widget-tests"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


def test_toggle_on_and_off(key: str) -> None:
    assert not startup.is_enabled(key)
    startup.set_enabled(True, key)
    assert startup.is_enabled(key)
    startup.set_enabled(False, key)
    assert not startup.is_enabled(key)


def test_disabling_twice_is_harmless(key: str) -> None:
    startup.set_enabled(False, key)
    startup.set_enabled(False, key)
    assert not startup.is_enabled(key)


def test_stored_command_runs_pythonw_from_source(key: str) -> None:
    startup.set_enabled(True, key)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
        value, _ = winreg.QueryValueEx(k, startup.VALUE_NAME)
    assert value == startup.launch_command()
    assert value.endswith('pythonw.exe" -m cal_widget')


def test_frozen_command_is_the_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", r"C:\Apps\cal-widget.exe")
    assert startup.launch_command() == r'"C:\Apps\cal-widget.exe"'
