"""Keep only one copy of the app running.

The first copy owns a named mutex and waits on a named event. Launching the app
again signals that event (so the first copy shows its window) and then exits.
Without this, hidden copies in the tray would each try to grab the same global
hotkeys, and every copy after the first would silently get none.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Optional

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
INFINITE = 0xFFFFFFFF

MUTEX_NAME = "Local\\GhostMacroRecorder.Instance"
SHOW_EVENT_NAME = "Local\\GhostMacroRecorder.Show"

_mutex_handle: Optional[int] = None


def acquire_single_instance() -> bool:
    """Return True if this is the first copy. Otherwise ask the first copy to show itself."""
    global _mutex_handle
    try:
        ctypes.set_last_error(0)
        handle = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
        already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    except Exception:
        return True  # never block startup because of this feature
    if not already:
        _mutex_handle = handle
        return True
    if handle:
        _kernel32.CloseHandle(handle)
    event = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
    if event:
        _kernel32.SetEvent(event)
        _kernel32.CloseHandle(event)
    return False


def listen_for_show_requests(on_show: Callable[[], None]) -> None:
    """Call on_show (from a background thread) whenever another launch asks us to appear."""
    event = _kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
    if not event:
        return

    def wait_loop() -> None:
        while True:
            if _kernel32.WaitForSingleObject(event, INFINITE) != 0:
                return
            try:
                on_show()
            except Exception:
                pass

    threading.Thread(target=wait_loop, daemon=True).start()
