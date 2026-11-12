"""Background, window-aware mouse and keyboard macro recorder."""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from pynput import keyboard, mouse

from src.hotkeys import canonical_hotkey, held_modifier_combo
from src.models import MacroEvent, WindowTarget
from src.win32_backend import (
    get_client_size,
    get_foreground_root_window,
    get_root_window_at_point,
    get_window_target,
    is_sensitive_window,
    is_window_matching_target,
    screen_to_client,
)

EXTENDED_VK_CODES = {
    0x21,  # VK_PRIOR (Page Up)
    0x22,  # VK_NEXT (Page Down)
    0x23,  # VK_END
    0x24,  # VK_HOME
    0x25,  # VK_LEFT
    0x26,  # VK_UP
    0x27,  # VK_RIGHT
    0x28,  # VK_DOWN
    0x2D,  # VK_INSERT
    0x2E,  # VK_DELETE
    0x6F,  # VK_DIVIDE
    0xA3,  # VK_RCONTROL
    0xA5,  # VK_RMENU
}


def extract_key_info(key: keyboard.Key | keyboard.KeyCode) -> tuple[int, str, str, bool]:
    """Extract (vk_code, key_name, printable_char, is_extended) from a pynput key."""
    if isinstance(key, keyboard.Key):
        vk = int(getattr(key.value, "vk", 0) or 0)
        name = key.name or str(key)
        char = " " if name == "space" else ""
        return vk, name, char, vk in EXTENDED_VK_CODES

    vk = int(getattr(key, "vk", 0) or 0)
    raw_char = getattr(key, "char", None) or ""
    # Control combos (e.g. Ctrl+Z) produce ASCII control codes < 32; keep char empty for those
    printable = raw_char if (len(raw_char) == 1 and ord(raw_char) >= 32) else ""
    if printable:
        name = printable
    elif 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        name = chr(vk)
    elif vk:
        name = f"VK_{vk}"
    else:
        name = str(key)
    return vk, name, printable, vk in EXTENDED_VK_CODES


def normalize_hotkey_name(key: keyboard.Key | keyboard.KeyCode) -> str:
    """Return a canonical uppercase key name (e.g. 'F9', 'ESC', 'A') for hotkey matching."""
    if isinstance(key, keyboard.Key):
        return (key.name or "").upper()
    char = getattr(key, "char", None)
    if char and len(char) == 1 and ord(char) >= 32:
        return char.upper()
    vk = getattr(key, "vk", None)
    if vk:
        return f"VK_{vk}"
    return ""


class MacroRecorder:
    """Records mouse and keyboard events tagged with window-relative coordinates."""

    def __init__(
        self,
        own_pid: Optional[int] = None,
        on_event: Optional[Callable[[MacroEvent], None]] = None,
        on_state_change: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self.own_pid = own_pid if own_pid is not None else os.getpid()
        self.on_event = on_event
        self.on_state_change = on_state_change

        self._lock = threading.Lock()
        self._recording = False
        self._start_time = 0.0
        self._events: list[MacroEvent] = []
        self._target_window: Optional[WindowTarget] = None
        self._scope: str = "target"  # "target" | "all"
        self._record_moves: bool = False
        self._ignored_hotkeys: set[str] = set()

        self._last_move_ts = 0.0
        self._last_move_pos: Optional[tuple[int, int]] = None
        self._window_cache: dict[int, WindowTarget] = {}

        self._mouse_listener: Optional[mouse.Listener] = None
        self._key_listener: Optional[keyboard.Listener] = None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def events(self) -> list[MacroEvent]:
        with self._lock:
            return list(self._events)

    def start(
        self,
        target_window: Optional[WindowTarget] = None,
        scope: str = "target",
        record_mouse_moves: bool = False,
        ignored_hotkeys: Optional[set[str]] = None,
        append: bool = False,
    ) -> None:
        """Start background mouse & keyboard recording."""
        with self._lock:
            if self._recording:
                return
            if scope == "target" and target_window is None:
                raise ValueError("Target window must be selected when scope is 'target'.")
            self._target_window = target_window
            self._scope = scope if scope in ("target", "all") else "target"
            self._record_moves = record_mouse_moves
            self._ignored_hotkeys = {canonical_hotkey(h) for h in (ignored_hotkeys or set()) if h}
            if not append:
                self._events = []
                self._start_time = time.perf_counter()
            else:
                offset = self._events[-1].timestamp + 0.1 if self._events else 0.0
                self._start_time = time.perf_counter() - offset
            self._last_move_ts = 0.0
            self._last_move_pos = None
            self._window_cache.clear()
            self._recording = True

        self._mouse_listener = mouse.Listener(
            on_move=self._handle_move,
            on_click=self._handle_click,
            on_scroll=self._handle_scroll,
        )
        self._key_listener = keyboard.Listener(
            on_press=self._handle_key_press,
            on_release=self._handle_key_release,
        )
        self._mouse_listener.start()
        self._key_listener.start()

        if self.on_state_change:
            self.on_state_change(True)

    def stop(self) -> list[MacroEvent]:
        """Stop recording and return a snapshot of recorded events."""
        with self._lock:
            if not self._recording:
                return list(self._events)
            self._recording = False
            mouse_listener = self._mouse_listener
            key_listener = self._key_listener
            self._mouse_listener = None
            self._key_listener = None
            snapshot = list(self._events)

        if mouse_listener:
            mouse_listener.stop()
        if key_listener:
            key_listener.stop()

        if self.on_state_change:
            self.on_state_change(False)
        return snapshot

    def _get_cached_target(self, hwnd: int) -> Optional[WindowTarget]:
        if not hwnd:
            return None
        cached = self._window_cache.get(hwnd)
        if cached is not None:
            return cached
        target = get_window_target(hwnd)
        if target is not None:
            self._window_cache[hwnd] = target
        return target

    def _accept_hwnd(self, hwnd: int) -> Optional[WindowTarget]:
        if not hwnd:
            return None
        target = self._get_cached_target(hwnd)
        if not target or target.pid == self.own_pid:
            return None
        if is_sensitive_window(hwnd, target.process_name):
            return None
        if self._scope == "target":
            if self._target_window is None or not is_window_matching_target(
                hwnd, self._target_window
            ):
                return None
        return target

    def _build_mouse_event(
        self, event_type: str, sx: int, sy: int, target: WindowTarget, **kwargs: object
    ) -> MacroEvent:
        rel_x, rel_y = screen_to_client(target.hwnd, sx, sy)
        cw, ch = get_client_size(target.hwnd)
        norm_x = (rel_x / cw) if cw > 0 else 0.0
        norm_y = (rel_y / ch) if ch > 0 else 0.0
        return MacroEvent(
            timestamp=round(time.perf_counter() - self._start_time, 4),
            event_type=event_type,
            target=WindowTarget(
                hwnd=target.hwnd,
                title=target.title,
                process_name=target.process_name,
                class_name=target.class_name,
                pid=target.pid,
                client_width=cw,
                client_height=ch,
            ),
            rel_x=rel_x,
            rel_y=rel_y,
            norm_x=round(norm_x, 6),
            norm_y=round(norm_y, 6),
            screen_x=int(sx),
            screen_y=int(sy),
            **kwargs,  # type: ignore[arg-type]
        )

    def _append_event(self, ev: MacroEvent) -> None:
        with self._lock:
            if not self._recording:
                return
            self._events.append(ev)
        if self.on_event:
            self.on_event(ev)

    def _handle_move(self, x: int, y: int) -> None:
        if not self._recording or not self._record_moves:
            return
        now = time.perf_counter()
        if now - self._last_move_ts < 0.025:
            return
        if self._last_move_pos is not None:
            if abs(x - self._last_move_pos[0]) < 4 and abs(y - self._last_move_pos[1]) < 4:
                return
        hwnd = get_root_window_at_point(x, y)
        target = self._accept_hwnd(hwnd)
        if not target:
            return
        self._last_move_ts = now
        self._last_move_pos = (int(x), int(y))
        self._append_event(self._build_mouse_event("mouse_move", x, y, target))

    def _handle_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        if not self._recording:
            return
        hwnd = get_root_window_at_point(x, y)
        target = self._accept_hwnd(hwnd)
        if not target:
            return
        btn_name = getattr(button, "name", "left")
        if btn_name not in ("left", "right", "middle"):
            btn_name = "left"
        ev_type = "mouse_down" if pressed else "mouse_up"
        self._append_event(self._build_mouse_event(ev_type, x, y, target, button=btn_name))

    def _handle_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        if not self._recording:
            return
        hwnd = get_root_window_at_point(x, y)
        target = self._accept_hwnd(hwnd)
        if not target:
            return
        self._append_event(
            self._build_mouse_event(
                "mouse_scroll", x, y, target, scroll_dx=int(dx), scroll_dy=int(dy)
            )
        )

    def _handle_key_event(self, key: keyboard.Key | keyboard.KeyCode, down: bool) -> None:
        if not self._recording:
            return
        base = normalize_hotkey_name(key).replace("_", "")
        if base in self._ignored_hotkeys or held_modifier_combo(base) in self._ignored_hotkeys:
            return
        hwnd = get_foreground_root_window()
        target = self._accept_hwnd(hwnd)
        if not target:
            return
        vk, key_name, char, is_ext = extract_key_info(key)
        ev = MacroEvent(
            timestamp=round(time.perf_counter() - self._start_time, 4),
            event_type="key_down" if down else "key_up",
            target=WindowTarget(
                hwnd=target.hwnd,
                title=target.title,
                process_name=target.process_name,
                class_name=target.class_name,
                pid=target.pid,
                client_width=target.client_width,
                client_height=target.client_height,
            ),
            vk_code=vk,
            key_name=key_name,
            char=char,
            is_extended=is_ext,
        )
        self._append_event(ev)

    def _handle_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        self._handle_key_event(key, down=True)

    def _handle_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        self._handle_key_event(key, down=False)

