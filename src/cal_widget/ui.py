"""The PySide6 widget window: draws the two lines and reports user actions.

This module only *displays* things. Deciding what to show and reacting to
clicks is the job of :mod:`cal_widget.app`.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QCursor,
    QEnterEvent,
    QFont,
    QFontMetricsF,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

# Layout, in logical pixels (Qt scales them for 125 %, 150 %, ...).
PADDING_X = 8  # space inside the hover highlight, left and right
BAR_WIDTH = 3
BAR_GAP = 8  # between the bar and the text
LINE_SPACING = 0
MAX_WIDTH = 280
HOVER_MARGIN_Y = 4  # Windows 11 taskbar buttons leave this gap above/below
HOVER_RADIUS = 4

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI"]
TIME_FONT_PX = 13
TITLE_FONT_PX = 12

DARK_THEME_TEXT = QColor(255, 255, 255)
LIGHT_THEME_TEXT = QColor(0, 0, 0, 228)
DIMMED_OPACITY = 0.55
DARK_TASKBAR = QColor(0x1C, 0x1C, 0x1C)  # Windows 11 dark taskbar, no transparency
LIGHT_TASKBAR = QColor(0xEE, 0xEE, 0xEE)


def _make_font(pixel_size: int, weight: QFont.Weight) -> QFont:
    """Create a Segoe UI Variable font, falling back to Segoe UI."""
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


class CalendarWidget(QWidget):
    """Frameless, transparent, never-focused window that shows one event."""

    clicked = Signal()
    refresh_requested = Signal()
    open_calendar_requested = Signal()
    quit_requested = Signal()

    def __init__(self, embedded: bool = False) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool  # no taskbar button, not in Alt+Tab
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus  # never steal focus
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        # Embedded in the taskbar we paint opaquely on a colour key instead
        # (see taskbar.set_color_key), because per-pixel alpha stops updating.
        self._embedded = embedded
        if not embedded:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Tooltips normally only appear for the active window.
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._time_font = _make_font(TIME_FONT_PX, QFont.Weight.Bold)
        self._title_font = _make_font(TITLE_FONT_PX, QFont.Weight.Normal)

        self._time_text = ""
        self._title = ""
        self._bar_color: QColor | None = None
        self._dimmed = False
        self._light_theme = False
        self._hovered = False
        self._pressed = False

    # --- public API ------------------------------------------------------------

    def set_content(
        self,
        time_text: str,
        title: str,
        tooltip: str = "",
        bar_color: str | None = None,
        dimmed: bool = False,
    ) -> None:
        """Change what is shown. ``bar_color`` is "#rrggbb" or None for the text colour."""
        self._time_text = time_text
        self._title = title
        self._bar_color = QColor(bar_color) if bar_color else None
        self._dimmed = dimmed
        self.setToolTip(tooltip)
        self.update()

    def set_light_theme(self, light: bool) -> None:
        """Use dark text for a light taskbar, white text for a dark one."""
        if light != self._light_theme:
            self._light_theme = light
            self.update()

    def preferred_width(self) -> int:
        """Width that fits the current text, capped at ``MAX_WIDTH``."""
        # Float metrics + ceil: integer metrics round down, which would make
        # the text one pixel too wide for its box and trigger the ellipsis.
        text_width = max(
            QFontMetricsF(self._time_font).horizontalAdvance(self._time_text),
            QFontMetricsF(self._title_font).horizontalAdvance(self._title),
        )
        width = PADDING_X + BAR_WIDTH + BAR_GAP + math.ceil(text_width) + 1 + PADDING_X
        return min(MAX_WIDTH, width)

    def sync_hover(self) -> None:
        """Recheck the hover state against the real cursor position.

        A window that is never activated does not always receive a leave
        event (e.g. when it moves away from under the cursor), so the
        controller calls this periodically.
        """
        self.set_hovered(self.isVisible() and self.rect().contains(self.mapFromGlobal(QCursor.pos())))

    def set_hovered(self, hovered: bool) -> None:
        """Set the hover highlight explicitly."""
        if hovered != self._hovered:
            self._hovered = hovered
            self._pressed = self._pressed and hovered
            self.update()

    # --- painting -------------------------------------------------------------

    def key_color(self) -> QColor:
        """Transparent colour for embedded mode: the taskbar's own colour, so
        anti-aliased text edges blend into the real background."""
        return QColor(LIGHT_TASKBAR if self._light_theme else DARK_TASKBAR)

    def _text_color(self) -> QColor:
        return QColor(LIGHT_THEME_TEXT if self._light_theme else DARK_THEME_TEXT)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # The window can be wider than its content (embedded mode), so the
        # clickable area is only the part that fits the text.
        content = QRectF(0, 0, min(self.width(), self.preferred_width()), self.height())

        if self._embedded:
            # Colour-key pixels become transparent *and click-through*, so the
            # content area gets a colour one step away from the key: it looks
            # identical but still receives clicks.
            key = self.key_color()
            painter.fillRect(self.rect(), key)
            step = -1 if key.red() > 127 else 1
            painter.fillRect(content, QColor(key.red() + step, key.green(), key.blue()))
        else:
            # Fully transparent pixels of a layered window let clicks fall through
            # to the taskbar, so paint an invisible (alpha = 1) background.
            painter.fillRect(content, QColor(0, 0, 0, 1))

        text_color = self._text_color()
        if self._hovered:
            highlight = QColor(text_color)
            highlight.setAlphaF(0.05 if self._pressed else 0.09)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(highlight)
            area = content.adjusted(0, HOVER_MARGIN_Y, 0, -HOVER_MARGIN_Y)
            painter.drawRoundedRect(area, HOVER_RADIUS, HOVER_RADIUS)

        if self._dimmed:
            painter.setOpacity(DIMMED_OPACITY)

        time_metrics = QFontMetricsF(self._time_font)
        title_metrics = QFontMetricsF(self._title_font)
        block_height = time_metrics.height()
        if self._title:
            block_height += LINE_SPACING + title_metrics.height()
        top = (self.height() - block_height) / 2

        # Vertical bar on the left, as tall as the text block.
        bar = QRectF(PADDING_X, top + 2, BAR_WIDTH, block_height - 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bar_color or text_color)
        painter.drawRoundedRect(bar, BAR_WIDTH / 2, BAR_WIDTH / 2)

        text_x = PADDING_X + BAR_WIDTH + BAR_GAP
        text_width = self.width() - text_x - PADDING_X
        painter.setPen(text_color)

        painter.setFont(self._time_font)
        time_text = time_metrics.elidedText(self._time_text, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QPointF(text_x, round(top + time_metrics.ascent())), time_text)

        if self._title:
            painter.setFont(self._title_font)
            title = title_metrics.elidedText(self._title, Qt.TextElideMode.ElideRight, text_width)
            baseline = top + time_metrics.height() + LINE_SPACING + title_metrics.ascent()
            painter.drawText(QPointF(text_x, round(baseline)), title)

    # --- mouse ------------------------------------------------------------------

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self.sync_hover()

    def leaveEvent(self, event: object) -> None:  # noqa: N802
        self._hovered = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.addAction("Refresh now", self.refresh_requested.emit)
        menu.addAction("Open Google Calendar", self.open_calendar_requested.emit)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_requested.emit)
        # QCursor.pos() is always right; event.globalPos() is derived from where
        # Qt *thinks* the window is, which is wrong when embedded in the taskbar.
        menu.exec(QCursor.pos())

    def event(self, event: QEvent) -> bool:  # noqa: A003
        if event.type() == QEvent.Type.ToolTip:
            if self.toolTip():
                QToolTip.showText(QCursor.pos(), self.toolTip(), self)
            return True
        return super().event(event)
