"""Crisp app icons everywhere: window title bar, taskbar, Alt+Tab and tray.

Some toolkits hand Windows a single icon image that Windows then
stretches, which looks blurry on high-DPI screens. Here we load the multi-size
assets/app.ico at the *exact* pixel size Windows wants for the current DPI.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile
from typing import Optional

from PIL import Image, ImageDraw

from src.app_paths import get_resource_path

user32 = ctypes.WinDLL("user32", use_last_error=True)

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
WM_SETICON = 0x0080
ICON_SMALL, ICON_BIG = 0, 1
SM_CXICON, SM_CXSMICON = 11, 49
GCLP_HICON, GCLP_HICONSM = -14, -34

user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.DestroyIcon.argtypes = [wintypes.HANDLE]
try:
    user32.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetClassLongPtrW.restype = ctypes.c_size_t
except AttributeError:  # 32-bit Python
    pass

ICO_PATH: Path = get_resource_path("assets/app.ico")
_handles: dict[tuple[str, int], int] = {}  # keep HICONs alive for the app's lifetime

# Status badge colours for the tray (recording / playing)
BADGES = {"recording": (255, 77, 79, 255), "playing": (61, 220, 151, 255)}


def _dpi_for(hwnd: Optional[int] = None) -> int:
    try:
        if hwnd:
            dpi = user32.GetDpiForWindow(wintypes.HWND(hwnd))
            if dpi:
                return int(dpi)
        return int(user32.GetDpiForSystem()) or 96
    except Exception:
        return 96


def _metric(index: int, dpi: int) -> int:
    try:
        return int(user32.GetSystemMetricsForDpi(index, dpi))
    except Exception:
        return int(user32.GetSystemMetrics(index))


def load_icon(size: int, path: Optional[Path] = None) -> int:
    """HICON of exactly `size` px from a multi-size .ico (cached)."""
    path = path or ICO_PATH
    key = (str(path), size)
    if key not in _handles:
        _handles[key] = user32.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE) or 0
    return _handles[key]


def apply_window_icons(hwnd: int) -> None:
    """Give a top-level window crisp small (title bar) and big (taskbar/Alt+Tab) icons."""
    if not hwnd or not ICO_PATH.exists():
        return
    dpi = _dpi_for(hwnd)
    small = load_icon(_metric(SM_CXSMICON, dpi))
    big = load_icon(_metric(SM_CXICON, dpi))
    if small:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
    if big:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
    # Also set the window-class icon, so any other Tk window (popups, dialogs)
    # falls back to the ghost instead of the Tk / CustomTkinter logo.
    try:
        if big:
            user32.SetClassLongPtrW(hwnd, GCLP_HICON, big)
        if small:
            user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, small)
    except Exception:
        pass


def tray_icon_size() -> int:
    return _metric(SM_CXSMICON, _dpi_for())


def build_state_ico(state: str) -> Path:
    """Write a multi-size .ico of the ghost with a status badge; returns its path (cached per state)."""
    out = Path(tempfile.gettempdir()) / f"GhostMacroRecorder-tray-{state}.ico"
    if out.exists() and out.stat().st_mtime >= ICO_PATH.stat().st_mtime:
        return out
    base = Image.open(ICO_PATH)
    sizes = sorted(s for s in base.info.get("sizes", [(32, 32)]) if s[0] <= 64)
    frames = []
    for size in sizes:
        base.size = size
        frame = base.copy().convert("RGBA")
        frame.load()
        badge = BADGES.get(state)
        if badge:
            px = size[0]
            d = max(5, round(px * 0.42))
            ring = max(1, round(px * 0.07))
            draw = ImageDraw.Draw(frame)
            draw.ellipse((px - d, px - d, px - 1, px - 1), fill=(16, 17, 20, 255))
            draw.ellipse((px - d + ring, px - d + ring, px - 1 - ring, px - 1 - ring), fill=badge)
        frames.append(frame)
    tmp = out.with_suffix(f".{os.getpid()}.tmp")
    frames[-1].save(tmp, format="ICO", sizes=[f.size for f in frames], append_images=frames[:-1])
    os.replace(tmp, out)
    return out


def tray_icon_handle(state: str) -> int:
    """A *fresh* HICON for the tray (the caller owns and destroys it)."""
    path = build_state_ico(state)
    size = tray_icon_size()
    return user32.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE) or 0
