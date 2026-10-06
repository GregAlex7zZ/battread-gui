# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Select the isolated worker in source and packaged Windows installations."""

import sys
from pathlib import Path


def worker_command(workspace: str) -> tuple[str, list[str]]:
    """Return a launch command preserving piped JSON and the startup handshake.

    Source runs use Python's module entry point. The frozen GUI executable is
    windowed and cannot act as a Python interpreter; launch the bundled console
    worker instead. QProcess redirects its standard streams without a console
    window. Keeping it under _internal leaves one user-facing executable.
    """
    if getattr(sys, "frozen", False):
        worker = Path(sys.executable).resolve().parent / "_internal/battread-worker.exe"
        return str(worker), [workspace]
    return sys.executable, ["-m", "battread_gui.worker", workspace]
