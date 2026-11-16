"""The PySide6 widget window: draws the two lines and reports user actions.

This module only *displays* things. Deciding what to show and reacting to
clicks is the job of :mod:`cal_widget.app`.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
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
from PySide6.QtWidgets import QMenu, QWidget

# Layout, in logical pixels (Qt scales them for 125 %, 150 %, ...).
PADDING_X = 8  # space inside the hover highlight, left and right
BAR_WIDTH = 3
BAR_GAP = 8  # between the bar and the text
LINE_SPACING = 0
MAX_WIDTH = 280
HOVER_MARGIN_Y = 4  # Windows 11 taskbar buttons leave this gap above/below
HOVER_RADIUS = 4

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI"]
HEADING_FONT_PX = 13  # line 1, bold: the event title
DETAIL_FONT_PX = 12  # line 2, regular: the time range

DARK_THEME_TEXT = QColor(255, 255, 255)
LIGHT_THEME_TEXT = QColor(0, 0, 0, 228)
DIMMED_OPACITY = 0.55


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

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool  # no taskbar button, not in Alt+Tab
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus  # never steal focus
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Tooltips normally only appear for the active window.
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._heading_font = _make_font(HEADING_FONT_PX, QFont.Weight.Bold)
        self._detail_font = _make_font(DETAIL_FONT_PX, QFont.Weight.Normal)

        self._heading = ""
        self._detail = ""
        self._bar_color: QColor | None = None
        self._dimmed = False
        self._light_theme = False
        self._hovered = False
        self._pressed = False

    # --- public API ------------------------------------------------------------

    def set_content(
        self,
        heading: str,
        detail: str = "",
        tooltip: str = "",
        bar_color: str | None = None,
        dimmed: bool = False,
    ) -> None:
        """Change what is shown.

        Args:
            heading: line 1, bold (e.g. the event title).
            detail: line 2, regular (e.g. the time range); empty for one line.
            tooltip: hover text.
            bar_color: "#rrggbb", or None to use the text colour.
            dimmed: draw faded, e.g. for cached data while offline.
        """
        self._heading = heading
        self._detail = detail
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
            QFontMetricsF(self._heading_font).horizontalAdvance(self._heading),
            QFontMetricsF(self._detail_font).horizontalAdvance(self._detail),
        )
        width = PADDING_X + BAR_WIDTH + BAR_GAP + math.ceil(text_width) + 1 + PADDING_X
        return min(MAX_WIDTH, width)

    def sync_hover(self) -> None:
        """Recheck the hover state against the real cursor position.

        A window that is never activated does not always receive a leave
        event (e.g. when it moves away from under the cursor), so the
        controller calls this periodically.
        """
        hovered = self.isVisible() and self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        if hovered != self._hovered:
            self._hovered = hovered
            self._pressed = self._pressed and hovered
            self.update()

    # --- painting -------------------------------------------------------------

    def _text_color(self) -> QColor:
        return QColor(LIGHT_THEME_TEXT if self._light_theme else DARK_THEME_TEXT)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Fully transparent pixels of a layered window let clicks fall through
        # to the taskbar, so paint an invisible (alpha = 1) background.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

        text_color = self._text_color()
        if self._hovered:
            highlight = QColor(text_color)
            highlight.setAlphaF(0.05 if self._pressed else 0.09)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(highlight)
            area = QRectF(self.rect()).adjusted(0, HOVER_MARGIN_Y, 0, -HOVER_MARGIN_Y)
            painter.drawRoundedRect(area, HOVER_RADIUS, HOVER_RADIUS)

        if self._dimmed:
            painter.setOpacity(DIMMED_OPACITY)

        heading_metrics = QFontMetricsF(self._heading_font)
        detail_metrics = QFontMetricsF(self._detail_font)
        block_height = heading_metrics.height()
        if self._detail:
            block_height += LINE_SPACING + detail_metrics.height()
        top = (self.height() - block_height) / 2

        # Vertical bar on the left, as tall as the text block.
        bar = QRectF(PADDING_X, top + 2, BAR_WIDTH, block_height - 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bar_color or text_color)
        painter.drawRoundedRect(bar, BAR_WIDTH / 2, BAR_WIDTH / 2)

        text_x = PADDING_X + BAR_WIDTH + BAR_GAP
        text_width = self.width() - text_x - PADDING_X
        painter.setPen(text_color)

        painter.setFont(self._heading_font)
        heading = heading_metrics.elidedText(self._heading, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QPointF(text_x, round(top + heading_metrics.ascent())), heading)

        if self._detail:
            painter.setFont(self._detail_font)
            detail = detail_metrics.elidedText(self._detail, Qt.TextElideMode.ElideRight, text_width)
            baseline = top + heading_metrics.height() + LINE_SPACING + detail_metrics.ascent()
            painter.drawText(QPointF(text_x, round(baseline)), detail)

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
        menu.exec(event.globalPos())
