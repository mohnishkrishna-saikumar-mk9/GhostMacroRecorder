"""Entry point for Ghost Macro Recorder."""

from __future__ import annotations

import os
import sys

from src.app_paths import APP_NAME, set_windows_app_user_model_id
from src.single_instance import acquire_single_instance, listen_for_show_requests
from src.win32_backend import enable_dpi_awareness


def main() -> None:
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
