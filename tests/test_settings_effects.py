"""Every playback setting does what the UI says it does.

Each test plays a tiny macro through a fake input backend (nothing touches the
real mouse or keyboard) and measures the effect of one setting.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from src.models import AppSettings, Macro, MacroEvent, WindowTarget
from src.player import MacroPlayer

TARGET = WindowTarget(hwnd=555, title="T", process_name="t.exe", client_width=200, client_height=100)


def key_macro(span: float = 0.2) -> Macro:
    """Two key presses `span` seconds apart."""
    return Macro(
        events=[
            MacroEvent(timestamp=0.0, event_type="key_down", target=TARGET, vk_code=0x41, key_name="a"),
            MacroEvent(timestamp=span, event_type="key_up", target=TARGET, vk_code=0x41, key_name="a"),
        ]
    )


def run(macro: Macro, client_size=(200, 100), timeout: float = 6.0, **overrides):
    """Play `macro` with the given setting overrides; return (backend, seconds, final message)."""
    backend = MagicMock()
    done: list[tuple[bool, str]] = []
    player = MacroPlayer(
        backend=backend,
        resolve_hwnd_fn=lambda _t: 555,
        get_client_size_fn=lambda _h: client_size,
        client_to_screen_fn=lambda _h, x, y: (x, y),
        on_state_change=lambda playing, msg: done.append((playing, msg)),
    )
    settings = AppSettings(**{"loop_delay": 0.0, "repeat_count": 1, **overrides})
    start = time.monotonic()
    assert player.start(macro, settings)
    while player.is_playing and time.monotonic() - start < timeout:
        time.sleep(0.01)
    elapsed = time.monotonic() - start
    if player.is_playing:
        player.stop()
    return backend, elapsed, done[-1][1] if done else ""


def keys_sent(backend) -> int:
    return backend.send_background_key.call_count + backend.send_foreground_key.call_count


# --- Play tab -------------------------------------------------------------
def test_engine_background_never_touches_real_input() -> None:
    backend, _, _ = run(key_macro(0.0), playback_mode="background")
    assert backend.send_background_key.call_count == 2
    assert backend.send_foreground_key.call_count == 0


def test_engine_foreground_uses_real_input() -> None:
    backend, _, _ = run(key_macro(0.0), playback_mode="foreground")
    assert backend.send_foreground_key.call_count == 2
    assert backend.send_background_key.call_count == 0


@pytest.mark.parametrize("speed, expected", [(1.0, 0.4), (4.0, 0.1)])
def test_speed_scales_playback_time(speed: float, expected: float) -> None:
    _, elapsed, _ = run(key_macro(0.4), speed=speed)
    assert expected * 0.8 <= elapsed <= expected + 0.25


def test_humanize_varies_each_wait(monkeypatch) -> None:
    # Force the random factor to its maximum (+15%) and check the wait grows by that much
    monkeypatch.setattr("src.player.random.uniform", lambda lo, hi: hi)
    _, plain, _ = run(key_macro(0.5), humanize_pct=0)
    _, human, _ = run(key_macro(0.5), humanize_pct=15)
    assert human - plain == pytest.approx(0.075, abs=0.05)


# --- Repeat tab -----------------------------------------------------------
def test_repeat_count_plays_exactly_n_times() -> None:
    backend, _, msg = run(key_macro(0.0), repeat_count=3)
    assert keys_sent(backend) == 6
    assert msg == "Playback complete."


def test_repeat_zero_means_forever_until_stopped() -> None:
    backend, elapsed, _ = run(key_macro(0.02), repeat_count=0, timeout=0.5)
    assert elapsed >= 0.5  # still going when we stopped it
    assert keys_sent(backend) > 6


def test_wait_between_runs_is_applied() -> None:
    _, elapsed, _ = run(key_macro(0.0), repeat_count=3, loop_delay=0.2)
    assert elapsed >= 0.38  # two gaps of 0.2 s between three runs


def test_run_for_time_stops_on_its_own() -> None:
    _, elapsed, msg = run(key_macro(0.05), run_limit_mode="time", run_duration=1.0, repeat_count=1)
    assert 0.9 <= elapsed < 1.5
    assert msg.startswith("Time limit reached")


# --- Record tab: "Adjust if the window is resized" --------------------------
def click_macro() -> Macro:
    return Macro(
        events=[
            MacroEvent(timestamp=0.0, event_type="mouse_down", target=TARGET, button="left",
                       rel_x=100, rel_y=50, norm_x=0.5, norm_y=0.5),
        ]
    )


def test_scale_on_resize_moves_click_with_window() -> None:
    backend, _, _ = run(click_macro(), client_size=(400, 200), scale_coordinates=True)
    backend.send_background_mouse_button.assert_called_with(555, 200, 100, "left", True)


def test_scale_off_keeps_original_pixels() -> None:
    backend, _, _ = run(click_macro(), client_size=(400, 200), scale_coordinates=False)
    backend.send_background_mouse_button.assert_called_with(555, 100, 50, "left", True)
