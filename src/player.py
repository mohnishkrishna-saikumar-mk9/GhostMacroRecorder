"""Background and foreground macro playback engine."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from src.models import AppSettings, Macro, MacroEvent, WindowTarget
from src.win32_backend import (
    MK_LBUTTON,
    MK_MBUTTON,
    MK_RBUTTON,
    Win32Backend,
    client_to_screen,
    get_client_size,
    resolve_target_hwnd,
)

CTRL_VKS = {0x11, 0xA2, 0xA3}  # VK_CONTROL, VK_LCONTROL, VK_RCONTROL
ALT_VKS = {0x12, 0xA4, 0xA5}   # VK_MENU, VK_LMENU, VK_RMENU
SHIFT_VKS = {0x10, 0xA0, 0xA1}  # VK_SHIFT, VK_LSHIFT, VK_RSHIFT
BUTTON_MASK = {"left": MK_LBUTTON, "right": MK_RBUTTON, "middle": MK_MBUTTON}


class MacroPlayer:
    """Replays recorded MacroEvents into target windows in the background or foreground."""

    def __init__(
        self,
        backend: Optional[Win32Backend] = None,
        resolve_hwnd_fn: Callable[[Optional[WindowTarget]], int] = resolve_target_hwnd,
        get_client_size_fn: Callable[[int], tuple[int, int]] = get_client_size,
        client_to_screen_fn: Callable[[int, int, int], tuple[int, int]] = client_to_screen,
        on_progress: Optional[Callable[[int, int, int, int], None]] = None,
        on_state_change: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        self.backend = backend or Win32Backend()
        self._resolve_hwnd = resolve_hwnd_fn
        self._get_client_size = get_client_size_fn
        self._client_to_screen = client_to_screen_fn
        self.on_progress = on_progress
        self.on_state_change = on_state_change

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._playing = False

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def start(
        self,
        macro: Macro,
        settings: AppSettings,
        override_target: Optional[WindowTarget] = None,
    ) -> bool:
        """Start asynchronous macro playback. Returns False if macro is empty or already playing."""
        if not macro.events:
            if self.on_state_change:
                self.on_state_change(False, "No recorded events to play.")
            return False

        with self._lock:
            if self._playing:
                return False
            self._stop_event.clear()
            self._playing = True

        self._thread = threading.Thread(
            target=self._run_loop,
            args=(macro, settings, override_target),
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Request immediate playback stop."""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=1.0)

    def _resolve_event_hwnd(
        self,
        ev: MacroEvent,
        default_target: Optional[WindowTarget],
        override_target: Optional[WindowTarget],
        hwnd_cache: dict[tuple[int, str, str], int],
    ) -> int:
        target = override_target or ev.target or default_target
        if not target:
            return 0
        key = (target.hwnd, target.process_name, target.title)
        if key not in hwnd_cache:
            hwnd_cache[key] = self._resolve_hwnd(target)
        return hwnd_cache[key]

    def _run_loop(
        self,
        macro: Macro,
        settings: AppSettings,
        override_target: Optional[WindowTarget],
    ) -> None:
        mode_label = "Background" if settings.playback_mode == "background" else "Foreground"
        if self.on_state_change:
            self.on_state_change(True, f"Playing ({mode_label})...")

        timed = settings.run_limit_mode == "time"
        # A timed run loops until the clock runs out, so the loop count is open-ended.
        total_loops = 0 if timed else settings.repeat_count  # 0 means infinite
        deadline = time.monotonic() + max(1.0, float(settings.run_duration)) if timed else None
        loop_idx = 0
        events = list(macro.events)
        total_events = len(events)
        speed = max(0.05, float(settings.speed))
        status_msg = "Playback complete."

        try:
            while not self._stop_event.is_set():
                loop_idx += 1
                if total_loops > 0 and loop_idx > total_loops:
                    break

                hwnd_cache: dict[tuple[int, str, str], int] = {}
                last_click_by_hwnd: dict[int, tuple[int, int]] = {}
                ctrl_held = False
                alt_held = False
                shift_held = False
                buttons_mask = 0
                prev_ts = events[0].timestamp

                for idx, ev in enumerate(events):
                    if self._stop_event.is_set():
                        break

                    delta = max(0.0, ev.timestamp - prev_ts) / speed
                    prev_ts = ev.timestamp
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= delta:
                            # Not enough time left for this step: wait out the clock and finish.
                            if remaining > 0:
                                self._stop_event.wait(timeout=remaining)
                            break
                    if delta > 0 and self._stop_event.wait(timeout=delta):
                        break

                    if ev.event_type in ("key_down", "key_up"):
                        is_down = ev.event_type == "key_down"
                        if ev.vk_code in CTRL_VKS:
                            ctrl_held = is_down
                        elif ev.vk_code in ALT_VKS:
                            alt_held = is_down
                        elif ev.vk_code in SHIFT_VKS:
                            shift_held = is_down
                    elif ev.event_type in ("mouse_down", "mouse_up"):
                        bit = BUTTON_MASK.get((ev.button or "left").lower(), 0)
                        if ev.event_type == "mouse_down":
                            buttons_mask |= bit
                        else:
                            buttons_mask &= ~bit

                    hwnd = self._resolve_event_hwnd(
                        ev, macro.default_target, override_target, hwnd_cache
                    )
                    self._dispatch_event(
                        ev=ev,
                        hwnd=hwnd,
                        settings=settings,
                        last_click_by_hwnd=last_click_by_hwnd,
                        ctrl_held=ctrl_held,
                        alt_held=alt_held,
                        shift_held=shift_held,
                        buttons_mask=buttons_mask,
                    )

                    if self.on_progress:
                        self.on_progress(loop_idx, total_loops, idx + 1, total_events)

                if self._stop_event.is_set():
                    status_msg = "Playback stopped."
                    break

                if deadline is not None and time.monotonic() >= deadline - 1e-3:
                    status_msg = f"Time limit reached after {loop_idx} loop(s)."
                    break

                if total_loops == 0 or loop_idx < total_loops:
                    gap = settings.loop_delay
                    if deadline is not None:
                        gap = min(gap, max(0.0, deadline - time.monotonic()))
                    if gap > 0 and self._stop_event.wait(timeout=gap):
                        status_msg = "Playback stopped."
                        break
            if self._stop_event.is_set():
                status_msg = "Playback stopped."
        except Exception as exc:
            status_msg = f"Playback error: {exc}"
        finally:
            with self._lock:
                self._playing = False
            if self.on_state_change:
                self.on_state_change(False, status_msg)

    def _dispatch_event(
        self,
        ev: MacroEvent,
        hwnd: int,
        settings: AppSettings,
        last_click_by_hwnd: dict[int, tuple[int, int]],
        ctrl_held: bool,
        alt_held: bool,
        shift_held: bool = False,
        buttons_mask: int = 0,
    ) -> None:
        cw, ch = self._get_client_size(hwnd) if hwnd else (0, 0)
        cx, cy = ev.resolve_client_coords(cw, ch, scale=settings.scale_coordinates)

        if settings.playback_mode == "background":
            if not hwnd:
                return
            if ev.event_type == "mouse_move":
                self.backend.send_background_mouse_move(hwnd, cx, cy, buttons_mask=buttons_mask)
            elif ev.event_type in ("mouse_down", "mouse_up"):
                is_down = ev.event_type == "mouse_down"
                if is_down:
                    last_click_by_hwnd[hwnd] = (cx, cy)
                self.backend.send_background_mouse_button(hwnd, cx, cy, ev.button or "left", is_down)
            elif ev.event_type == "mouse_scroll":
                self.backend.send_background_mouse_scroll(hwnd, cx, cy, ev.scroll_dy)
            elif ev.event_type in ("key_down", "key_up"):
                self.backend.send_background_key(
                    hwnd,
                    vk_code=ev.vk_code,
                    scan_code=ev.scan_code,
                    is_extended=ev.is_extended,
                    down=(ev.event_type == "key_down"),
                    char=ev.char,
                    last_click_client=last_click_by_hwnd.get(hwnd),
                    ctrl_held=ctrl_held,
                    alt_held=alt_held,
                    shift_held=shift_held,
                )
            return

        # Foreground fallback (SendInput)
        if hwnd:
            self.backend.activate_window(hwnd)
            sx, sy = self._client_to_screen(hwnd, cx, cy)
        else:
            sx, sy = ev.screen_x, ev.screen_y

        if ev.event_type == "mouse_move":
            self.backend.send_foreground_mouse_move(sx, sy)
        elif ev.event_type in ("mouse_down", "mouse_up"):
            self.backend.send_foreground_mouse_button(
                sx, sy, ev.button or "left", down=(ev.event_type == "mouse_down")
            )
        elif ev.event_type == "mouse_scroll":
            self.backend.send_foreground_mouse_scroll(sx, sy, ev.scroll_dy)
        elif ev.event_type in ("key_down", "key_up"):
            self.backend.send_foreground_key(
                vk_code=ev.vk_code,
                scan_code=ev.scan_code,
                is_extended=ev.is_extended,
                down=(ev.event_type == "key_down"),
                char=ev.char,
            )

