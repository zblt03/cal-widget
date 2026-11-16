"""Controller tests: offline behaviour, cache and wake-up, with Google mocked out."""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cal_widget import app as app_module  # noqa: E402
from cal_widget import calendar_client, paths  # noqa: E402
from cal_widget.app import App, State  # noqa: E402
from cal_widget.events import Event  # noqa: E402


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path / "cal-widget"


def upcoming_event() -> Event:
    start = datetime.now().astimezone() + timedelta(minutes=30)
    return Event(title="Gym", start=start, end=start + timedelta(hours=1))


def make_app(monkeypatch: pytest.MonkeyPatch, fetch_result: list[Event] | Exception) -> App:
    """An overlay-mode App whose Google calls return ``fetch_result`` (or raise it)."""

    def fake_fetch(creds: object, now: datetime) -> list[Event]:
        if isinstance(fetch_result, Exception):
            raise fetch_result
        return fetch_result

    monkeypatch.setattr(app_module.auth, "get_credentials", lambda allow_login=False: object())
    monkeypatch.setattr(app_module.calendar_client, "fetch_events", fake_fetch)
    return App(embed=False)


def test_cache_is_shown_at_startup(qt_app: QApplication, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calendar_client.save_cache([upcoming_event()], paths.cache_path())
    app = make_app(monkeypatch, [])
    assert app.state is State.READY
    app.update_display()  # what start() does before the first fetch returns
    assert app.widget._heading == "Gym"


def test_success_writes_cache(qt_app: QApplication, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = upcoming_event()
    app = make_app(monkeypatch, [event])
    app._worker(allow_login=False)  # runs synchronously; signals deliver directly
    assert app.state is State.READY
    assert not app.stale
    assert calendar_client.load_cache(paths.cache_path()) == [event]


def test_offline_with_events_dims_them(qt_app: QApplication, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calendar_client.save_cache([upcoming_event()], paths.cache_path())
    app = make_app(monkeypatch, ConnectionError("offline"))
    app._worker(allow_login=False)
    assert app.state is State.READY
    assert app.stale
    assert app.widget._dimmed
    assert app._refresh_timer.interval() == app_module.RETRY_INTERVAL_MS


def test_offline_without_events_shows_error(qt_app: QApplication, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app(monkeypatch, ConnectionError("offline"))
    app._worker(allow_login=False)
    assert app.state is State.ERROR


def test_back_online_clears_dimming(qt_app: QApplication, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app(monkeypatch, ConnectionError("offline"))
    app.events = [upcoming_event()]
    app._worker(allow_login=False)
    assert app.stale
    monkeypatch.setattr(app_module.calendar_client, "fetch_events", lambda creds, now: [upcoming_event()])
    app._worker(allow_login=False)
    assert not app.stale
    assert not app.widget._dimmed
    assert app._refresh_timer.interval() == app_module.REFRESH_INTERVAL_MS


def test_long_gap_between_ticks_means_wake_up(qt_app: QApplication, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app(monkeypatch, [])
    refreshes: list[bool] = []
    monkeypatch.setattr(app, "refresh", lambda: refreshes.append(True))

    app._last_tick = time.time() - 10  # normal tick: no refresh
    app._on_reselect_tick()
    assert refreshes == []

    app._last_tick = time.time() - 3600  # slept for an hour
    app._on_reselect_tick()
    assert refreshes == [True]
