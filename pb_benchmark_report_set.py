"""Cross-platform facade for atomic benchmark report-set publication.

The recovered report-set implementation uses POSIX ``fcntl.flock`` for
inter-process publication locking.  PlanReader is also developed and run on
Windows, where ``fcntl`` is unavailable.  This facade installs a minimal
Windows-compatible ``fcntl`` module backed by ``msvcrt.locking`` before
loading the recovered implementation.  POSIX platforms continue to use the
standard-library ``fcntl`` module unchanged.
"""
from __future__ import annotations

import os
import sys
import types


def _install_windows_fcntl_compat() -> None:
    if os.name != "nt" or "fcntl" in sys.modules:
        return

    import msvcrt
    import time

    compat = types.ModuleType("fcntl")
    compat.LOCK_EX = 2
    compat.LOCK_UN = 8

    def flock(fd: int, operation: int) -> None:
        # msvcrt.locking locks a byte range from the current file position.
        # Keep one stable byte in the lock file so every process contends on
        # exactly the same range.
        if os.fstat(fd).st_size == 0:
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"\0")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)

        if operation == compat.LOCK_EX:
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    time.sleep(0.05)
        elif operation == compat.LOCK_UN:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            raise ValueError(f"unsupported flock operation on Windows: {operation!r}")

    compat.flock = flock
    sys.modules["fcntl"] = compat


_install_windows_fcntl_compat()

# Re-export the recovered implementation.  Keeping it in a separate module
# lets us preserve the audited recovery commit byte-for-byte while supplying
# the platform shim before its unconditional ``import fcntl`` executes.
from _pb_benchmark_report_set_impl import *  # noqa: F401,F403,E402
