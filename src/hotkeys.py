"""Global hotkey manager using the official Win32 RegisterHotKey API.

Unlike low-level keyboard hooks (WH_KEYBOARD_LL), RegisterHotKey does not
intercept or inspect general keystrokes when the app is idle.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Optional

from src.win32_backend import (
    MOD_NOREPEAT,
    PM_NOREMOVE,
    WM_APP,
    WM_HOTKEY,
    WM_QUIT,
    kernel32,
    user32,
)

WM_REBIND_HOTKEYS = WM_APP + 1
HOTKEY_ID_RECORD = 1
HOTKEY_ID_PLAY = 2
HOTKEY_ID_STOP = 3

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MODIFIER_FLAGS = {"CTRL": MOD_CONTROL, "ALT": MOD_ALT, "SHIFT": MOD_SHIFT}
MODIFIER_ORDER = ("CTRL", "ALT", "SHIFT")
MODIFIER_VKS = {"CTRL": 0x11, "ALT": 0x12, "SHIFT": 0x10}

SPECIAL_VK_MAP: dict[str, int] = {
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "PAUSE": 0x13,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "SCROLLLOCK": 0x91,
    "SPACE": 0x20,
    **{f"F{i}": 0x70 + (i - 1) for i in range(1, 25)},
}

DISPLAY_NAMES = {"CTRL": "Ctrl", "ALT": "Alt", "SHIFT": "Shift", "PAGEUP": "PgUp", "PAGEDOWN": "PgDn",
                 "SCROLLLOCK": "ScrLk", "DELETE": "Del", "INSERT": "Ins", "ESCAPE": "Esc", "ESC": "Esc",
                 "PAUSE": "Pause", "HOME": "Home", "END": "End", "SPACE": "Space"}


def split_hotkey(name: str) -> tuple[list[str], str]:
    """'ctrl+shift+r' -> (['CTRL', 'SHIFT'], 'R'), with modifiers in canonical order."""
    parts = [p.strip().upper().replace("_", "") for p in name.split("+") if p.strip()]
    if not parts:
        return [], ""
    mods = {p for p in parts[:-1] if p in MODIFIER_FLAGS}
    return [m for m in MODIFIER_ORDER if m in mods], parts[-1]


def canonical_hotkey(name: str) -> str:
    mods, key = split_hotkey(name)
    return "+".join(mods + [key]) if key else ""


def display_hotkey(name: str) -> str:
    """'CTRL+SHIFT+R' -> 'Ctrl + Shift + R' for the UI."""
    mods, key = split_hotkey(name)
    if not key:
        return "—"
    return " + ".join(DISPLAY_NAMES.get(p, p) for p in mods + [key])


def hotkey_name_to_vk(name: str) -> int:
    """Convert a key name such as 'F9', 'ESC' or 'R' (no modifiers) to a virtual-key code."""
    key = split_hotkey(name)[1]
    if key in SPECIAL_VK_MAP:
        return SPECIAL_VK_MAP[key]
    if len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        return ord(key)
    return 0


def hotkey_modifiers(name: str) -> int:
    flags = 0
    for mod in split_hotkey(name)[0]:
        flags |= MODIFIER_FLAGS[mod]
    return flags


def held_modifier_combo(base_key: str) -> str:
    """Combine a base key with whichever Ctrl/Alt/Shift keys are physically held now."""
    held = [m for m in MODIFIER_ORDER if user32.GetAsyncKeyState(MODIFIER_VKS[m]) & 0x8000]
    return canonical_hotkey("+".join(held + [base_key]))


class GlobalHotkeyManager:
    """Listens for configured hotkeys via Win32 RegisterHotKey / WM_HOTKEY."""

    def __init__(
        self,
        on_toggle_record: Callable[[], None],
        on_toggle_play: Callable[[], None],
        on_stop_all: Callable[[], None],
        on_registered: Optional[Callable[[dict[str, bool]], None]] = None,
    ) -> None:
        self.on_toggle_record = on_toggle_record
        self.on_toggle_play = on_toggle_play
        self.on_stop_all = on_stop_all
        # Called from the hotkey thread with {"record"|"play"|"stop": registered_ok}
        self.on_registered = on_registered
        self._suspended = False
        # Latest registration outcome, safe to poll from the UI thread
        self.last_results: dict[str, bool] = {}
        self.results_version = 0

        self._lock = threading.Lock()
        self._hotkey_record = "F9"
        self._hotkey_play = "F10"
        self._hotkey_stop = "F12"
        self._thread: Optional[threading.Thread] = None
        self._thread_id: int = 0
        self._ready_event = threading.Event()

    def set_hotkeys(self, record_key: str, play_key: str, stop_key: str) -> None:
        with self._lock:
            self._hotkey_record = canonical_hotkey(record_key)
            self._hotkey_play = canonical_hotkey(play_key)
            self._hotkey_stop = canonical_hotkey(stop_key)
            tid = self._thread_id
        if tid:
            user32.PostThreadMessageW(tid, WM_REBIND_HOTKEYS, 0, 0)

    def set_suspended(self, suspended: bool) -> None:
        """Temporarily release all hotkeys (e.g. while the user is choosing a new key)."""
        with self._lock:
            self._suspended = suspended
            tid = self._thread_id
        if tid:
            user32.PostThreadMessageW(tid, WM_REBIND_HOTKEYS, 0, 0)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready_event.clear()
            self._thread = threading.Thread(target=self._run_message_loop, daemon=True)
            self._thread.start()
        self._ready_event.wait(timeout=2.0)

    def stop(self) -> None:
        with self._lock:
            tid = self._thread_id
            thread = self._thread
        if tid:
            user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=1.5)
        with self._lock:
            self._thread = None
            self._thread_id = 0

    def _register_all(self) -> None:
        self._unregister_all()
        with self._lock:
            if self._suspended:
                return
            bindings = [
                ("record", HOTKEY_ID_RECORD, self._hotkey_record),
                ("play", HOTKEY_ID_PLAY, self._hotkey_play),
                ("stop", HOTKEY_ID_STOP, self._hotkey_stop),
            ]
        results: dict[str, bool] = {}
        seen: set[tuple[int, int]] = set()
        for action, hk_id, name in bindings:
            vk, mods = hotkey_name_to_vk(name), hotkey_modifiers(name)
            ok = False
            if vk and (vk, mods) not in seen:
                seen.add((vk, mods))
                ok = bool(user32.RegisterHotKey(None, hk_id, MOD_NOREPEAT | mods, vk))
            results[action] = ok
        with self._lock:
            self.last_results = dict(results)
            self.results_version += 1
        if self.on_registered:
            try:
                self.on_registered(results)
            except Exception:
                pass

    def _unregister_all(self) -> None:
        for hk_id in (HOTKEY_ID_RECORD, HOTKEY_ID_PLAY, HOTKEY_ID_STOP):
            user32.UnregisterHotKey(None, hk_id)

    def _run_message_loop(self) -> None:
        msg = wintypes.MSG()
        # Ensure this thread's message queue exists before PostThreadMessageW is called
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        with self._lock:
            self._thread_id = int(kernel32.GetCurrentThreadId())
        self._register_all()
        self._ready_event.set()

        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_REBIND_HOTKEYS:
                    self._register_all()
                elif msg.message == WM_HOTKEY:
                    hk_id = int(msg.wParam)
                    if hk_id == HOTKEY_ID_RECORD:
                        self.on_toggle_record()
                    elif hk_id == HOTKEY_ID_PLAY:
                        self.on_toggle_play()
                    elif hk_id == HOTKEY_ID_STOP:
                        self.on_stop_all()
        finally:
            self._unregister_all()
            with self._lock:
                self._thread_id = 0
