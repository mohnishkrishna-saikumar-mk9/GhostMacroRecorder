"""Unit tests for data models, coordinate resolution, and JSON persistence."""

from pathlib import Path

from src.app_paths import get_resource_path, get_user_data_dir
from src.models import AppSettings, Macro, MacroEvent, WindowTarget


def test_window_target_display_label_truncation() -> None:
    target = WindowTarget(
        hwnd=1234,
        title="A" * 60,
        process_name="chrome.exe",
    )
    label = target.display_label
    assert label.startswith("[chrome.exe] ")
    assert label.endswith("...")
    assert len(label) <= len("[chrome.exe] ") + 48


def test_macro_event_resolve_client_coords_scaling() -> None:
    ev = MacroEvent(
        timestamp=0.5,
        event_type="mouse_down",
        rel_x=100,
        rel_y=50,
        norm_x=0.5,
        norm_y=0.25,
        button="left",
    )
    # Scaled to a 800x400 window
    assert ev.resolve_client_coords(800, 400, scale=True) == (400, 100)
    # Unscaled uses raw client coordinates
    assert ev.resolve_client_coords(800, 400, scale=False) == (100, 50)


def test_macro_save_and_load_roundtrip(tmp_path: Path) -> None:
    target = WindowTarget(
        hwnd=999,
        title="Untitled - Notepad",
        process_name="notepad.exe",
        class_name="Notepad",
        pid=4242,
        client_width=640,
        client_height=480,
    )
    macro = Macro(
        name="demo",
        default_target=target,
        events=[
            MacroEvent(
                timestamp=0.0,
                event_type="mouse_down",
                target=target,
                rel_x=50,
                rel_y=60,
                norm_x=0.078125,
                norm_y=0.125,
                button="left",
            ),
            MacroEvent(
                timestamp=0.12,
                event_type="key_down",
                target=target,
                vk_code=0x41,
                key_name="a",
                char="a",
            ),
        ],
    )
    file_path = tmp_path / "demo.json"
    macro.save(file_path)

    loaded = Macro.load(file_path)
    assert loaded.name == "demo"
    assert loaded.duration == 0.12
    assert loaded.default_target is not None
    assert loaded.default_target.process_name == "notepad.exe"
    assert len(loaded.events) == 2
    assert loaded.events[0].summary() == ("Left Down", "Client (50, 60)")
    assert loaded.events[1].summary() == ("Key Down", "a")


def test_app_settings_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    settings = AppSettings(
        playback_mode="background",
        record_scope="target",
        speed=2.5,
        repeat_count=3,
        hotkey_record="F8",
    )
    settings.save(path)

    loaded = AppSettings.load(path)
    assert loaded.playback_mode == "background"
    assert loaded.speed == 2.5
    assert loaded.repeat_count == 3
    assert loaded.hotkey_record == "F8"


def test_app_paths_resolve_assets_and_user_dir(tmp_path: Path, monkeypatch) -> None:
    ico = get_resource_path("assets/app.ico")
    assert ico.name == "app.ico"
    assert ico.exists()

    monkeypatch.setenv("APPDATA", str(tmp_path))
    data_dir = get_user_data_dir()
    assert data_dir == tmp_path / "GhostMacroRecorder"
    assert data_dir.exists()


def test_user_dir_migrates_legacy_folder(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / "BackgroundMacroRecorder"
    legacy.mkdir()
    (legacy / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    data_dir = get_user_data_dir()
    assert (data_dir / "config.json").exists()


def test_macro_load_rejects_invalid_event_and_oversized_file(tmp_path: Path) -> None:
    import json
    import pytest

    bad_event_file = tmp_path / "bad_event.json"
    bad_event_file.write_text(
        json.dumps({"name": "bad", "events": [{"event_type": "exec_shell"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported macro event type"):
        Macro.load(bad_event_file)

    bad_btn_file = tmp_path / "bad_btn.json"
    bad_btn_file.write_text(
        json.dumps({"name": "bad", "events": [{"event_type": "mouse_down", "button": "hack"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported mouse button"):
        Macro.load(bad_btn_file)

