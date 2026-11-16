"""Draw the app icon and save it as assets/icon.ico (run: python tools/make_icon.py).

The icon is a small picture of the widget itself: a dark rounded square with
the white accent bar and two "lines of text". It is drawn with Qt at several
sizes, because Windows picks a different size for Explorer, the taskbar and
Alt+Tab, and a 256 px image scaled down to 16 px looks blurry.

An .ico file is just a small header, one directory entry per image and then
the images themselves; since Windows Vista each image may simply be a PNG.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

SIZES = [16, 24, 32, 48, 64, 128, 256]
OUTPUT = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"

BACKGROUND = QColor("#202020")
FOREGROUND = QColor("white")


def draw(size: int) -> QImage:
    """Render the icon at ``size`` × ``size`` pixels."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    s = size / 16  # everything below is designed on a 16 × 16 grid

    painter.setBrush(BACKGROUND)
    painter.drawRoundedRect(QRectF(0, 0, size, size), 3.5 * s, 3.5 * s)

    painter.setBrush(FOREGROUND)
    painter.drawRoundedRect(QRectF(3 * s, 3.5 * s, 1.5 * s, 9 * s), 0.75 * s, 0.75 * s)  # bar
    painter.drawRoundedRect(QRectF(6 * s, 4.5 * s, 7 * s, 2.5 * s), 1.25 * s, 1.25 * s)  # time
    painter.setBrush(QColor(255, 255, 255, 170))
    painter.drawRoundedRect(QRectF(6 * s, 9 * s, 4.5 * s, 2.5 * s), 1.25 * s, 1.25 * s)  # title
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    """Encode a QImage as PNG."""
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def write_ico(images: list[QImage], path: Path) -> None:
    """Write PNG-compressed images into one .ico file."""
    pngs = [png_bytes(image) for image in images]
    header = struct.pack("<HHH", 0, 1, len(pngs))  # reserved, type 1 = icon, count
    offset = 6 + 16 * len(pngs)  # images start after the header and directory
    directory = b""
    for image, png in zip(images, pngs):
        side = image.width() if image.width() < 256 else 0  # 0 means 256
        # width, height, colour count, reserved, planes, bits per pixel, size, offset
        directory += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + directory + b"".join(pngs))


def main() -> int:
    app = QGuiApplication(sys.argv)  # needed before QPainter can draw  # noqa: F841
    write_ico([draw(size) for size in SIZES], OUTPUT)
    draw(256).save(str(OUTPUT.with_suffix(".png")))  # for the README
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
