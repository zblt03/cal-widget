"""Application controller: owns the state, talks to Google, drives the widget.

Network calls run on a background thread so the UI never freezes. Results
come back through Qt signals, which Qt delivers on the UI thread.
"""

from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from enum import Enum, auto

from PySide6.QtCore import QObject, QRect, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication

from cal_widget import auth, calendar_client, taskbar
from cal_widget.events import Event, format_time_range, select_event
from cal_widget.ui import MAX_WIDTH, CalendarWidget

log = logging.getLogger(__name__)

CALENDAR_URL = "https://calendar.google.com/"
README_SETUP_URL = "https://github.com/zblt03/cal-widget#google-cloud-setup"
PLACEMENT_INTERVAL_MS = 2_000
TOPMOST_INTERVAL_MS = 1_000


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

    def __init__(self, embed: bool = False) -> None:
        super().__init__()
        self.embed = embed  # experimental: live inside the taskbar window
        self.widget = CalendarWidget()
        self.state = State.LOADING
        self.events: list[Event] = []
        self._busy = False  # a fetch or login thread is running
        self._hidden_for_fullscreen = False
        self._warned_layout: tuple[taskbar.Edge, bool] | None = None

        self._fetch_succeeded.connect(self._on_fetch_succeeded)
        self._fetch_failed.connect(self._on_fetch_failed)
        self._reauth_needed.connect(lambda: self._finish_with_state(State.SIGN_IN))
        self._credentials_missing.connect(
            lambda: self._finish_with_state(State.MISSING_CREDENTIALS)
        )

        self.widget.clicked.connect(self._on_clicked)
        self.widget.refresh_requested.connect(self.refresh)
        self.widget.open_calendar_requested.connect(lambda: self._open_url(CALENDAR_URL))
        self.widget.quit_requested.connect(QApplication.quit)

        self._placement_timer = QTimer(self, interval=PLACEMENT_INTERVAL_MS)
        self._placement_timer.timeout.connect(self.reposition)
        self._topmost_timer = QTimer(self, interval=TOPMOST_INTERVAL_MS)
        self._topmost_timer.timeout.connect(self._keep_visible)

    def start(self) -> None:
        """Show the widget, start the timers and load events."""
        self.update_display()
        if self.embed:
            info = taskbar.get_taskbar()
            scale = QGuiApplication.primaryScreen().devicePixelRatio()
            height = round(info.rect.height / scale) if info else 48
            self.widget.resize(QSize(MAX_WIDTH, height))
        self.widget.show()
        self.reposition()  # embedding needs the native window to exist
        self._placement_timer.start()
        self._topmost_timer.start()
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
        self.update_display()

    def _on_fetch_failed(self) -> None:
        self._busy = False
        if self.state is State.SIGNING_IN:
            self.state = State.SIGN_IN
        elif not self.events:
            self.state = State.ERROR
        self.update_display()

    def _finish_with_state(self, state: State) -> None:
        self._busy = False
        self.state = state
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
                self.widget.set_content(display.time_text, display.title, tooltip)
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
        """Experimental: keep the widget as a child of the taskbar window.

        Coordinates here are physical pixels relative to the taskbar. Qt does
        not know it has a parent, so we resize through Qt (to keep its
        painting size right) and then position through Win32.
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
                return

        # The window keeps a fixed size (set in start()); resizing through Qt
        # after embedding makes Qt compute wrong positions and stop painting.
        scale = QGuiApplication.primaryScreen().devicePixelRatio()
        width_px = round(self.widget.width() * scale)
        height_px = round(self.widget.height() * scale)
        y = (info.rect.height - height_px) // 2
        taskbar.place_child(hwnd, round(8 * scale), y, width_px, height_px)

    def _keep_visible(self) -> None:
        """Hide during fullscreen apps; otherwise stay above the taskbar."""
        hwnd = int(self.widget.winId())
        if self.embed:
            # Inside the taskbar: it hides with it in fullscreen; just keep
            # the hover state honest and stay above the XAML content.
            self.widget.set_hovered(taskbar.cursor_over_window(hwnd))
            self._reposition_embedded()
            return
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


def run(embed: bool = False) -> int:
    """Create the Qt application, start the widget and run the event loop."""
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    controller = App(embed=embed)
    controller.start()
    return qt_app.exec()
