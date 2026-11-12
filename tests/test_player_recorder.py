"""Tests for MacroRecorder filtering/key extraction and MacroPlayer dispatch."""

import time
from unittest.mock import MagicMock

from pynput import keyboard

from src.models import AppSettings, Macro, MacroEvent, WindowTarget
from src.player import MacroPlayer
from src.recorder import MacroRecorder, extract_key_info, normalize_hotkey_name


def test_extract_key_info_variants() -> None:
    vk, name, char, ext = extract_key_info(keyboard.KeyCode.from_char("a"))
    assert name == "a"
    assert char == "a"
    assert not ext

    # Control combo like Ctrl+C / Ctrl+Z produces ASCII control codes < 32; char stays empty, readable name
    vk_c, name_c, char_c, _ = extract_key_info(keyboard.KeyCode(vk=90, char="\x1a"))
    assert vk_c == 90
    assert char_c == ""
    assert name_c == "Z"

    vk_ret, name_ret, char_ret, ext_ret = extract_key_info(keyboard.Key.enter)
    assert name_ret == "enter"
    assert char_ret == ""
    assert not ext_ret

    vk_left, name_left, _, ext_left = extract_key_info(keyboard.Key.left)
    assert name_left == "left"
    assert ext_left
    assert normalize_hotkey_name(keyboard.Key.f9) == "F9"


def test_recorder_ignores_own_pid_and_filters_target(monkeypatch) -> None:
    own_target = WindowTarget(hwnd=100, pid=9999, process_name="python.exe", title="Recorder")
    other_target = WindowTarget(hwnd=200, pid=2222, process_name="calc.exe", title="Calculator")
    wanted_target = WindowTarget(hwnd=300, pid=3333, process_name="notepad.exe", title="Notes")

    mapping = {100: own_target, 200: other_target, 300: wanted_target}
    monkeypatch.setattr("src.recorder.get_window_target", lambda hwnd: mapping.get(hwnd))
    monkeypatch.setattr(
        "src.recorder.is_window_matching_target",
        lambda hwnd, target: hwnd == target.hwnd,
    )

    rec = MacroRecorder(own_pid=9999)
    rec._target_window = wanted_target
    rec._scope = "target"

    assert rec._accept_hwnd(100) is None
    assert rec._accept_hwnd(200) is None
    assert rec._accept_hwnd(300) == wanted_target

    rec._scope = "all"
    assert rec._accept_hwnd(100) is None
    assert rec._accept_hwnd(200) == other_target


def test_recorder_requires_target_and_blocks_sensitive_windows(monkeypatch) -> None:
    import pytest
    from src.hotkeys import GlobalHotkeyManager, hotkey_name_to_vk

    rec = MacroRecorder(own_pid=9999)
    with pytest.raises(ValueError, match="Target window must be selected"):
        rec.start(target_window=None, scope="target")

    cred_target = WindowTarget(
        hwnd=400, pid=4444, process_name="CredentialUIBroker.exe", title="Windows Security"
    )
    monkeypatch.setattr("src.recorder.get_window_target", lambda hwnd: cred_target)
    monkeypatch.setattr("src.recorder.is_sensitive_window", lambda hwnd, proc="": True)
    rec._scope = "all"
    assert rec._accept_hwnd(400) is None

    assert hotkey_name_to_vk("F9") == 0x78
    assert hotkey_name_to_vk("F12") == 0x7B
    assert hotkey_name_to_vk("PAUSE") == 0x13

    mgr = GlobalHotkeyManager(lambda: None, lambda: None, lambda: None)
    mgr.set_hotkeys("F9", "F10", "F12")
    mgr.start()
    mgr.stop()


def test_player_background_and_foreground_dispatch() -> None:
    backend = MagicMock()
    target = WindowTarget(hwnd=555, process_name="notepad.exe", title="Notes")
    macro = Macro(
        default_target=target,
        events=[
            MacroEvent(
                timestamp=0.0,
                event_type="mouse_down",
                target=target,
                rel_x=40,
                rel_y=60,
                norm_x=0.5,
                norm_y=0.5,
                button="left",
            ),
            MacroEvent(
                timestamp=0.01,
                event_type="key_down",
                target=target,
                vk_code=0x11,
                key_name="ctrl",
            ),
            MacroEvent(
                timestamp=0.02,
                event_type="key_down",
                target=target,
                vk_code=0x41,
                key_name="a",
                char="a",
            ),
            MacroEvent(
                timestamp=0.03,
                event_type="key_up",
                target=target,
                vk_code=0x11,
                key_name="ctrl",
            ),
        ],
    )

    done = []
    player = MacroPlayer(
        backend=backend,
        resolve_hwnd_fn=lambda _t: 555,
        get_client_size_fn=lambda _h: (200, 100),
        client_to_screen_fn=lambda _h, x, y: (x + 10, y + 20),
        on_state_change=lambda playing, msg: done.append((playing, msg)),
    )

    settings = AppSettings(playback_mode="background", repeat_count=2, loop_delay=0.0, speed=5.0)
    assert player.start(macro, settings)

    deadline = time.time() + 3.0
    while player.is_playing and time.time() < deadline:
        time.sleep(0.02)

    assert not player.is_playing
    assert backend.send_background_mouse_button.call_count == 2
    backend.send_background_mouse_button.assert_any_call(555, 100, 50, "left", True)

    # Ctrl was held when 'a' was pressed, and last_click_client was (100, 50)
    backend.send_background_key.assert_any_call(
        555,
        vk_code=0x41,
        scan_code=0,
        is_extended=False,
        down=True,
        char="a",
        last_click_client=(100, 50),
        ctrl_held=True,
        alt_held=False,
        shift_held=False,
    )

    # Verify foreground mode also routes cleanly
    fg_settings = AppSettings(playback_mode="foreground", repeat_count=1, speed=5.0)
    assert player.start(macro, fg_settings)
    deadline = time.time() + 3.0
    while player.is_playing and time.time() < deadline:
        time.sleep(0.02)

    backend.send_foreground_mouse_button.assert_called_with(110, 70, "left", down=True)



def test_player_timed_run_loops_until_duration_ends() -> None:
    backend = MagicMock()
    target = WindowTarget(hwnd=555, title="T", process_name="t.exe", client_width=200, client_height=100)
    macro = Macro(
        events=[
            MacroEvent(timestamp=0.0, event_type="key_down", target=target, vk_code=0x41, key_name="a"),
            MacroEvent(timestamp=0.1, event_type="key_up", target=target, vk_code=0x41, key_name="a"),
        ]
    )
    done = []
    player = MacroPlayer(
        backend=backend,
        resolve_hwnd_fn=lambda _t: 555,
        get_client_size_fn=lambda _h: (200, 100),
        client_to_screen_fn=lambda _h, x, y: (x, y),
        on_state_change=lambda playing, msg: done.append((playing, msg)),
    )
    # repeat_count=1 must be ignored in time mode: ~0.15s per loop over 1s => several loops
    settings = AppSettings(
        playback_mode="background", repeat_count=1, loop_delay=0.05, run_limit_mode="time", run_duration=1.0
    )
    started = time.monotonic()
    assert player.start(macro, settings)
    while player.is_playing and time.monotonic() - started < 4.0:
        time.sleep(0.02)
    elapsed = time.monotonic() - started

    assert not player.is_playing
    assert 0.9 <= elapsed < 1.6
    assert backend.send_background_key.call_count >= 8  # >= 4 full loops of 2 keys
    assert done[-1][0] is False and "Time limit reached" in done[-1][1]
