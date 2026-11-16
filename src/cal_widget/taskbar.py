"""Win32 helpers (via ctypes): taskbar geometry, topmost, fullscreen detection.

All rectangles returned by Win32 are in *physical* pixels, because Qt makes
the process per-monitor DPI aware. ``widget_rect`` converts them to Qt's
*logical* pixels.
"""

from __future__ import annotations

import ctypes
import logging
import winreg
from ctypes import wintypes
from dataclasses import dataclass
from enum import IntEnum

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


# --- Win32 structures and constants -----------------------------------------


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", RECT),
        ("lParam", wintypes.LPARAM),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


ABM_GETTASKBARPOS = 5
MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTOPRIMARY = 1
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200

# Declaring argument types keeps 64-bit handles from being truncated.
shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
shell32.SHAppBarMessage.restype = ctypes.c_size_t
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetShellWindow.restype = wintypes.HWND
user32.GetDesktopWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]


# --- Plain data types (no Win32) ---------------------------------------------


class Edge(IntEnum):
    """Screen edge the taskbar is docked to (values match ABE_* constants)."""

    LEFT = 0
    TOP = 1
    RIGHT = 2
    BOTTOM = 3


@dataclass(frozen=True)
class Rect:
    """An integer rectangle given by its edges (right/bottom exclusive)."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class TaskbarInfo:
    """Primary taskbar position in physical pixels."""

    rect: Rect
    edge: Edge


def widget_rect(
    taskbar: Rect,
    edge: Edge,
    scale: float,
    width: int,
    padding: int = 8,
    vertical_height: int = 48,
) -> Rect:
    """Compute where the widget goes, in Qt logical pixels.

    Args:
        taskbar: taskbar rectangle in physical pixels (primary monitor).
        edge: which screen edge the taskbar is on.
        scale: Qt device pixel ratio of the primary screen (1.5 at 150 %).
        width: desired widget width in logical pixels.
        padding: gap from the taskbar's start, in logical pixels.
        vertical_height: widget height used when the taskbar is vertical.

    For a horizontal taskbar the widget sits at its left end and takes its
    full height. For a vertical taskbar it sits at the top and takes its
    width. The primary monitor's top-left corner is (0, 0) in both pixel
    systems, so dividing by ``scale`` is a correct conversion.
    """
    left = round(taskbar.left / scale)
    top = round(taskbar.top / scale)
    right = round(taskbar.right / scale)
    bottom = round(taskbar.bottom / scale)

    if edge in (Edge.BOTTOM, Edge.TOP):
        return Rect(left + padding, top, left + padding + width, bottom)
    return Rect(left, top + padding, right, top + padding + vertical_height)


# --- Win32 queries -------------------------------------------------------------


def get_taskbar() -> TaskbarInfo | None:
    """Return the primary taskbar's position, or None if Windows won't say."""
    data = APPBARDATA()
    data.cbSize = ctypes.sizeof(APPBARDATA)
    if not shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(data)):
        return None
    rc = data.rc
    return TaskbarInfo(Rect(rc.left, rc.top, rc.right, rc.bottom), Edge(data.uEdge))


def _read_hkcu_dword(key_path: str, name: str) -> int | None:
    """Read a DWORD from HKEY_CURRENT_USER, or None if missing."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return int(value)
    except OSError:
        return None


def taskbar_is_left_aligned() -> bool:
    """True if the Windows 11 taskbar icons are left-aligned (default: centred)."""
    value = _read_hkcu_dword(
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarAl"
    )
    return value == 0


def uses_light_theme() -> bool:
    """True if the taskbar uses the light theme (so text must be dark)."""
    value = _read_hkcu_dword(
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "SystemUsesLightTheme",
    )
    return value == 1


def set_topmost(hwnd: int) -> None:
    """Put the window back at the top of the always-on-top band without activating it.

    Clicking the taskbar raises it above other topmost windows, which would
    otherwise cover the widget until something else changes the z-order.
    """
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def is_fullscreen_app_active(own_hwnd: int) -> bool:
    """True if the foreground window covers the whole primary monitor.

    The desktop and the taskbar are ignored. Maximised windows do not count,
    because they leave the taskbar visible.
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd == own_hwnd:
        return False
    if hwnd in (user32.GetShellWindow(), user32.GetDesktopWindow()):
        return False
    if _class_name(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd"):
        return False

    primary = user32.MonitorFromPoint(wintypes.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
    if user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONULL) != primary:
        return False

    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    window = RECT()
    if not user32.GetMonitorInfoW(primary, ctypes.byref(info)):
        return False
    if not user32.GetWindowRect(hwnd, ctypes.byref(window)):
        return False

    screen = info.rcMonitor
    return (
        window.left <= screen.left
        and window.top <= screen.top
        and window.right >= screen.right
        and window.bottom >= screen.bottom
    )
