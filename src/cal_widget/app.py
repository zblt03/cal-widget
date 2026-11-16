"""Application controller: owns the state, talks to Google, drives the widget.

Network calls run on a background thread so the UI never freezes. Results
come back through Qt signals, which Qt delivers on the UI thread.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
import time
from datetime import datetime
from enum import Enum, auto

from PySide6.QtCore import QObject, QRect, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtNetwork import QNetworkInformation
from PySide6.QtWidgets import QApplication

from cal_widget import auth, calendar_client, paths, taskbar
from cal_widget.events import Event, format_time_range, select_event
from cal_widget.ui import MAX_WIDTH, CalendarWidget

log = logging.getLogger(__name__)

CALENDAR_URL = "https://calendar.google.com/"
README_SETUP_URL = "https://github.com/zblt03/cal-widget#google-cloud-setup"
PLACEMENT_INTERVAL_MS = 2_000
TOPMOST_INTERVAL_MS = 1_000
REFRESH_INTERVAL_MS = 5 * 60_000  # normal API refresh
RETRY_INTERVAL_MS = 30_000  # API retry while the last fetch failed (offline)
RESELECT_INTERVAL_MS = 30_000  # re-run select_event, no API call
# If two 30-second ticks are this far apart, the PC must have been asleep.
SLEEP_GAP_SECONDS = 90
OFFLINE_NOTE = "Offline — showing saved events"


class State(Enum):
    """What the widget is currently able to show."""

    LOADING = auto()
    READY = auto()  # we have events (possibly stale)
    SIGN_IN = auto()  # no valid token: user must log in
    SIGNING_IN = auto()  # browser login in progress
    MISSING_CREDENTIALS = auto()  # credentials.json not found
    ERROR = auto()  # fetch failed and nothing to show


def build_tooltip(event: Event, now: datetime) -> str:
    """Tooltip text: full title, date and time, calendar name."""
    start = event.start.astimezone(now.tzinfo)
    when = f"{start:%a %d %b} · {format_time_range(event, now)}"
    return f"{event.title}\n{when}\n{event.calendar_name}"


class App(QObject):
    """Glue between Google Calendar, the selection logic and the widget."""

    # Emitted from the worker thread; Qt queues them onto the UI thread.
    _fetch_succeeded = Signal(list)
    _fetch_failed = Signal()
    _reauth_needed = Signal()
    _credentials_missing = Signal()

    def __init__(self, embed: bool = True) -> None:
        super().__init__()
        # embed=True: the widget lives *inside* the taskbar window.
        # embed=False: it floats over the taskbar as a topmost window (fallback).
        self.embed = embed
        self.widget = self._create_widget()
        self.state = State.LOADING
        self.events: list[Event] = []
        self.stale = False  # True while showing old events because fetching fails
        self._busy = False  # a fetch or login thread is running
        self._last_tick = time.time()

        cached = calendar_client.load_cache(paths.cache_path())
        if cached is not None:
            # Show the last known events straight away instead of "Loading…".
            self.events = cached
            self.state = State.READY
        self._hidden_for_fullscreen = False
        self._warned_layout: tuple[taskbar.Edge, bool] | None = None

        self._fetch_succeeded.connect(self._on_fetch_succeeded)
        self._fetch_failed.connect(self._on_fetch_failed)
        self._reauth_needed.connect(lambda: self._finish_with_state(State.SIGN_IN))
        self._credentials_missing.connect(
            lambda: self._finish_with_state(State.MISSING_CREDENTIALS)
        )

        self._placement_timer = QTimer(self, interval=PLACEMENT_INTERVAL_MS)
        self._placement_timer.timeout.connect(self.reposition)
        self._topmost_timer = QTimer(self, interval=TOPMOST_INTERVAL_MS)
        self._topmost_timer.timeout.connect(self._keep_visible)
        self._refresh_timer = QTimer(self, interval=REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.refresh)
        self._reselect_timer = QTimer(self, interval=RESELECT_INTERVAL_MS)
        self._reselect_timer.timeout.connect(self._on_reselect_tick)

        self._watch_network()

    def _create_widget(self) -> CalendarWidget:
        """Create the widget window and connect its signals."""
        widget = CalendarWidget(embedded=self.embed)
        widget.clicked.connect(self._on_clicked)
        widget.refresh_requested.connect(self.refresh)
        widget.open_calendar_requested.connect(lambda: self._open_url(CALENDAR_URL))
        widget.quit_requested.connect(QApplication.quit)
        return widget

    def _show_widget(self) -> None:
        """Size (embedded mode), show and place the widget."""
        if self.embed:
            info = taskbar.get_taskbar()
            scale = QGuiApplication.primaryScreen().devicePixelRatio()
            height = round(info.rect.height / scale) if info else 48
            self.widget.resize(QSize(MAX_WIDTH, height))
        else:
            self.update_display()  # place it before it first appears
        self.widget.show()
        self.update_display()  # embedding needs the native window to exist

    def _replace_widget(self) -> None:
        """Throw the widget window away and create a fresh (hidden) one."""
        self.widget.hide()
        self.widget.deleteLater()
        self.widget = self._create_widget()

    def _fall_back_to_overlay(self) -> None:
        """Embedding failed: float over the taskbar instead."""
        log.warning("Could not embed into the taskbar; using overlay mode")
        self.embed = False
        self._replace_widget()
        self._show_widget()

    def start(self) -> None:
        """Show the widget, start the timers and load events."""
        self._placement_timer.start()
        self._topmost_timer.start()
        self._reselect_timer.start()
        self._keep_visible()  # shows the widget as soon as the taskbar exists
        self.refresh()

    # --- timing -------------------------------------------------------------------

    def _on_reselect_tick(self) -> None:
        """Every 30 s: switch to the right event on time, and notice waking from sleep."""
        now = time.time()
        if now - self._last_tick > SLEEP_GAP_SECONDS:
            log.info("PC woke up (no tick for %.0f s); refreshing", now - self._last_tick)
            self.refresh()
        self._last_tick = now
        self.update_display()

    def _watch_network(self) -> None:
        """Refresh as soon as Windows reports the network is back."""
        if not QNetworkInformation.loadDefaultBackend():
            log.info("No network-status backend; relying on the retry timer")
            return
        info = QNetworkInformation.instance()
        info.reachabilityChanged.connect(self._on_reachability_changed)

    def _on_reachability_changed(self, reachability: QNetworkInformation.Reachability) -> None:
        if reachability == QNetworkInformation.Reachability.Online:
            log.info("Network is back; refreshing")
            self.refresh()

    # --- fetching (background thread) -------------------------------------------

    def refresh(self) -> None:
        """Fetch events in the background unless a fetch/login is already running."""
        self._start_worker(allow_login=False)

    def sign_in(self) -> None:
        """Start the browser login in the background."""
        self.state = State.SIGNING_IN
        self.update_display()
        self._start_worker(allow_login=True)

    def _start_worker(self, allow_login: bool) -> None:
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._worker, args=(allow_login,), daemon=True).start()

    def _worker(self, allow_login: bool) -> None:
        """Runs off the UI thread. Always emits exactly one result signal."""
        try:
            creds = auth.get_credentials(allow_login=allow_login)
            events = calendar_client.fetch_events(creds, datetime.now().astimezone())
        except auth.ReauthRequiredError:
            self._reauth_needed.emit()
        except auth.CredentialsMissingError:
            log.error("credentials.json not found")
            self._credentials_missing.emit()
        except Exception:  # network/API errors must never crash the widget
            log.exception("Fetching events failed")
            self._fetch_failed.emit()
        else:
            self._fetch_succeeded.emit(events)

    # --- results (UI thread) ----------------------------------------------------

    def _on_fetch_succeeded(self, events: list[Event]) -> None:
        self._busy = False
        self.events = events
        self.state = State.READY
        self.stale = False
        try:
            calendar_client.save_cache(events, paths.cache_path())
        except OSError:
            log.exception("Could not write the event cache")
        self._refresh_timer.start(REFRESH_INTERVAL_MS)
        self.update_display()

    def _on_fetch_failed(self) -> None:
        self._busy = False
        if self.state is State.SIGNING_IN:
            self.state = State.SIGN_IN
        elif self.events:
            self.stale = True  # keep showing what we have, dimmed
        else:
            self.state = State.ERROR
        self._refresh_timer.start(RETRY_INTERVAL_MS)
        self.update_display()

    def _finish_with_state(self, state: State) -> None:
        self._busy = False
        self.state = state
        self._refresh_timer.start(REFRESH_INTERVAL_MS)
        self.update_display()

    # --- display ------------------------------------------------------------------

    def update_display(self) -> None:
        """Recompute the two lines from the current state and events."""
        now = datetime.now().astimezone()
        match self.state:
            case State.LOADING:
                self.widget.set_content("Loading…", "")
            case State.SIGN_IN:
                self.widget.set_content("Sign in to Google", "Click to connect")
            case State.SIGNING_IN:
                self.widget.set_content("Signing in…", "Continue in your browser")
            case State.MISSING_CREDENTIALS:
                self.widget.set_content(
                    "Setup needed", "credentials.json not found", "Click to open the setup guide"
                )
            case State.ERROR:
                self.widget.set_content("Can't load events", "Right-click → Refresh now")
            case State.READY:
                display = select_event(self.events, now)
                tooltip = build_tooltip(display.event, now) if display.event else ""
                if self.stale:
                    tooltip = (tooltip + "\n\n" if tooltip else "") + OFFLINE_NOTE
                if display.event:
                    # Title on top in bold, time range underneath.
                    self.widget.set_content(
                        display.title, display.time_text, tooltip, dimmed=self.stale
                    )
                else:
                    self.widget.set_content(display.time_text, "", tooltip, dimmed=self.stale)
        self.reposition()

    def _on_clicked(self) -> None:
        match self.state:
            case State.SIGN_IN:
                self.sign_in()
            case State.MISSING_CREDENTIALS:
                self._open_url(README_SETUP_URL)
            case _:
                display = select_event(self.events, datetime.now().astimezone())
                link = display.event.html_link if display.event else None
                self._open_url(link or CALENDAR_URL)

    @staticmethod
    def _open_url(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    # --- placement and visibility ------------------------------------------------

    def reposition(self) -> None:
        """Move the widget onto the taskbar; cheap enough to call every 2 s."""
        self.widget.set_light_theme(taskbar.uses_light_theme())
        if self.embed:
            self._reposition_embedded()
            return

        screen = QGuiApplication.primaryScreen()
        scale = screen.devicePixelRatio()
        info = taskbar.get_taskbar()
        if info is None:
            # Fallback: assume a 48 px bottom taskbar on the primary screen.
            width = round(screen.geometry().width() * scale)
            height = round(screen.geometry().height() * scale)
            physical = taskbar.Rect(0, height - round(48 * scale), width, height)
            info = taskbar.TaskbarInfo(physical, taskbar.Edge.BOTTOM)

        self._warn_about_layout(info.edge)
        rect = taskbar.widget_rect(info.rect, info.edge, scale, self.widget.preferred_width())
        target = QRect(rect.left, rect.top, rect.width, rect.height)
        if self.widget.geometry() != target:
            self.widget.setGeometry(target)

    def _warn_about_layout(self, edge: taskbar.Edge) -> None:
        """Log (once per change) when the taskbar layout isn't the expected one."""
        layout = (edge, taskbar.taskbar_is_left_aligned())
        if layout == self._warned_layout:
            return
        self._warned_layout = layout
        if edge is not taskbar.Edge.BOTTOM:
            log.warning("Taskbar is at the %s edge; placing the widget at its start", edge.name.lower())
        if layout[1]:
            log.warning("Taskbar icons are left-aligned; the widget may overlap the Start button")

    def _reposition_embedded(self) -> None:
        """Keep the widget as a child of the taskbar window.

        Coordinates here are physical pixels relative to the taskbar. Qt does
        not know it has a parent, so the window keeps the fixed size it got
        before embedding and is positioned through Win32 only.
        """
        if not self.widget.isVisible():
            return
        hwnd = int(self.widget.winId())
        tray = taskbar.find_taskbar_window()
        info = taskbar.get_taskbar()
        if tray is None or info is None:
            return
        if not taskbar.is_child_of(hwnd, tray):
            log.info("Embedding the widget into the taskbar")
            if not taskbar.embed_in_taskbar(hwnd, tray):
                self._fall_back_to_overlay()
                return

        key = self.widget.key_color()  # re-applied every tick: follows theme changes
        taskbar.set_color_key(hwnd, key.red(), key.green(), key.blue())

        # The window keeps a fixed size (set in start()); resizing through Qt
        # after embedding makes Qt compute wrong positions and stop painting.
        scale = QGuiApplication.primaryScreen().devicePixelRatio()
        width_px = round(self.widget.width() * scale)
        border_px = math.ceil(scale)  # the taskbar's 1-logical-px top border line
        height_px = info.rect.height - border_px
        taskbar.place_child(hwnd, round(8 * scale), border_px, width_px, height_px)

    def _keep_visible(self) -> None:
        """Runs every second: keep the widget shown, placed and on top."""
        if self.embed:
            self._keep_visible_embedded()
        else:
            self._keep_visible_overlay()

    def _keep_visible_embedded(self) -> None:
        """Inside the taskbar the widget hides with it in fullscreen, so this
        only survives Explorer restarts and keeps the hover state honest."""
        if not taskbar.window_exists(int(self.widget.winId())):
            # Explorer restarted: Windows destroyed the taskbar *and* our child window.
            log.warning("Widget window was destroyed (Explorer restart?); recreating it")
            self._replace_widget()
        if not self.widget.isVisible():
            if taskbar.find_taskbar_window() is None:
                return  # Explorer not running yet; try again next tick
            self._show_widget()

        hwnd = int(self.widget.winId())
        scale = QGuiApplication.primaryScreen().devicePixelRatio()
        cursor = taskbar.cursor_in_window(hwnd)
        content_px = self.widget.preferred_width() * scale
        self.widget.set_hovered(cursor is not None and cursor[0] < content_px)
        self._reposition_embedded()

    def _keep_visible_overlay(self) -> None:
        """Hide during fullscreen apps; otherwise stay above the taskbar."""
        if not self.widget.isVisible() and not self._hidden_for_fullscreen:
            self._show_widget()  # first tick after start
        hwnd = int(self.widget.winId())
        self.widget.sync_hover()
        if taskbar.is_fullscreen_app_active(hwnd):
            if not self._hidden_for_fullscreen:
                self._hidden_for_fullscreen = True
                self.widget.hide()
            return
        if self._hidden_for_fullscreen:
            self._hidden_for_fullscreen = False
            self.widget.show()
        taskbar.set_topmost(hwnd)


def run(embed: bool = True) -> int:
    """Create the Qt application, start the widget and run the event loop."""
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    controller = App(embed=embed)
    controller.start()
    return qt_app.exec()
