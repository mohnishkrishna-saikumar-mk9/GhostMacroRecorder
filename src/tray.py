"""System tray icon integration so the macro recorder can run unobtrusively."""

from __future__ import annotations

import threading
from typing import Callable, Optional

from PIL import Image, ImageDraw
import pystray

from src.app_paths import APP_NAME, get_resource_path
from src.icons import tray_icon_handle


_BASE_ICON: Optional[Image.Image] = None


def _base_icon() -> Image.Image:
    global _BASE_ICON
    if _BASE_ICON is None:
        try:
            _BASE_ICON = (
                Image.open(get_resource_path("assets/icon_small.png")).convert("RGBA").resize((64, 64), Image.LANCZOS)
            )
        except Exception:
            _BASE_ICON = Image.new("RGBA", (64, 64), (17, 8, 42, 255))
    return _BASE_ICON


def _build_tray_icon(state: str = "idle") -> Image.Image:
    """Ghost icon with a status badge: red dot while recording, green while playing."""
    img = _base_icon().copy()
    badge = {"recording": (255, 77, 79, 255), "playing": (61, 220, 151, 255)}.get(state)
    if badge:
        draw = ImageDraw.Draw(img)
        draw.ellipse((38, 38, 63, 63), fill=(17, 8, 42, 255))
        draw.ellipse((42, 42, 59, 59), fill=badge)
    return img


class _GhostTrayIcon(pystray.Icon):
    """pystray icon that loads our multi-size .ico at the exact tray size (no blur)."""

    ghost_state = "idle"

    def _assert_icon_handle(self):  # noqa: D401 - pystray internal hook (Windows backend)
        if getattr(self, "_icon_handle", None):
            return
        try:
            handle = tray_icon_handle(self.ghost_state)
        except Exception:
            handle = 0
        if handle:
            self._icon_handle = handle
        else:
            super()._assert_icon_handle()


class TrayController:
    """Manages a background system tray icon and quick-action menu."""

    def __init__(
        self,
        on_show: Callable[[], None],
        on_toggle_record: Callable[[], None],
        on_toggle_play: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self.on_show = on_show
        self.on_toggle_record = on_toggle_record
        self.on_toggle_play = on_toggle_play
        self.on_exit = on_exit
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        self._state = "idle"

    def start(self) -> None:
        if self._icon is not None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show Window", lambda _icon, _item: self.on_show(), default=True),
            pystray.MenuItem("Record / Stop", lambda _icon, _item: self.on_toggle_record()),
            pystray.MenuItem("Play / Stop", lambda _icon, _item: self.on_toggle_play()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda _icon, _item: self.on_exit()),
        )
        self._icon = _GhostTrayIcon(
            "ghost_macro_recorder",
            _build_tray_icon(self._state),
            APP_NAME,
            menu=menu,
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def set_state(self, state: str, tooltip: str = "") -> None:
        self._state = state
        if self._icon is not None:
            self._icon.ghost_state = state
            self._icon.icon = _build_tray_icon(state)
            self._icon.title = tooltip or f"{APP_NAME} ({state.capitalize()})"

    def notify(self, title: str, message: str) -> None:
        """Windows toast from the tray icon (used when a long run finishes)."""
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None

