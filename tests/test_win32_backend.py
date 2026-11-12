"""Tests for Win32 coordinate packing, key lParam, and real background PostMessage delivery."""

import tkinter as tk

import pytest

from src.win32_backend import (
    Win32Backend,
    build_key_lparam,
    list_visible_windows,
    pack_lparam,
)


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


def test_pack_lparam_positive_and_negative() -> None:
    assert pack_lparam(10, 20) == (20 << 16) | 10
    lp = pack_lparam(-5, -10)
    x = lp & 0xFFFF
    y = (lp >> 16) & 0xFFFF
    assert x == ((-5) & 0xFFFF)
    assert y == ((-10) & 0xFFFF)


def test_build_key_lparam_flags() -> None:
    down_lp = build_key_lparam(0x25, scan_code=0x4B, is_extended=True, is_up=False)
    assert (down_lp & 0xFFFF) == 1
    assert ((down_lp >> 16) & 0xFF) == 0x4B
    assert bool(down_lp & (1 << 24))
    assert not bool(down_lp & (1 << 31))

    up_lp = build_key_lparam(0x25, scan_code=0x4B, is_extended=True, is_up=True)
    assert bool(up_lp & (1 << 30))
    assert bool(up_lp & (1 << 31))


def test_list_visible_windows_returns_list() -> None:
    windows = list_visible_windows()
    assert isinstance(windows, list)


def test_background_postmessage_click_and_typing_to_real_window(tk_root: tk.Tk) -> None:
    """Verify PostMessage delivers click + text into real unfocused Win32 child controls."""
    import ctypes
    from src.win32_backend import user32

    WS_CHILD = 0x40000000
    WS_VISIBLE = 0x10000000
    WS_BORDER = 0x00800000
    BS_AUTOCHECKBOX = 0x0003
    BM_GETCHECK = 0x00F0
    BST_CHECKED = 1
    WM_GETTEXT = 0x000D

    root = tk.Toplevel(tk_root)
    root.geometry("320x160+40+40")
    root.title("MacroTestTarget")
    root.lower()
    root.update()

    hwnd = int(root.wm_frame(), 16)
    client_hwnd = root.winfo_id()
    checkbox_hwnd = user32.CreateWindowExW(
        0,
        "BUTTON",
        "CheckMe",
        WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
        20,
        20,
        140,
        30,
        client_hwnd,
        None,
        None,
        None,
    )
    edit_hwnd = user32.CreateWindowExW(
        0,
        "EDIT",
        "",
        WS_CHILD | WS_VISIBLE | WS_BORDER,
        20,
        70,
        200,
        30,
        client_hwnd,
        None,
        None,
        None,
    )
    assert checkbox_hwnd and edit_hwnd

    backend = Win32Backend()
    try:
        # Click inside checkbox (at 50, 35 in top-level client coords) while unfocused
        assert backend.send_background_mouse_button(hwnd, 50, 35, "left", down=True)
        assert backend.send_background_mouse_button(hwnd, 50, 35, "left", down=False)

        # Click inside edit control (at 50, 85) and type "hi" in background
        assert backend.send_background_mouse_button(hwnd, 50, 85, "left", down=True)
        assert backend.send_background_mouse_button(hwnd, 50, 85, "left", down=False)
        for ch in "hi":
            assert backend.send_background_key(
                hwnd,
                vk_code=ord(ch.upper()),
                down=True,
                char=ch,
                last_click_client=(50, 85),
            )
            assert backend.send_background_key(
                hwnd,
                vk_code=ord(ch.upper()),
                down=False,
                char=ch,
                last_click_client=(50, 85),
            )

        for _ in range(10):
            root.update()

        checked = user32.SendMessageW(checkbox_hwnd, BM_GETCHECK, 0, 0)
        assert checked == BST_CHECKED, "Expected background click to toggle Win32 checkbox"

        buf = ctypes.create_unicode_buffer(64)
        user32.SendMessageW(edit_hwnd, WM_GETTEXT, 64, ctypes.addressof(buf))
        assert buf.value == "hi", f"Expected 'hi' in Win32 EDIT control, got {buf.value!r}"
    finally:
        root.destroy()


def test_end_to_end_macro_save_load_and_background_playback(tk_root: tk.Tk, tmp_path) -> None:
    """End-to-end: save Macro -> load JSON -> play via MacroPlayer into unfocused Win32 controls."""
    import ctypes
    import time
    from src.models import AppSettings, Macro, MacroEvent, WindowTarget
    from src.player import MacroPlayer
    from src.win32_backend import user32

    WS_CHILD = 0x40000000
    WS_VISIBLE = 0x10000000
    WS_BORDER = 0x00800000
    BS_AUTOCHECKBOX = 0x0003
    BM_GETCHECK = 0x00F0
    BST_CHECKED = 1
    WM_GETTEXT = 0x000D

    root = tk.Toplevel(tk_root)
    root.geometry("320x160+40+40")
    root.title("MacroE2ETarget")
    root.lower()
    root.update()

    hwnd = int(root.wm_frame(), 16)
    client_hwnd = root.winfo_id()
    checkbox_hwnd = user32.CreateWindowExW(
        0, "BUTTON", "Agree", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
        20, 20, 140, 30, client_hwnd, None, None, None,
    )
    edit_hwnd = user32.CreateWindowExW(
        0, "EDIT", "", WS_CHILD | WS_VISIBLE | WS_BORDER,
        20, 70, 200, 30, client_hwnd, None, None, None,
    )

    try:
        target = WindowTarget(hwnd=hwnd, title="MacroE2ETarget", process_name="python.exe")
        macro = Macro(
            name="e2e_test",
            default_target=target,
            events=[
                MacroEvent(timestamp=0.0, event_type="mouse_down", rel_x=50, rel_y=35, button="left"),
                MacroEvent(timestamp=0.01, event_type="mouse_up", rel_x=50, rel_y=35, button="left"),
                MacroEvent(timestamp=0.02, event_type="mouse_down", rel_x=50, rel_y=85, button="left"),
                MacroEvent(timestamp=0.03, event_type="mouse_up", rel_x=50, rel_y=85, button="left"),
                MacroEvent(timestamp=0.04, event_type="key_down", vk_code=ord("O"), key_name="o", char="o"),
                MacroEvent(timestamp=0.05, event_type="key_up", vk_code=ord("O"), key_name="o", char="o"),
                MacroEvent(timestamp=0.06, event_type="key_down", vk_code=ord("K"), key_name="k", char="k"),
                MacroEvent(timestamp=0.07, event_type="key_up", vk_code=ord("K"), key_name="k", char="k"),
            ],
        )
        macro_path = tmp_path / "e2e.json"
        macro.save(macro_path)
        loaded = Macro.load(macro_path)

        player = MacroPlayer()
        settings = AppSettings(playback_mode="background", scale_coordinates=False, repeat_count=1, speed=4.0)
        assert player.start(loaded, settings)

        deadline = time.time() + 3.0
        while player.is_playing and time.time() < deadline:
            root.update()
            time.sleep(0.01)
        for _ in range(10):
            root.update()

        assert not player.is_playing
        assert user32.SendMessageW(checkbox_hwnd, BM_GETCHECK, 0, 0) == BST_CHECKED

        buf = ctypes.create_unicode_buffer(64)
        user32.SendMessageW(edit_hwnd, WM_GETTEXT, 64, ctypes.addressof(buf))
        assert buf.value == "ok"
    finally:
        root.destroy()


def test_is_sensitive_window_only_checks_edit_password_style(monkeypatch) -> None:
    import ctypes
    from src.win32_backend import ES_PASSWORD, is_sensitive_window, user32

    assert is_sensitive_window(0, "CredentialUIBroker.exe") is True

    monkeypatch.setattr("src.win32_backend.get_process_info", lambda _h: (1, "chrome.exe"))
    monkeypatch.setattr(user32, "GetWindowThreadProcessId", lambda _h, _p: 42)
    monkeypatch.setattr(user32, "GetWindowLongW", lambda _h, _idx: ES_PASSWORD)

    def fake_gui_info(_tid, p_info):
        gti = ctypes.cast(p_info, ctypes.POINTER(type(p_info._obj))).contents if hasattr(p_info, "_obj") else None
        if gti is not None:
            gti.hwndFocus = 1234
            return True
        return False

    monkeypatch.setattr(user32, "GetGUIThreadInfo", fake_gui_info)

    # Non-Edit control with style bit 0x0020 must NOT block recording
    monkeypatch.setattr("src.win32_backend.get_class_name", lambda _h: "Chrome_RenderWidgetHostHWND")
    assert is_sensitive_window(99, "chrome.exe") is False

    # Standard Win32 Edit control with ES_PASSWORD (0x0020) MUST block recording
    monkeypatch.setattr("src.win32_backend.get_class_name", lambda _h: "Edit")
    assert is_sensitive_window(99, "notepad.exe") is True


def test_background_ctrl_z_undo_across_processes() -> None:
    """Verify MacroPlayer replays Ctrl+Z undo into a separate unfocused background process."""
    import subprocess
    import sys
    import time
    from src.models import AppSettings, Macro, MacroEvent, WindowTarget
    from src.player import MacroPlayer

    child_code = (
        "import ctypes, tkinter as tk; "
        "from src.win32_backend import user32; "
        "r=tk.Tk(); r.geometry('260x100+40+40'); r.lower(); r.update(); "
        "f=int(r.wm_frame(),16); c=r.winfo_id(); "
        "ed=user32.CreateWindowExW(0,'EDIT','',0x50000000|0x00800000,10,10,200,30,c,None,None,None); "
        "print(f, flush=True); "
        "r.after(1800, r.quit); r.mainloop(); "
        "buf=ctypes.create_unicode_buffer(64); "
        "user32.SendMessageW(ed, 0x000D, 64, ctypes.addressof(buf)); "
        "print(buf.value, flush=True)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", child_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        top_hwnd = int(proc.stdout.readline().strip())
        target = WindowTarget(hwnd=top_hwnd, process_name="python.exe")
        macro = Macro(
            default_target=target,
            events=[
                MacroEvent(timestamp=0.0, event_type="mouse_down", rel_x=50, rel_y=25, button="left"),
                MacroEvent(timestamp=0.01, event_type="mouse_up", rel_x=50, rel_y=25, button="left"),
                MacroEvent(timestamp=0.02, event_type="key_down", vk_code=ord("A"), key_name="a", char="a"),
                MacroEvent(timestamp=0.03, event_type="key_up", vk_code=ord("A"), key_name="a", char="a"),
                MacroEvent(timestamp=0.04, event_type="key_down", vk_code=ord("B"), key_name="b", char="b"),
                MacroEvent(timestamp=0.05, event_type="key_up", vk_code=ord("B"), key_name="b", char="b"),
                MacroEvent(timestamp=0.10, event_type="key_down", vk_code=0xA2, key_name="ctrl_l"),
                MacroEvent(timestamp=0.11, event_type="key_down", vk_code=0x5A, key_name="Z"),
                MacroEvent(timestamp=0.12, event_type="key_up", vk_code=0x5A, key_name="Z"),
                MacroEvent(timestamp=0.13, event_type="key_up", vk_code=0xA2, key_name="ctrl_l"),
            ],
        )
        player = MacroPlayer()
        settings = AppSettings(playback_mode="background", scale_coordinates=False, repeat_count=1, speed=2.0)
        assert player.start(macro, settings)
        deadline = time.time() + 3.0
        while player.is_playing and time.time() < deadline:
            time.sleep(0.02)
        out, err = proc.communicate(timeout=5)
        assert err == ""
        assert out.strip() == ""
    finally:
        if proc.poll() is None:
            proc.kill()

