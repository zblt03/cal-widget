"""Tests for the pure placement maths in cal_widget.taskbar."""

import pytest

from cal_widget.taskbar import Edge, Rect, widget_rect


@pytest.mark.parametrize(
    ("scale", "screen_w", "screen_h"),
    [(1.0, 1920, 1080), (1.25, 1920, 1080), (1.5, 1920, 1200), (2.0, 3840, 2160)],
)
def test_bottom_taskbar_at_common_scales(scale: float, screen_w: int, screen_h: int) -> None:
    bar_height = round(48 * scale)  # Windows 11 taskbar is 48 logical px tall
    taskbar = Rect(0, screen_h - bar_height, screen_w, screen_h)

    rect = widget_rect(taskbar, Edge.BOTTOM, scale, width=200, padding=8)

    assert rect.left == 8
    assert rect.width == 200
    assert rect.height == 48
    assert rect.bottom == round(screen_h / scale)


def test_top_taskbar() -> None:
    rect = widget_rect(Rect(0, 0, 1920, 48), Edge.TOP, 1.0, width=200)
    assert (rect.top, rect.bottom) == (0, 48)


def test_vertical_taskbar_uses_its_width() -> None:
    rect = widget_rect(Rect(0, 0, 60, 1080), Edge.LEFT, 1.0, width=200, padding=8)
    assert rect.left == 0
    assert rect.width == 60
    assert rect.top == 8
