# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verify a frozen package with synthetic files and no Python on its runtime PATH.

Run in the development environment after building. The shipped main executable
is opened/closed through Win32. Source widget orchestration then drives the
shipped worker, exercising the same compiled scientific code and ready gate.
This complements source tests; it is not a separate clean-machine certification.
"""

import argparse
import ctypes
import os
import struct
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path


def synthetic_mpr(path: Path) -> None:
    """Write known MPR records with mixed accessory widths and distinct voltages."""

    def module(name: bytes, version: int, data: bytes) -> bytes:
        """Frame independent wire records, never deriving bytes from the decoder."""
        return (
            b"MODULE"
            + struct.pack("<10s25sII8s", name, name, len(data), version, b"01/01/24")
            + data
        )

    ids = [4, 115, 8, 175, 6, 215, 77, 116, 176, 177, 182]
    header = (struct.pack("<IB", 2, len(ids)) + struct.pack("<11H", *ids)).ljust(
        405, b"\x00"
    )
    records = bytearray()
    for time_s, current in [(10, -2), (11, 3)]:
        fields = {
            4: struct.pack("<d", time_s),
            8: struct.pack("<f", current),
            6: struct.pack("<f", 3.5),
            77: struct.pack("<f", 9),
            115: b"\xff" * 8,
            116: b"\xff" * 8,
            175: b"\xff" * 4,
            176: b"\xff" * 4,
            177: b"\xff" * 4,
            182: b"\xff" * 8,
            215: b"\xff" * 4,
        }
        records.extend(b"".join(fields[i] for i in ids))
    path.write_bytes(
        b"BIO-LOGIC MODULAR FILE\x1a".ljust(48)
        + b"\x00" * 4
        + module(b"VMP Set   ", 0, b"")
        + module(b"VMP data  ", 2, header + records)
    )


def window_startup(bundle: Path) -> None:
    """Open the shipped window with sanitized runtime environment, then close it."""
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "QT_QPA_PLATFORM"):
        environment.pop(name, None)
    environment["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    executable = bundle / "battread.exe"
    process = subprocess.Popen(
        [str(executable)],
        cwd=bundle,
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    user = ctypes.WinDLL("user32")
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[int] = []

    def visit(handle: int, data: int) -> bool:
        """Find only this process's main window, leaving other user windows alone."""
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value == process.pid and user.IsWindowVisible(handle):
            text = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(handle, text, 256)
            if text.value == "battread":
                found.append(handle)
        return True

    callback = callback_type(visit)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    try:
        deadline = time.monotonic() + 30
        while not found and process.poll() is None and time.monotonic() < deadline:
            user.EnumWindows(callback, 0)
            time.sleep(0.05)
        if not found:
            raise AssertionError("The frozen main window did not open.")
        user.PostMessageW(found[0], 0x10, 0, 0)
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def worker_workflows(bundle: Path) -> None:
    """Drive frozen conversion, merge, warnings, failure and cancellation via Qt."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import battread
    from PySide6.QtWidgets import QApplication

    from battread_gui.app import MainWindow, configure_style

    application = QApplication.instance() or QApplication([])
    configure_style(application)
    original_executable = sys.executable
    original_path = os.environ.get("PATH", "")
    original_frozen = getattr(sys, "frozen", None)
    sys.executable = str(bundle / "battread.exe")
    sys.frozen = True
    os.environ["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    try:
        with tempfile.TemporaryDirectory(
            prefix="battread packaged check "
        ) as temporary:
            root = Path(temporary)
            for case in ("single", "merge", "mpr", "warning", "failure", "cancel"):
                folder = root / case
                folder.mkdir()
                first = folder / "first.txt"
                first.write_text(
                    "time_s,current_mA,voltage_V\n0,-2,3.5\n1,3,3.5\n", encoding="utf-8"
                )
                inputs = [first]
                if case == "merge":
                    second = folder / "second.txt"
                    second.write_text(
                        "time_s,current_mA,voltage_V\n0,-4,3.7\n2,5,3.7\n",
                        encoding="utf-8",
                    )
                    inputs = [second, first]
                elif case == "mpr":
                    first = folder / "accessory.mpr"
                    synthetic_mpr(first)
                    inputs = [first]
                elif case == "warning":
                    first.write_text(
                        "time_s,current_mA,voltage_V\n0,,3.5\n1,3,3.5\n",
                        encoding="utf-8",
                    )
                elif case == "failure":
                    first.write_text(
                        "time_s,current_mA,voltage_V\n0,-2,3.5\n2,3,3.5\n1,4,3.5\n",
                        encoding="utf-8",
                    )
                window = MainWindow()
                try:
                    window.append_files(inputs)
                    if case == "merge":
                        window.merge_box.setChecked(True)
                    output = window.make_job().outputs[0]
                    window.start()
                    if case == "cancel":
                        window.cancel()
                    deadline = time.monotonic() + 45
                    while window.workspace is not None and time.monotonic() < deadline:
                        application.processEvents()
                        time.sleep(0.01)
                    assert window.workspace is None, "Frozen worker timed out."
                    log = window.details.toPlainText()
                    if case in {"cancel", "failure"}:
                        assert not output.exists()
                        assert (
                            "Cancelled" in window.status.text()
                            if case == "cancel"
                            else "NonMonotonicTimeError" in log
                        )
                    else:
                        assert window.saved == 1, log
                        frame = battread.read(output)
                        assert battread.is_standardized(frame)
                        if case == "merge":
                            assert frame.current_mA.tolist() == [-4, 5, -2, 3]
                            assert frame.time_s.tolist() == [0, 2, 4, 5]
                        elif case == "warning":
                            assert frame.current_mA.isna().sum() == 1
                            assert log.count("MissingValueWarning") == 1
                        else:
                            assert frame.current_mA.tolist() == [-2, 3]
                            assert frame.voltage_V.tolist() == [3.5, 3.5]
                    assert not list(folder.glob(".battread-work-*"))
                    print(f"Frozen workflow passed: {case}", flush=True)
                finally:
                    window.close()
                    application.processEvents()
    finally:
        sys.executable = original_executable
        os.environ["PATH"] = original_path
        if original_frozen is None:
            del sys.frozen
        else:
            sys.frozen = original_frozen


def main() -> None:
    """Verify a specific extracted bundle without publishing or keeping test data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "dist/battread",
    )
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    window_startup(bundle)
    worker_workflows(bundle)
    print(
        "Frozen package checks passed. "
        "A separate clean-machine trial remains recommended."
    )


if __name__ == "__main__":
    main()
