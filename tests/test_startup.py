# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verify early startup feedback does not depend on the framework it precedes."""

import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Native Windows startup notice")
def test_starting_notice_precedes_qt_and_closes():
    """A fresh process can paint feedback before loading Qt, and closes its thread."""
    script = """
import sys
from battread_gui.startup import StartupIndicator
assert not any(name.startswith('PySide6') for name in sys.modules)
indicator = StartupIndicator()
try:
    indicator.start()
    assert indicator.ready.is_set()
    assert indicator.error is None, indicator.error
    assert indicator.handle is not None
    assert not any(name.startswith('PySide6') for name in sys.modules)
finally:
    indicator.close()
assert indicator.handle is None
assert not indicator.thread.is_alive()
indicator.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
