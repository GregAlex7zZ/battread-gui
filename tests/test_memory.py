# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verify real Windows allocation containment and orphan-worker cleanup."""

import os
import subprocess
import sys

import pytest

from battread_gui.memory import MemoryGuard


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_windows_memory_limit_prevents_large_allocation():
    """A child cannot commit an allocation beyond the configured job budget."""
    script = """
import sys
sys.stdin.readline()
try:
    allocation = bytearray(512 * 1024**2)
except MemoryError:
    print('limited', flush=True)
else:
    print('unprotected', flush=True)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    guard = None
    try:
        guard = MemoryGuard(process.pid, 128 * 1024**2)
        output, errors = process.communicate("ready\n", timeout=10)
        assert process.returncode == 0, errors
        assert output.strip() == "limited"
    finally:
        if guard is not None:
            guard.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_closing_guard_stops_orphan_worker():
    """Losing the parent-owned handle cannot leave a runaway worker behind."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        guard = MemoryGuard(process.pid, 256 * 1024**2)
        guard.close()
        process.wait(timeout=10)
        # Closing a Windows job can terminate members with exit code zero;
        # timely termination, rather than its exit code, is the invariant.
        assert process.poll() is not None
        guard.close()  # Handle closure is deliberately idempotent.
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
