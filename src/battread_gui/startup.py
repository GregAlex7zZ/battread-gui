# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lightweight Windows startup feedback before importing Qt and the main window.

Only the standard library is imported initially. A small native window owns its
message loop in a separate thread, remaining responsive during slow Qt imports.
It disappears after the main window has been shown; no artificial delay is added.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Any


class StartupIndicator:
    """Own a temporary Windows starting notice independently of Qt initialization.

    Call start() before importing Qt, then close() after the main window paints.
    close() is idempotent. Non-Windows systems use a no-op. Native-window failures
    do not prevent launching the application.
    """

    def __init__(self) -> None:
        """Prepare synchronization without loading any GUI framework."""
        self.ready = threading.Event()
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.handle: int | None = None
        self.error: str | None = None

    def start(self) -> None:
        """Paint the early notice before permitting expensive imports to start."""
        if os.name != "nt":
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(timeout=2)

    def close(self) -> None:
        """Stop the native loop and release its window on the owning thread."""
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)

    def _run(self) -> None:
        """Create and pump a standard Win32 static window while Qt loads elsewhere."""
        user: Any = None  # ctypes function signatures are a narrow dynamic ABI.
        handle: int | None = None
        try:
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.CreateWindowExW.argtypes = [
                wintypes.DWORD,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.DWORD,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                wintypes.HMENU,
                wintypes.HINSTANCE,
                ctypes.c_void_p,
            ]
            user.CreateWindowExW.restype = wintypes.HWND
            user.GetSystemMetrics.argtypes = [ctypes.c_int]
            user.GetSystemMetrics.restype = ctypes.c_int
            user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user.UpdateWindow.argtypes = [wintypes.HWND]
            user.DestroyWindow.argtypes = [wintypes.HWND]
            user.PeekMessageW.argtypes = [
                ctypes.POINTER(wintypes.MSG),
                wintypes.HWND,
                wintypes.UINT,
                wintypes.UINT,
                wintypes.UINT,
            ]
            user.PeekMessageW.restype = wintypes.BOOL
            user.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user.DispatchMessageW.restype = ctypes.c_ssize_t
            user.SendMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                ctypes.c_size_t,
                ctypes.c_ssize_t,
            ]
            user.SendMessageW.restype = ctypes.c_ssize_t
            user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
            # Match Qt's per-monitor-v2 mode before the first native HWND exists.
            user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            width, height = 360, 90
            handle = user.CreateWindowExW(
                0x08000088,  # NOACTIVATE | TOOLWINDOW | TOPMOST
                "STATIC",
                "Starting battread…",
                0x80800201,  # POPUP | BORDER | SS_CENTERIMAGE | SS_CENTER
                (user.GetSystemMetrics(0) - width) // 2,
                (user.GetSystemMetrics(1) - height) // 2,
                width,
                height,
                None,
                None,
                None,
                None,
            )
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = handle
            gdi = ctypes.WinDLL("gdi32")
            gdi.GetStockObject.argtypes = [ctypes.c_int]
            gdi.GetStockObject.restype = wintypes.HANDLE
            user.SendMessageW(handle, 0x30, gdi.GetStockObject(17), 1)
            user.ShowWindow(handle, 4)  # SHOWNOACTIVATE: no focus theft.
            user.UpdateWindow(handle)
            self.ready.set()
            message = wintypes.MSG()
            while not self.stop.wait(0.02):
                while user.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    user.TranslateMessage(ctypes.byref(message))
                    user.DispatchMessageW(ctypes.byref(message))
        except Exception as error:
            self.error = str(error)
        finally:
            self.ready.set()
            if handle is not None and user is not None:
                user.DestroyWindow(handle)
            self.handle = None


def show_startup_error(error: Exception) -> None:
    """Explain startup failure even when pythonw provides no visible console."""
    message = f"battread could not start.\n\n{type(error).__name__}: {error}"
    if os.name == "nt":
        user = ctypes.WinDLL("user32")
        user.MessageBoxW.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.UINT,
        ]
        user.MessageBoxW(None, message, "battread — Startup error", 0x10)
    else:
        print(message, file=sys.stderr)


def main() -> None:
    """Show early feedback, initialize Qt, then replace it with the main window.

    A portable launcher supplies BATTREAD_STARTUP_READY while its initial
    notice is visible. In that case avoid a second notice and acknowledge the
    painted window through the marker before entering the Qt event loop.
    """
    indicator = StartupIndicator()
    ready_marker = os.environ.pop("BATTREAD_STARTUP_READY", None)
    if ready_marker is None:
        indicator.start()
    try:
        from PySide6.QtWidgets import QApplication

        from battread_gui.app import MainWindow, configure_style

        app = QApplication(sys.argv)
        configure_style(app)
        window = MainWindow()
        window.show()
        app.processEvents()
        if ready_marker is not None:
            Path(ready_marker).touch()
    except Exception as error:
        indicator.close()
        show_startup_error(error)
        raise SystemExit(1) from error
    finally:
        indicator.close()
    sys.exit(app.exec())
