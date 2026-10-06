# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Qt fixtures using an offscreen display and synthetic local files only."""

import os
import struct
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app() -> Iterator[QApplication]:
    """Keep one Qt application alive throughout event-driven interface tests."""
    application = QApplication.instance() or QApplication([])
    from battread_gui.app import configure_style

    configure_style(application)
    yield application


@pytest.fixture
def accessory_mpr(tmp_path: Path) -> Path:
    """Encode mixed-width accessory fields around distinct measured/average voltages.

    Independent struct bytes cover every verified skip without real acquisitions
    or decoder-generated expectations. Opaque NaN bytes must never affect the
    canonical values. The fixture requires the optional Bio-Logic dependency.
    """
    pytest.importorskip("galvani")

    def module(name: bytes, version: int, payload: bytes) -> bytes:
        """Frame a synthetic module using the independently specified wire layout."""
        return (
            b"MODULE"
            + struct.pack("<10s25sII8s", name, name, len(payload), version, b"01/01/24")
            + payload
        )

    identifiers = [4, 115, 8, 175, 6, 215, 77, 116, 176, 177, 182]
    header = struct.pack("<IB", 2, len(identifiers))
    header += struct.pack("<" + "H" * len(identifiers), *identifiers)
    header = header.ljust(405, b"\x00")
    records = bytearray()
    for time, current in [(10.0, -2.0), (11.0, 3.0)]:
        fields = {
            4: struct.pack("<d", time),
            8: struct.pack("<f", current),
            6: struct.pack("<f", 3.5),
            77: struct.pack("<f", 9.0),
            115: b"\xff" * 8,
            116: b"\xff" * 8,
            175: b"\xff" * 4,
            176: b"\xff" * 4,
            177: b"\xff" * 4,
            182: b"\xff" * 8,
            215: b"\xff" * 4,
        }
        records.extend(b"".join(fields[identifier] for identifier in identifiers))
    source = tmp_path / "accessory.mpr"
    source.write_bytes(
        b"BIO-LOGIC MODULAR FILE\x1a".ljust(48)
        + b"\x00" * 4
        + module(b"VMP Set   ", 0, b"")
        + module(b"VMP data  ", 2, header + records)
    )
    return source
