# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render the original grayscale SVG into a multi-resolution Windows icon.

Run with PySide6 installed. Qt renders each size; the standard library writes
ICO framing around lossless PNG payloads, avoiding an extra image dependency.
"""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> None:
    """Rebuild the icon from its editable vector source at seven Windows sizes."""
    application = QGuiApplication.instance() or QGuiApplication([])
    resources = Path(__file__).resolve().parents[1] / "src/battread_gui/resources"
    renderer = QSvgRenderer(str(resources / "battread.svg"))
    sizes = (16, 24, 32, 48, 64, 128, 256)
    payloads: list[bytes] = []
    for size in sizes:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Could not encode the Windows icon.")
        payloads.append(bytes(data.data()))
        buffer.close()
    contents = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for size, payload in zip(sizes, payloads, strict=True):
        contents.extend(
            struct.pack(
                "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(payload), offset
            )
        )
        offset += len(payload)
    for payload in payloads:
        contents.extend(payload)
    (resources / "battread.ico").write_bytes(contents)
    application.processEvents()


if __name__ == "__main__":
    main()
