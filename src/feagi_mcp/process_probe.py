"""Check whether a process exists without disturbing it.

Never use ``os.kill(pid, 0)`` on Windows: Python's Windows ``os.kill`` calls
``TerminateProcess`` for any signal other than CTRL_C_EVENT / CTRL_BREAK_EVENT,
so the "probe" would kill the target (exit code 0). Windows uses
``OpenProcess`` + ``GetExitCodeProcess`` instead.
"""

from __future__ import annotations

import os
import sys
from typing import Any, cast

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE = 259


def _pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int, kernel32: Any = None) -> bool:
    """Windows liveness probe; ``kernel32`` is injectable for tests."""
    import ctypes
    from ctypes import wintypes

    if kernel32 is None:
        # WinDLL and get_last_error are present at runtime on Windows and absent
        # from the non-Windows ctypes stubs. cast keeps both mypy platforms quiet.
        win_ctypes = cast(Any, ctypes)
        kernel32 = win_ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        get_last_error = win_ctypes.get_last_error
    else:
        get_last_error = kernel32.get_last_error

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return bool(get_last_error() == _ERROR_ACCESS_DENIED)
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return int(code.value) == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    return _pid_alive_posix(pid)
