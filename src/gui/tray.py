"""System tray icon (Qt) with the ghost and a status badge."""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from src.app_paths import APP_NAME
from src.icons import build_state_ico


class QtTray:
    def __init__(self, parent, on_show: Callable[[], None], on_record: Callable[[], None],
                 on_play: Callable[[], None], on_exit: Callable[[], None]) -> None:
        self._icons: dict[str, QIcon] = {}
        self.tray = QSystemTrayIcon(self._icon("idle"), parent)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        for text, fn in (("Show Ghost", on_show), ("Record / Stop", on_record), ("Play / Stop", on_play)):
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.addSeparator()
        quit_act = QAction("Exit", menu)
        quit_act.triggered.connect(on_exit)
        menu.addAction(quit_act)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: on_show() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None
        )

    def _icon(self, state: str) -> QIcon:
        if state not in self._icons:
            try:
                self._icons[state] = QIcon(str(build_state_ico(state)))
            except Exception:
                self._icons[state] = QIcon()
        return self._icons[state]

    def start(self) -> None:
        self.tray.show()

    def set_state(self, state: str, tooltip: str = "") -> None:
        self.tray.setIcon(self._icon(state))
        self.tray.setToolTip(tooltip or APP_NAME)

    def notify(self, title: str, message: str) -> None:
        try:
            self.tray.showMessage(title, message, self._icon("idle"), 5000)
        except Exception:
            pass

    def stop(self) -> None:
        self.tray.hide()
