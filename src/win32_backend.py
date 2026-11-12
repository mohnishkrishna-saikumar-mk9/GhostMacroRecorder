"""Win32 window discovery, coordinate mapping, and background/foreground input backend."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from typing import Optional

from src.models import WindowTarget

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

# Constants
GA_ROOT = 2
GW_OWNER = 4
GWL_STYLE = -16
ES_PASSWORD = 0x0020
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP = 0x8000
MOD_NOREPEAT = 0x4000
PM_NOREMOVE = 0x0000

SENSITIVE_PROCESSES = frozenset(
    {
        "consent.exe",
        "credentialuibroker.exe",
        "lockapp.exe",
        "logonui.exe",
        "keepass.exe",
        "keepassxc.exe",
        "1password.exe",
        "bitwarden.exe",
    }
)

CWP_SKIPINVISIBLE = 0x0001
CWP_SKIPDISABLED = 0x0002
CWP_SKIPTRANSPARENT = 0x0004

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010

MAPVK_VK_TO_VSC = 0
WHEEL_DELTA = 120

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

SM_CXSCREEN = 0
SM_CYSCREEN = 1

# Preferred child window classes for keyboard routing when unfocused
PREFERRED_INPUT_CHILD_CLASSES = (
    "Chrome_RenderWidgetHostHWND",
    "RichEditD2DPT",
    "Edit",
    "Windows.UI.Input.InputSite.WindowClass",
    "Scintilla",
    "DirectUIHWND",
)
NON_INPUT_OVERLAY_CLASSES = frozenset({"Intermediate D3D Window"})


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", RECT),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT_UNION)]


# Configure argtypes/restypes for safety on 64-bit Windows
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ScreenToClient.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.MapWindowPoints.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.POINTER(POINT), wintypes.UINT]
user32.MapWindowPoints.restype = ctypes.c_int
user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, POINT, wintypes.UINT]
user32.ChildWindowFromPointEx.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]
user32.PeekMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.GetKeyboardState.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
user32.GetKeyboardState.restype = wintypes.BOOL
user32.SetKeyboardState.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
user32.SetKeyboardState.restype = wintypes.BOOL

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

dwmapi.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


def enable_dpi_awareness() -> None:
    """Enable per-monitor DPI awareness so coordinates match physical screen pixels."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def pack_lparam(x: int, y: int) -> int:
    """Pack signed 16-bit (x, y) coordinates into a Win32 LPARAM."""
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def build_key_lparam(
    vk_code: int, scan_code: int = 0, is_extended: bool = False, is_up: bool = False
) -> int:
    """Construct the 32-bit lParam for WM_KEYDOWN / WM_KEYUP."""
    sc = scan_code or user32.MapVirtualKeyW(vk_code, MAPVK_VK_TO_VSC)
    lparam = 1  # repeat count = 1
    lparam |= (sc & 0xFF) << 16
    if is_extended:
        lparam |= 1 << 24
    if is_up:
        lparam |= (1 << 30) | (1 << 31)
    return lparam


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_process_info(hwnd: int) -> tuple[int, str]:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    pid_val = int(pid.value)
    if pid_val <= 0:
        return 0, ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid_val)
    if not handle:
        return pid_val, ""
    try:
        size = wintypes.DWORD(512)
        buf = ctypes.create_unicode_buffer(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return pid_val, os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return pid_val, ""


def get_client_size(hwnd: int) -> tuple[int, int]:
    rect = RECT()
    if user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return max(0, rect.right - rect.left), max(0, rect.bottom - rect.top)
    return 0, 0


def screen_to_client(hwnd: int, sx: int, sy: int) -> tuple[int, int]:
    pt = POINT(int(sx), int(sy))
    user32.ScreenToClient(hwnd, ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def client_to_screen(hwnd: int, cx: int, cy: int) -> tuple[int, int]:
    pt = POINT(int(cx), int(cy))
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def is_sensitive_window(hwnd: int, process_name: str = "") -> bool:
    """Return True if hwnd belongs to a security/password prompt or focused Win32 Edit password box."""
    proc = process_name.lower() if process_name else get_process_info(hwnd)[1].lower()
    if proc in SENSITIVE_PROCESSES:
        return True
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    if tid:
        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        if user32.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndFocus:
            # ES_PASSWORD (0x0020) is only a password style bit on standard Win32 Edit controls
            if get_class_name(gti.hwndFocus).lower() == "edit":
                style = user32.GetWindowLongW(gti.hwndFocus, GWL_STYLE)
                if style & ES_PASSWORD:
                    return True
    return False


def get_window_target(hwnd: int) -> Optional[WindowTarget]:
    """Build a WindowTarget snapshot for an existing window handle."""
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    pid, proc = get_process_info(root)
    width, height = get_client_size(root)
    return WindowTarget(
        hwnd=int(root),
        title=get_window_text(root),
        process_name=proc,
        class_name=get_class_name(root),
        pid=pid,
        client_width=width,
        client_height=height,
    )


def get_root_window_at_point(sx: int, sy: int) -> int:
    hwnd = user32.WindowFromPoint(POINT(int(sx), int(sy)))
    if not hwnd:
        return 0
    return int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)


def get_foreground_root_window() -> int:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0
    return int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)


def _is_window_cloaked(hwnd: int) -> bool:
    cloaked = wintypes.DWORD(0)
    res = dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    return res == 0 and cloaked.value != 0


def list_visible_windows(exclude_pid: Optional[int] = None) -> list[WindowTarget]:
    """Enumerate top-level visible desktop application windows."""
    results: list[WindowTarget] = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if _is_window_cloaked(hwnd):
            return True
        title = get_window_text(hwnd).strip()
        if not title or title == "Program Manager":
            return True
        cls = get_class_name(hwnd)
        if cls in ("Shell_TrayWnd", "Progman", "Windows.UI.Core.CoreWindow"):
            return True
        pid, proc = get_process_info(hwnd)
        if exclude_pid is not None and pid == exclude_pid:
            return True
        w, h = get_client_size(hwnd)
        if w <= 0 or h <= 0:
            return True
        results.append(
            WindowTarget(
                hwnd=int(hwnd),
                title=title,
                process_name=proc,
                class_name=cls,
                pid=pid,
                client_width=w,
                client_height=h,
            )
        )
        return True

    user32.EnumWindows(enum_proc_type(callback), 0)
    results.sort(key=lambda t: (t.process_name.lower(), t.title.lower()))
    return results


def is_window_matching_target(candidate_hwnd: int, target: WindowTarget) -> bool:
    """Check whether candidate_hwnd belongs to the chosen WindowTarget."""
    if not candidate_hwnd or not target:
        return False
    root = int(user32.GetAncestor(candidate_hwnd, GA_ROOT) or candidate_hwnd)
    if target.hwnd and root == target.hwnd:
        return True
    owner = user32.GetWindow(root, GW_OWNER)
    if target.hwnd and owner == target.hwnd:
        return True
    if target.hwnd and user32.IsWindow(target.hwnd):
        return False
    # If original HWND disappeared (e.g. app restarted), fall back to process + title/class
    pid, proc = get_process_info(root)
    if target.pid and pid == target.pid and proc == target.process_name:
        return True
    if target.process_name and proc.lower() == target.process_name.lower():
        if not target.title or get_window_text(root) == target.title:
            return True
    return False


def resolve_target_hwnd(target: Optional[WindowTarget], exclude_pid: Optional[int] = None) -> int:
    """Find a live HWND matching a recorded WindowTarget."""
    if not target:
        return 0
    if target.hwnd and user32.IsWindow(target.hwnd):
        return int(target.hwnd)
    windows = list_visible_windows(exclude_pid=exclude_pid)
    proc_lower = target.process_name.lower()
    # 1. Exact process + title
    for win in windows:
        if win.process_name.lower() == proc_lower and win.title == target.title:
            return win.hwnd
    # 2. Exact process + class
    for win in windows:
        if win.process_name.lower() == proc_lower and win.class_name == target.class_name:
            return win.hwnd
    # 3. Same process name
    for win in windows:
        if proc_lower and win.process_name.lower() == proc_lower:
            return win.hwnd
    return 0


def find_child_at_client_point(top_hwnd: int, rel_x: int, rel_y: int) -> tuple[int, int, int]:
    """Recursively find the deepest child window at (rel_x, rel_y) and its local coords."""
    current_hwnd = int(top_hwnd)
    cx, cy = int(rel_x), int(rel_y)
    flags = CWP_SKIPINVISIBLE | CWP_SKIPDISABLED | CWP_SKIPTRANSPARENT

    for _ in range(16):
        child = user32.ChildWindowFromPointEx(current_hwnd, POINT(cx, cy), flags)
        if not child or int(child) == current_hwnd:
            break
        pt = POINT(cx, cy)
        user32.MapWindowPoints(current_hwnd, child, ctypes.byref(pt), 1)
        current_hwnd = int(child)
        cx, cy = int(pt.x), int(pt.y)

    return current_hwnd, cx, cy


def find_keyboard_target_hwnd(
    top_hwnd: int, last_click_client: Optional[tuple[int, int]] = None
) -> int:
    """Choose the best HWND within top_hwnd to receive background keyboard messages."""
    if last_click_client is not None:
        child_hwnd, _, _ = find_child_at_client_point(
            top_hwnd, last_click_client[0], last_click_client[1]
        )
        if child_hwnd and get_class_name(child_hwnd) not in NON_INPUT_OVERLAY_CLASSES:
            return child_hwnd

    # Check GUI thread focus if available
    tid = user32.GetWindowThreadProcessId(top_hwnd, None)
    if tid:
        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        if user32.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndFocus:
            focus_root = user32.GetAncestor(gti.hwndFocus, GA_ROOT)
            if int(focus_root or 0) == int(top_hwnd):
                return int(gti.hwndFocus)

    # Search child windows for well-known input/render hosts (Chrome, Notepad, etc.)
    found: list[tuple[int, str]] = []
    enum_child_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def child_cb(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            found.append((int(hwnd), get_class_name(hwnd)))
        return True

    user32.EnumChildWindows(top_hwnd, enum_child_type(child_cb), 0)
    for preferred in PREFERRED_INPUT_CHILD_CLASSES:
        for hwnd, cls in found:
            if cls == preferred:
                return hwnd

    # Otherwise if there is a single visible child (e.g. classic Notepad Edit), use it
    if found:
        return found[0][0]
    return int(top_hwnd)


class Win32Backend:
    """Dispatches recorded events in either Background (PostMessage) or Foreground (SendInput) mode."""

    def send_background_mouse_move(
        self, top_hwnd: int, rel_x: int, rel_y: int, buttons_mask: int = 0
    ) -> bool:
        if not top_hwnd or not user32.IsWindow(top_hwnd):
            return False
        target_hwnd, cx, cy = find_child_at_client_point(top_hwnd, rel_x, rel_y)
        return bool(
            user32.PostMessageW(target_hwnd, WM_MOUSEMOVE, buttons_mask, pack_lparam(cx, cy))
        )

    def send_background_mouse_button(
        self, top_hwnd: int, rel_x: int, rel_y: int, button: str, down: bool
    ) -> bool:
        if not top_hwnd or not user32.IsWindow(top_hwnd):
            return False
        target_hwnd, cx, cy = find_child_at_client_point(top_hwnd, rel_x, rel_y)
        lp = pack_lparam(cx, cy)

        # Update hover coordinates before clicking
        user32.PostMessageW(target_hwnd, WM_MOUSEMOVE, 0, lp)

        msg_map = {
            ("left", True): (WM_LBUTTONDOWN, MK_LBUTTON),
            ("left", False): (WM_LBUTTONUP, 0),
            ("right", True): (WM_RBUTTONDOWN, MK_RBUTTON),
            ("right", False): (WM_RBUTTONUP, 0),
            ("middle", True): (WM_MBUTTONDOWN, MK_MBUTTON),
            ("middle", False): (WM_MBUTTONUP, 0),
        }
        entry = msg_map.get((button.lower(), down))
        if not entry:
            return False
        msg, wparam = entry
        return bool(user32.PostMessageW(target_hwnd, msg, wparam, lp))

    def send_background_mouse_scroll(
        self, top_hwnd: int, rel_x: int, rel_y: int, delta_y: int
    ) -> bool:
        if not top_hwnd or not user32.IsWindow(top_hwnd):
            return False
        target_hwnd, _, _ = find_child_at_client_point(top_hwnd, rel_x, rel_y)
        sx, sy = client_to_screen(top_hwnd, rel_x, rel_y)
        wheel_steps = int(delta_y * WHEEL_DELTA)
        wparam = (wheel_steps & 0xFFFF) << 16
        return bool(user32.PostMessageW(target_hwnd, WM_MOUSEWHEEL, wparam, pack_lparam(sx, sy)))

    def send_background_key(
        self,
        top_hwnd: int,
        vk_code: int,
        scan_code: int = 0,
        is_extended: bool = False,
        down: bool = True,
        char: str = "",
        last_click_client: Optional[tuple[int, int]] = None,
        ctrl_held: bool = False,
        alt_held: bool = False,
        shift_held: bool = False,
    ) -> bool:
        if not top_hwnd or not user32.IsWindow(top_hwnd):
            return False
        target_hwnd = find_keyboard_target_hwnd(top_hwnd, last_click_client=last_click_client)

        # Printable character without Ctrl/Alt: send WM_KEYDOWN directly (bypassing
        # TranslateMessage so there's no double-typing), WM_CHAR for text, and WM_KEYUP.
        if char and len(char) == 1 and ord(char) >= 32 and not ctrl_held and not alt_held:
            lp = build_key_lparam(
                vk_code or 0, scan_code=scan_code, is_extended=is_extended, is_up=not down
            )
            if down:
                if vk_code:
                    user32.SendMessageW(target_hwnd, WM_KEYDOWN, vk_code, lp)
                return bool(user32.PostMessageW(target_hwnd, WM_CHAR, ord(char), lp))
            if vk_code:
                return bool(user32.PostMessageW(target_hwnd, WM_KEYUP, vk_code, lp))
            return True

        if not vk_code:
            return False

        msg = (
            (WM_SYSKEYDOWN if alt_held else WM_KEYDOWN)
            if down
            else (WM_SYSKEYUP if alt_held else WM_KEYUP)
        )
        lp = build_key_lparam(vk_code, scan_code=scan_code, is_extended=is_extended, is_up=not down)

        # Shortcut combos (e.g. Ctrl+Z, Ctrl+A) need the target thread's GetKeyState() modifier bits set
        modifier_vks = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}
        if (ctrl_held or alt_held or shift_held) and vk_code not in modifier_vks:
            return self._send_key_with_modifiers(
                target_hwnd, msg, vk_code, lp, ctrl_held, alt_held, shift_held
            )

        return bool(user32.PostMessageW(target_hwnd, msg, vk_code, lp))

    def _send_key_with_modifiers(
        self,
        target_hwnd: int,
        msg: int,
        vk_code: int,
        lparam: int,
        ctrl_held: bool,
        alt_held: bool,
        shift_held: bool,
    ) -> bool:
        target_tid = user32.GetWindowThreadProcessId(target_hwnd, None)
        self_tid = kernel32.GetCurrentThreadId()
        attached = False
        if target_tid and self_tid and target_tid != self_tid:
            # Calling thread must have a Win32 message queue before AttachThreadInput can succeed
            dummy = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(dummy), None, 0, 0, PM_NOREMOVE)
            attached = bool(user32.AttachThreadInput(self_tid, target_tid, True))

        is_ctrl_alpha = ctrl_held and not alt_held and msg == WM_KEYDOWN and 0x41 <= vk_code <= 0x5A
        if not attached and target_tid != self_tid:
            ok = bool(user32.PostMessageW(target_hwnd, msg, vk_code, lparam))
            if is_ctrl_alpha:
                user32.PostMessageW(target_hwnd, WM_CHAR, vk_code - 64, lparam)
            return ok

        prev_state = (ctypes.c_ubyte * 256)()
        new_state = (ctypes.c_ubyte * 256)()
        user32.GetKeyboardState(prev_state)
        ctypes.memmove(new_state, prev_state, 256)
        if ctrl_held:
            new_state[0x11] = 0x80
            new_state[0xA2] = 0x80
        if alt_held:
            new_state[0x12] = 0x80
            new_state[0xA4] = 0x80
        if shift_held:
            new_state[0x10] = 0x80
            new_state[0xA0] = 0x80

        try:
            user32.SetKeyboardState(new_state)
            user32.SendMessageW(target_hwnd, msg, vk_code, lparam)
            if is_ctrl_alpha:
                user32.SendMessageW(target_hwnd, WM_CHAR, vk_code - 64, lparam)
        finally:
            user32.SetKeyboardState(prev_state)
            if attached:
                user32.AttachThreadInput(self_tid, target_tid, False)
        return True

    def activate_window(self, hwnd: int) -> bool:
        """Bring a window to the foreground for Foreground (SendInput) playback."""
        if not hwnd or not user32.IsWindow(hwnd):
            return False
        if get_foreground_root_window() == int(hwnd):
            return True
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE if minimized
        return bool(user32.SetForegroundWindow(hwnd))

    def send_foreground_mouse_move(self, sx: int, sy: int) -> bool:
        return bool(user32.SetCursorPos(int(sx), int(sy)))

    def send_foreground_mouse_button(self, sx: int, sy: int, button: str, down: bool) -> bool:
        user32.SetCursorPos(int(sx), int(sy))
        flag_map = {
            ("left", True): MOUSEEVENTF_LEFTDOWN,
            ("left", False): MOUSEEVENTF_LEFTUP,
            ("right", True): MOUSEEVENTF_RIGHTDOWN,
            ("right", False): MOUSEEVENTF_RIGHTUP,
            ("middle", True): MOUSEEVENTF_MIDDLEDOWN,
            ("middle", False): MOUSEEVENTF_MIDDLEUP,
        }
        flag = flag_map.get((button.lower(), down))
        if not flag:
            return False
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flag, time=0, dwExtraInfo=None)
        return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1

    def send_foreground_mouse_scroll(self, sx: int, sy: int, delta_y: int) -> bool:
        user32.SetCursorPos(int(sx), int(sy))
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(
            dx=0,
            dy=0,
            mouseData=wintypes.DWORD(int(delta_y * WHEEL_DELTA) & 0xFFFFFFFF),
            dwFlags=MOUSEEVENTF_WHEEL,
            time=0,
            dwExtraInfo=None,
        )
        return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1

    def send_foreground_key(
        self,
        vk_code: int,
        scan_code: int = 0,
        is_extended: bool = False,
        down: bool = True,
        char: str = "",
    ) -> bool:
        if not vk_code and char and len(char) == 1:
            flags = KEYEVENTF_UNICODE | (0 if down else KEYEVENTF_KEYUP)
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.ki = KEYBDINPUT(
                wVk=0, wScan=ord(char), dwFlags=flags, time=0, dwExtraInfo=None
            )
            return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1

        if not vk_code:
            return False
        flags = (KEYEVENTF_EXTENDEDKEY if is_extended else 0) | (0 if down else KEYEVENTF_KEYUP)
        sc = scan_code or user32.MapVirtualKeyW(vk_code, MAPVK_VK_TO_VSC)
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(wVk=vk_code, wScan=sc, dwFlags=flags, time=0, dwExtraInfo=None)
        return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1

