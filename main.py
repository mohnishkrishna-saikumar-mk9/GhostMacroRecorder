"""Entry point for Ghost Macro Recorder."""

from __future__ import annotations

from src.app_paths import set_windows_app_user_model_id
from src.single_instance import acquire_single_instance, listen_for_show_requests
from src.win32_backend import enable_dpi_awareness


def main() -> None:
    # A copy is already running (maybe hidden in the tray): bring it forward instead.
    if not acquire_single_instance():
        return
    set_windows_app_user_model_id()
    enable_dpi_awareness()

    from src.ui import MacroRecorderApp

    app = MacroRecorderApp()
    listen_for_show_requests(lambda: app.after(0, app.show_from_tray))
    app.mainloop()


if __name__ == "__main__":
    main()
