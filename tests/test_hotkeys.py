"""Tests for hotkey name parsing (combos, display names, virtual-key codes)."""

from src.hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    canonical_hotkey,
    display_hotkey,
    hotkey_modifiers,
    hotkey_name_to_vk,
)


def test_canonical_orders_modifiers_and_uppercases() -> None:
    assert canonical_hotkey("shift+ctrl+r") == "CTRL+SHIFT+R"
    assert canonical_hotkey(" f9 ") == "F9"
    assert canonical_hotkey("alt + page_up") == "ALT+PAGEUP"
    assert canonical_hotkey("") == ""


def test_vk_and_modifiers_for_combos() -> None:
    assert hotkey_name_to_vk("F9") == 0x78
    assert hotkey_name_to_vk("F24") == 0x87
    assert hotkey_name_to_vk("CTRL+SHIFT+R") == ord("R")
    assert hotkey_name_to_vk("CTRL+PAGEDOWN") == 0x22
    assert hotkey_name_to_vk("NOT_A_KEY") == 0
    assert hotkey_modifiers("F9") == 0
    assert hotkey_modifiers("CTRL+ALT+SHIFT+X") == MOD_CONTROL | MOD_ALT | MOD_SHIFT


def test_display_names_are_friendly() -> None:
    assert display_hotkey("CTRL+SHIFT+R") == "Ctrl + Shift + R"
    assert display_hotkey("ALT+PAGEUP") == "Alt + PgUp"
    assert display_hotkey("F10") == "F10"
    assert display_hotkey("") == "—"
