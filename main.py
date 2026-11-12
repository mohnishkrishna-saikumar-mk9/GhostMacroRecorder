"""Entry point for Ghost Macro Recorder."""

from __future__ import annotations

import os
import sys

from src.app_paths import APP_NAME, set_windows_app_user_model_id
from src.single_instance import acquire_single_instance, listen_for_show_requests
from src.win32_backend import enable_dpi_awareness


def _install_error_log() -> None:
    """Windowed builds have no console: write any error to %APPDATA%\\GhostMacroRecorder\\error.log."""
    import time
    import traceback

    from src.app_paths import get_user_data_dir

    log_path = get_user_data_dir() / "error.log"
    if sys.stdout is None or sys.stderr is None:
        stream = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the process
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream

    def hook(exc_type, exc, tb) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except OSError:
            pass

    sys.excepthook = hook


def main() -> None:
    _install_error_log()
    # A copy is already running (maybe hidden in the tray): bring it forward instead.
    if not acquire_single_instance():
        return
    set_windows_app_user_model_id()
    enable_dpi_awareness()  # recording uses physical pixels; Qt works with this too

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # closing to the tray keeps Ghost running

    from src.gui.theme import Theme
    from src.gui.window import MainWindow

    Theme.pick_fonts()
    # "--tray": started by Windows at sign-in -> stay quietly in the tray
    window = MainWindow(start_hidden="--tray" in sys.argv[1:])
    listen_for_show_requests(window.bridge.show_requested.emit)
    window.present()
    code = app.exec()
    # End the whole process now, so no leftover thread keeps files locked
    # (the installer and uninstaller need the files free).
    os._exit(code)


if __name__ == "__main__":
    main()
