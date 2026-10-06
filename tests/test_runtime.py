# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Protect source/frozen routing and the app's original Windows icon."""

import struct
import sys
from pathlib import Path

import pytest

from battread_gui.runtime import worker_command


def test_source_worker_uses_python_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Source development keeps its existing module invocation and ready gate."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert worker_command("workspace") == (
        sys.executable,
        ["-m", "battread_gui.worker", "workspace"],
    )


def test_frozen_worker_does_not_restart_windowed_gui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A frozen launcher must choose the piped worker instead of relaunching itself."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "battread.exe"))
    executable, args = worker_command("workspace with spaces")
    assert Path(executable) == tmp_path / "_internal/battread-worker.exe"
    assert args == ["workspace with spaces"]


def test_windows_icon_contains_small_and_large_images() -> None:
    """Windows taskbar/Explorer sizes must have valid independent PNG payloads."""
    icon = (
        Path(__file__).resolve().parents[1] / "src/battread_gui/resources/battread.ico"
    )
    data = icon.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind, count) == (0, 1, 7)
    widths = []
    for index in range(count):
        width, _, _, _, _, _, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        widths.append(width or 256)
        assert data[offset : offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert offset + length <= len(data)
    assert widths == [16, 24, 32, 48, 64, 128, 256]
