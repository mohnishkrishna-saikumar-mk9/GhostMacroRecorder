"""Application metadata, frozen-bundle resource resolution, and user data paths."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import sys

APP_NAME = "Ghost Macro Recorder"
APP_SLUG = "GhostMacroRecorder"
APP_ID = "GhostMacroRecorder.Desktop.1"
APP_TAGLINE = "Record Once. Run in the Background."
LEGACY_SLUG = "BackgroundMacroRecorder"
APP_VERSION = "1.0.3"


def get_resource_path(relative_path: str) -> Path:
    """Resolve bundled read-only assets in both dev and PyInstaller frozen builds."""
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_dir / relative_path


def get_user_data_dir() -> Path:
    """Return a writable per-user directory for settings and saved macros."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / APP_SLUG
        legacy = Path(appdata) / LEGACY_SLUG
    else:
        base = Path.home() / f".{APP_SLUG.lower()}"
        legacy = Path.home() / f".{LEGACY_SLUG.lower()}"
    if not base.exists() and legacy.is_dir():
        # Carry settings & macros over from the app's previous name.
        try:
            shutil.copytree(legacy, base)
        except OSError:
            pass
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_settings_path() -> Path:
    return get_user_data_dir() / "config.json"


def get_macros_dir() -> Path:
    macros_dir = get_user_data_dir() / "macros"
    macros_dir.mkdir(parents=True, exist_ok=True)
    return macros_dir


def set_windows_app_user_model_id() -> None:
    """Set explicit AppUserModelID so Windows taskbar uses the app's own icon and identity."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

