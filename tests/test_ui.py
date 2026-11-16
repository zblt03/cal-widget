"""Headless smoke tests for the widget and the tooltip text."""

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cal_widget.app import build_tooltip  # noqa: E402
from cal_widget.events import Event  # noqa: E402
from cal_widget.ui import MAX_WIDTH, CalendarWidget  # noqa: E402

MADRID = timezone(timedelta(hours=1))


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_width_grows_with_text_and_is_capped(qt_app: QApplication) -> None:
    widget = CalendarWidget()
    widget.set_content("19:30–20:30", "Gym")
    short = widget.preferred_width()
    widget.set_content("19:30–20:30", "A very long event title " * 10)
    assert short < widget.preferred_width() == MAX_WIDTH


def test_tooltip_has_title_time_and_calendar() -> None:
    event = Event(
        title="Gym",
        start=datetime(2026, 11, 16, 19, 30, tzinfo=MADRID),
        end=datetime(2026, 11, 16, 20, 30, tzinfo=MADRID),
        calendar_name="Routine",
    )
    now = datetime(2026, 11, 16, 15, 0, tzinfo=MADRID)
    assert build_tooltip(event, now) == "Gym\nMon 16 Nov · 19:30–20:30\nRoutine"
