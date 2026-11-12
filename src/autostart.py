"""Start Ghost Macro Recorder when you sign in to Windows (per-user, no admin needed).

Uses the standard HKCU ...\\CurrentVersion\\Run key. The app is launched with
--tray so it starts quietly in the system tray with hotkeys ready.
"""

from __future__ import annotations

from pathlib import Path
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "GhostMacroRecorder"


def launch_command() -> str:
    if getattr(sys, "frozen", False):  # installed .exe
        return f'"{sys.executable}" --tray'
    # Running from source: use pythonw.exe so no console window appears
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{pythonw if pythonw.exists() else exe}" "{main_py}" --tray'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def startup_folder() -> Path:
    """The user's Startup folder (shortcuts here run at sign-in)."""
    import os

    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
