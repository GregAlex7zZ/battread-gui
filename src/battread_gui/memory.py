# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows-enforced worker allocation limits, independent of GUI polling.

Job Objects cap committed process/job memory before heavy readers are imported.
They complement RSS/free-memory monitoring; committed memory and physical RAM
are different quantities. Closing the parent-owned handle kills orphan workers.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any


class BasicLimits(ctypes.Structure):
    """Match Microsoft's JOBOBJECT_BASIC_LIMIT_INFORMATION binary layout."""

    LimitFlags: int
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IOCounters(ctypes.Structure):
    """Preserve the reserved I/O fields in the Windows extended-limit structure."""

    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class ExtendedLimits(ctypes.Structure):
    """Represent the exact allocation-cap fields consumed by SetInformationJobObject."""

    BasicLimitInformation: BasicLimits
    ProcessMemoryLimit: int
    JobMemoryLimit: int
    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class MemoryGuard:
    """Attach a Windows worker to a hard committed-memory budget.

    Construct only after process spawn and before sending the startup handshake.
    Close once after worker exit. On non-Windows test systems this is a no-op;
    the application still monitors RSS. On Windows, inability to establish the
    guard raises OSError and the application refuses unprotected processing.
    """

    def __init__(self, pid: int, budget: int) -> None:
        """Install allocation caps and orphan cleanup for this worker process only."""
        self.handle: int | None = None
        # ctypes dynamically generates foreign function objects. Keep Any at
        # this ABI boundary rather than weakening application-level typing.
        self.kernel: Any = None
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel = kernel
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = handle
        try:
            limits = ExtendedLimits()
            # PROCESS_MEMORY | JOB_MEMORY | KILL_ON_JOB_CLOSE. Job-wide limits
            # also contain any subprocesses launched by a future vendor reader.
            limits.BasicLimitInformation.LimitFlags = 0x100 | 0x200 | 0x2000
            limits.ProcessMemoryLimit = budget
            limits.JobMemoryLimit = budget
            if not kernel.SetInformationJobObject(
                handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            # SET_QUOTA | TERMINATE are the documented assignment access rights.
            process = kernel.OpenProcess(0x100 | 0x1, False, pid)
            if not process:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not kernel.AssignProcessToJobObject(handle, process):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(process)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Release the job handle exactly once; terminate any orphaned job members."""
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
