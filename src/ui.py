"""Studio "tape deck" GUI for Ghost Macro Recorder.

The interface borrows from audio recording hardware: a transport deck with
round REC / PLAY / STOP keys, a timecode readout, and a multi-lane "tape"
strip that draws every captured click, key, scroll and move as it happens.
A playhead sweeps the tape during playback.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import threading
import time
import tkinter as tk
import winsound
from tkinter import filedialog, font as tkfont, messagebox, ttk
from typing import Optional

import customtkinter as ctk

from src.app_paths import (
    APP_NAME,
    APP_TAGLINE,
    APP_VERSION,
    get_macros_dir,
    get_resource_path,
    get_settings_path,
    get_user_data_dir,
)
from src.icons import apply_window_icons
from src import autostart, updater
from src.hotkeys import GlobalHotkeyManager, canonical_hotkey, display_hotkey
from src.models import AppSettings, Macro, MacroEvent, WindowTarget
from src.player import MacroPlayer
from src.recorder import MacroRecorder
from src.tray import TrayController
from src.win32_backend import (
    get_foreground_root_window,
    get_window_target,
    list_visible_windows,
)

SETTINGS_PATH = get_settings_path()
MACROS_DIR = get_macros_dir()

ALL_WINDOWS_LABEL = "All Windows (Auto-Tag)"

# ----------------------------------------------------------------------
# Palette — (light, dark) pairs. Light mode is warm "studio paper",
# dark mode is graphite hardware with amber/LED accents.
# ----------------------------------------------------------------------
C = {
    "bg": ("#efebe3", "#0c0d10"),
    "panel": ("#f8f6f1", "#14161a"),
    "panel_hi": ("#ffffff", "#1b1e23"),
    "line": ("#d9d3c7", "#262a31"),
    "text": ("#1b1d21", "#e7e9ec"),
    "muted": ("#6f6a60", "#868d98"),
    "accent": ("#d9820b", "#ffb020"),
    "accent_hover": ("#b86d06", "#e09a12"),
    "rec": ("#e5383b", "#ff4d4f"),
    "rec_hover": ("#c42b2e", "#e03a3c"),
    "play": ("#13a873", "#3ddc97"),
    "play_hover": ("#0e8a5e", "#2fbf80"),
    "stop": ("#cfc8bb", "#2a2e35"),
    "stop_hover": ("#bdb5a6", "#353a43"),
    "ghost_hover": ("#e6e0d4", "#20242a"),
    "key": ("#e3ddd1", "#22262c"),
    "info": ("#2f6fd6", "#6aa8ff"),
    "warn": ("#c77700", "#f5a524"),
    "scroll": ("#bdb5a6", "#3d434d"),
    "hint": ("#5d584f", "#a2a9b4"),
    "seg": ("#e9e4da", "#202329"),
}

# Tape lanes: (lane key, label, (light, dark) color, event types)
LANES = [
    ("click", "CLICK", ("#d9820b", "#ffb020"), {"mouse_down", "mouse_up"}),
    ("key", "KEYS", ("#0f8fb3", "#4cc9f0"), {"key_down", "key_up"}),
    ("scroll", "SCROLL", ("#7b4fd6", "#b388ff"), {"mouse_scroll"}),
    ("move", "MOVE", ("#9a9488", "#4b525c"), {"mouse_move"}),
]
LANE_OF = {etype: lane for lane, _l, _c, types in LANES for etype in types}


def _mode_index() -> int:
    return 1 if ctk.get_appearance_mode().lower() == "dark" else 0


def col(name: str) -> str:
    """Resolve a palette entry for the current appearance mode (for raw tk)."""
    return C[name][_mode_index()]


def fmt_timecode(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:06.3f}"


class SmoothScrollFrame(ctk.CTkScrollableFrame):
    """CTkScrollableFrame whose mouse wheel glides with easing instead of jumping."""

    STEP_PX = 90  # pixels per wheel notch
    EASE = 0.22  # fraction of remaining distance covered per frame

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._parent_canvas.configure(yscrollincrement=1)
        self._scroll_target: Optional[float] = None
        self._scroll_job: Optional[str] = None

    def _content_height(self) -> float:
        region = self._parent_canvas.cget("scrollregion")
        try:
            return float(str(region).split()[3])
        except (IndexError, ValueError):
            return float(self._parent_canvas.winfo_height())

    def _mouse_wheel_all(self, event) -> None:  # overrides CTk's instant jump
        if not self._check_if_valid_scroll(event.widget):
            return
        canvas = self._parent_canvas
        top, bottom = canvas.yview()
        if (top, bottom) == (0.0, 1.0):
            return
        total = self._content_height()
        visible = (bottom - top) * total
        current = self._scroll_target if self._scroll_target is not None else top * total
        notches = event.delta / 120 if event.delta else 0
        target = current - notches * self.STEP_PX
        self._scroll_target = max(0.0, min(target, total - visible))
        if self._scroll_job is None:
            self._animate_scroll()

    def _animate_scroll(self) -> None:
        canvas = self._parent_canvas
        total = self._content_height()
        if self._scroll_target is None or total <= 0:
            self._scroll_job = None
            return
        current = canvas.yview()[0] * total
        diff = self._scroll_target - current
        if abs(diff) < 1.0:
            canvas.yview_moveto(self._scroll_target / total)
            self._scroll_target = None
            self._scroll_job = None
            return
        step = diff * self.EASE
        if abs(step) < 1.0:
            step = 1.0 if diff > 0 else -1.0
        canvas.yview_moveto((current + step) / total)
        self._scroll_job = self.after(12, self._animate_scroll)


class TargetPicker(ctk.CTkFrame):
    """Dropdown field for choosing the target window, styled to match the app.

    Shows the chosen app as a process "chip" plus its window title. Clicking it
    opens a searchable list of open windows.
    """

    ROW_H = 40

    def __init__(self, master, app: "MacroRecorderApp", on_select) -> None:
        super().__init__(
            master, height=40, corner_radius=8, fg_color=C["panel_hi"], border_width=1, border_color=C["line"]
        )
        self.app = app
        self.on_select = on_select
        self.choices: list[WindowTarget] = []
        self.selected: Optional[WindowTarget] = None
        self.popup: Optional[ctk.CTkToplevel] = None
        self.grid_columnconfigure(1, weight=1)

        self.chip = ctk.CTkLabel(
            self, text="", font=app._font(11, "bold", app.mono), fg_color=C["key"], text_color=C["accent"],
            corner_radius=5, height=24,
        )
        self.chip.grid(row=0, column=0, padx=(8, 8), pady=7)
        self.title_lbl = ctk.CTkLabel(self, text="", font=app._font(13), text_color=C["text"], anchor="w")
        self.title_lbl.grid(row=0, column=1, sticky="ew")
        self.chev = ctk.CTkLabel(self, text="▾", font=app._font(14), text_color=C["muted"], width=28)
        self.chev.grid(row=0, column=2, padx=(4, 8))

        for w in (self, self.chip, self.title_lbl, self.chev):
            w.bind("<Button-1>", lambda _e: self.toggle(), add="+")
            w.bind("<Enter>", lambda _e: self.configure(border_color=C["accent"]), add="+")
            w.bind("<Leave>", lambda _e: self.configure(border_color=C["line"]), add="+")
        self._render_field()

    # ---- field ----------------------------------------------------------
    @staticmethod
    def _short(text: str, limit: int) -> str:
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _render_field(self) -> None:
        t = self.selected
        if t is None:
            self.chip.configure(text="  ANY APP  ")
            self.title_lbl.configure(text="All windows — record whatever you click")
        else:
            self.chip.configure(text=f"  {self._short(t.process_name or 'app', 22)}  ")
            self.title_lbl.configure(text=self._short(t.title or t.class_name or "(untitled window)", 70))

    def set_choices(self, choices: list[WindowTarget]) -> None:
        self.choices = list(choices)

    def set_selected(self, target: Optional[WindowTarget]) -> None:
        self.selected = target
        self._render_field()

    # ---- popup ----------------------------------------------------------
    def toggle(self) -> None:
        if self.popup is not None:
            self.close()
        else:
            self.open()

    def open(self) -> None:
        self.app.refresh_windows()
        scale = self.app._get_window_scaling()
        rows = min(len(self.choices) + 1, 7)
        width = self.winfo_width() / scale
        height = 62 + rows * (self.ROW_H + 2) + 10
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + int(4 * scale)

        pop = ctk.CTkToplevel(self.app)
        try:
            # Claim the icon first, otherwise CustomTkinter swaps in its own logo after 200 ms
            pop.iconbitmap(str(get_resource_path("assets/app.ico")))
        except Exception:
            pass
        pop.withdraw()
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        pop.configure(fg_color=C["line"])
        pop.geometry(f"{int(width)}x{int(height)}+{x}+{y}")
        self.popup = pop

        inner = ctk.CTkFrame(pop, fg_color=C["panel_hi"], corner_radius=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        self.search_var = ctk.StringVar()
        search = ctk.CTkEntry(
            inner, textvariable=self.search_var, placeholder_text="Search open windows…", height=34,
            corner_radius=8, border_width=1, border_color=C["line"], fg_color=C["panel"],
            text_color=C["text"], font=self.app._font(12),
        )
        search.pack(fill="x", padx=8, pady=(8, 6))
        self.list_frame = SmoothScrollFrame(
            inner, fg_color="transparent", scrollbar_button_color=C["scroll"],
            scrollbar_button_hover_color=C["accent"],
        )
        self.list_frame.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.search_var.trace_add("write", lambda *_a: self._fill_list())
        search.bind("<Escape>", lambda _e: self.close())
        search.bind("<Return>", lambda _e: self._pick_first())
        self._fill_list()
        pop.deiconify()
        pop.after(30, search.focus_set)
        self.chev.configure(text="▴")
        self._outside_bind = self.app.bind("<Button-1>", self._on_app_click, add="+")
        self._move_bind = self.app.bind("<Configure>", lambda _e: self.close(), add="+")

    def _matches(self) -> list[Optional[WindowTarget]]:
        q = self.search_var.get().strip().lower() if self.popup else ""
        items: list[Optional[WindowTarget]] = [None] + self.choices
        if not q:
            return items
        return [t for t in items if t is not None and (q in t.process_name.lower() or q in t.title.lower())]

    def _fill_list(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        matches = self._matches()
        if not matches:
            ctk.CTkLabel(
                self.list_frame, text="No open window matches that search.", font=self.app._font(12),
                text_color=C["muted"],
            ).grid(row=0, column=0, pady=12)
            return
        for i, target in enumerate(matches):
            self._make_row(i, target)

    def _make_row(self, index: int, target: Optional[WindowTarget]) -> None:
        app = self.app
        chosen = (target is None and self.selected is None) or (
            target is not None and self.selected is not None and target.hwnd == self.selected.hwnd
        )
        row = ctk.CTkFrame(
            self.list_frame, height=self.ROW_H, corner_radius=8,
            fg_color=C["ghost_hover"] if chosen else "transparent",
        )
        row.grid(row=index, column=0, sticky="ew", pady=1)
        row.grid_columnconfigure(2, weight=1)
        row.grid_propagate(False)
        bar = ctk.CTkLabel(row, text="", width=3, height=22, corner_radius=2,
                           fg_color=C["accent"] if chosen else "transparent")
        bar.grid(row=0, column=0, padx=(4, 6), pady=9)
        if target is None:
            chip_text, title = "ANY APP", "All windows — record whatever you click"
        else:
            chip_text = self._short(target.process_name or "app", 17)
            title = self._short(target.title or target.class_name or "(untitled window)", 60)
        chip = ctk.CTkLabel(
            row, text=chip_text, font=app._font(10, "bold", app.mono), fg_color=C["key"],
            text_color=C["accent"] if chosen else C["muted"], corner_radius=5, height=22, width=150,
        )
        chip.grid(row=0, column=1, padx=(0, 10))
        lbl = ctk.CTkLabel(row, text=title, font=app._font(12, "bold" if chosen else "normal"),
                           text_color=C["text"], anchor="w")
        lbl.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        check = ctk.CTkLabel(row, text="✓" if chosen else "", font=app._font(13, "bold"),
                             text_color=C["accent"], width=20)
        check.grid(row=0, column=3, padx=(0, 8))

        def enter(_e):
            if not chosen:
                row.configure(fg_color=C["panel"])

        def leave(_e):
            if not chosen:
                row.configure(fg_color="transparent")

        for w in (row, bar, chip, lbl, check):
            w.bind("<Button-1>", lambda _e, t=target: self._choose(t))
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")

    def _pick_first(self) -> None:
        matches = self._matches()
        if matches:
            self._choose(matches[0])

    def _choose(self, target: Optional[WindowTarget]) -> None:
        self.set_selected(target)
        self.close()
        self.on_select(target)

    def _on_app_click(self, event) -> None:
        if self.popup is None:
            return
        widget = event.widget
        try:
            if str(widget).startswith(str(self)):
                return  # the field itself handles toggling
        except Exception:
            pass
        self.close()

    def close(self) -> None:
        if self.popup is None:
            return
        pop, self.popup = self.popup, None
        try:
            self.app.unbind("<Button-1>", self._outside_bind)
            self.app.unbind("<Configure>", self._move_bind)
        except Exception:
            pass
        self.chev.configure(text="▾")
        pop.destroy()


class HotkeyField(ctk.CTkButton):
    """Click, then press the key (or combo) you want."""

    def __init__(self, master, app: "MacroRecorderApp", attr: str) -> None:
        self.app = app
        self.attr = attr
        super().__init__(
            master, text="", width=150, height=28, corner_radius=8, fg_color=C["key"],
            hover_color=C["ghost_hover"], border_width=1, border_color=C["line"], text_color=C["text"],
            font=app._font(12, "bold", app.mono), command=lambda: app._start_hotkey_capture(self),
        )
        self.show()

    def show(self) -> None:
        self.configure(text=display_hotkey(getattr(self.app.settings, self.attr)),
                       border_color=C["line"], text_color=C["text"])

    def waiting(self) -> None:
        self.configure(text="Press a key…", border_color=C["accent"], text_color=C["accent"])


def parse_duration(text: str) -> Optional[float]:
    """Parse '90', '90s', '5m', '1h', '1:30' or '1:02:03' into seconds."""
    raw = text.strip().lower().replace(" ", "")
    if not raw:
        return None
    try:
        if ":" in raw:
            total = 0.0
            for part in raw.split(":"):
                total = total * 60 + float(part or 0)
            return total
        unit = {"s": 1, "m": 60, "h": 3600}.get(raw[-1])
        if unit:
            return float(raw[:-1]) * unit
        return float(raw)
    except ValueError:
        return None


def fmt_duration(seconds: float) -> str:
    seconds = int(round(max(0.0, seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class MacroRecorderApp(ctk.CTk):
    MIN_W = 980  # logical px
    """Main desktop application window."""

    def __init__(self, start_hidden: bool = False) -> None:
        super().__init__()
        # Stay invisible while the window is built, themed and sized, then fade in
        # (otherwise Windows shows white strips and a visible resize jump on launch).
        self._start_hidden = start_hidden
        self._revealed = False
        self._fade_job: Optional[str] = None
        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            pass
        self.settings = AppSettings.load(SETTINGS_PATH)
        ctk.set_appearance_mode(self.settings.appearance_mode)
        ctk.set_default_color_theme("blue")
        self._apply_theme_defaults()
        self._splash: Optional[tk.Toplevel] = None
        if not start_hidden:
            self._show_splash()

        self.title(f"{APP_NAME} v{APP_VERSION}")
        # Fit smaller / high-DPI screens: never open larger than ~92% of the work area.
        scale = self._get_window_scaling()
        screen_w = int(self.winfo_screenwidth() / scale)
        screen_h = int(self.winfo_screenheight() / scale)
        win_w, win_h = min(1160, int(screen_w * 0.92)), min(760, int(screen_h * 0.86))
        self.geometry(f"{win_w}x{win_h}+{max(0, (screen_w - win_w) // 2)}+{max(0, (screen_h - win_h) // 3)}")
        self.minsize(self.MIN_W, 560)
        self.configure(fg_color=C["bg"])
        icon_path = get_resource_path("assets/app.ico")
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))  # also stops CustomTkinter's own logo
            except Exception:
                pass
        # Exact-size icons for title bar / taskbar / Alt+Tab (Tk alone gives a blurry one)
        self.after(50, self._apply_icons)
        self.bind("<Map>", lambda e: self._apply_icons() if e.widget is self else None, add="+")

        families = set(tkfont.families(self))
        self.mono = next(
            (f for f in ("Cascadia Mono", "Cascadia Code", "Consolas") if f in families),
            "Courier New",
        )
        self.sans = "Segoe UI Variable Text" if "Segoe UI Variable Text" in families else "Segoe UI"
        self.sans_display = (
            "Segoe UI Variable Display" if "Segoe UI Variable Display" in families else "Segoe UI"
        )

        self.own_pid = os.getpid()
        self.macro = Macro()
        self._dirty = False  # current macro has changes that aren't saved to a file
        self._macro_file: Optional[Path] = None
        self._window_choices: list[WindowTarget] = []
        self._selected_target: Optional[WindowTarget] = None
        self._picking_window = False
        self._is_closing = False

        # Live tape state
        self._live_events: list[MacroEvent] = []
        self._record_started_at: Optional[float] = None
        self._play_ev_idx = 0
        self._play_started_at: Optional[float] = None
        self._tape_dirty = True
        self._blink = False

        self.recorder = MacroRecorder(
            own_pid=self.own_pid,
            on_event=self._on_recorded_event_bg,
            on_state_change=self._on_record_state_bg,
        )
        self.player = MacroPlayer(
            on_progress=self._on_play_progress_bg,
            on_state_change=self._on_play_state_bg,
        )
        self.hotkeys = GlobalHotkeyManager(
            on_toggle_record=lambda: self.after(0, self.toggle_record),
            on_toggle_play=lambda: self.after(0, self.toggle_play),
            on_stop_all=lambda: self.after(0, self.stop_all),
            on_set_target=lambda: self.after(0, self.set_target_to_current_window),
        )
        self._hotkey_results_seen = -1
        self._countdown_job: Optional[str] = None
        self._countdown_left = 0
        self._hotkey_status: dict[str, bool] = {}
        self._capture_field: Optional[HotkeyField] = None
        self.hotkeys.set_hotkeys(
            self.settings.hotkey_record,
            self.settings.hotkey_play,
            self.settings.hotkey_stop,
            self.settings.hotkey_target,
        )
        self.tray = TrayController(
            on_show=lambda: self.after(0, self.show_from_tray),
            on_toggle_record=lambda: self.after(0, self.toggle_record),
            on_toggle_play=lambda: self.after(0, self.toggle_play),
            on_exit=lambda: self.after(0, self.request_exit),
        )

        self._build_ui()
        # Maximize / restore: hide the widget-by-widget redraw behind a plain panel
        self._resize_cover = tk.Frame(self, bg=col("bg"), bd=0, highlightthickness=0)
        self._resize_cover_job: Optional[str] = None
        self._last_size = (0, 0)
        self.bind("<Configure>", self._on_root_configure, add="+")
        self.after(120, self._fit_min_size)
        self.after(6000, self._reveal)  # safety net: never stay invisible
        self.lbl_engine_help.configure(text=self.ENGINE_HELP[self.mode_var.get()])
        self.lbl_limit_help.configure(text=self.LIMIT_HELP[self.limit_var.get()])
        self._apply_treeview_style()
        self.refresh_windows()
        self._set_status("Idle — ready to record", "info")

        self.hotkeys.start()
        self.tray.start()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.attributes("-topmost", bool(self.settings.always_on_top))
        self.after(100, self._tick)
        self._update_info: Optional[updater.UpdateInfo] = None
        self._updating = False
        self.after(6000, self._auto_update_check)
        if start_hidden:
            self.after(0, self.withdraw)

    # ------------------------------------------------------------------
    # Small widget factories
    # ------------------------------------------------------------------
    def _font(self, size: int, weight: str = "normal", family: Optional[str] = None) -> ctk.CTkFont:
        return ctk.CTkFont(family=family or self.sans, size=size, weight=weight)

    def _eyebrow(self, parent: ctk.CTkBaseClass, text: str) -> ctk.CTkLabel:
        """Small spaced-out uppercase label, like hardware panel silkscreen."""
        return ctk.CTkLabel(
            parent,
            text="  ".join(text.upper()) if len(text) <= 8 else text.upper(),
            font=self._font(10, "bold"),
            text_color=C["muted"],
        )

    def _ghost_button(self, parent: ctk.CTkBaseClass, text: str, command, width: int = 0) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width or 70,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            hover_color=C["ghost_hover"],
            border_width=1,
            border_color=C["line"],
            text_color=C["text"],
            font=self._font(12),
        )

    def _keycap(self, parent: ctk.CTkBaseClass, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=f" {text} ",
            font=self._font(10, "bold", self.mono),
            fg_color=C["key"],
            text_color=C["muted"],
            corner_radius=4,
            height=18,
        )

    def _card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent,
            corner_radius=14,
            fg_color=C["panel"],
            border_width=1,
            border_color=C["line"],
        )

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_deck()
        # Lower area: [target strip / steps list] on the left, a tall settings column on the right
        self._lower = ctk.CTkFrame(self, fg_color="transparent")
        self._lower.grid(row=2, column=0, padx=20, pady=6, sticky="nsew")
        self._lower.grid_columnconfigure(0, weight=1)
        self._lower.grid_rowconfigure(0, weight=1)
        self._left = ctk.CTkFrame(self._lower, fg_color="transparent")
        self._left.grid(row=0, column=0, sticky="nsew")
        self._left.grid_columnconfigure(0, weight=1)
        self._left.grid_rowconfigure(1, weight=1)
        self._build_target_strip()
        self._build_body()
        self._build_footer()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=20, pady=(14, 8), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w")
        logo_path = get_resource_path("assets/icon.png")
        if logo_path.exists():
            from PIL import Image

            ui_logo = get_resource_path("assets/icon_ui.png")
            self._logo_img = ctk.CTkImage(Image.open(ui_logo if ui_logo.exists() else logo_path), size=(40, 40))
            ctk.CTkLabel(brand, text="", image=self._logo_img).pack(side="left", padx=(0, 10))
        words = ctk.CTkFrame(brand, fg_color="transparent")
        words.pack(side="left")
        name_row = ctk.CTkFrame(words, fg_color="transparent")
        name_row.pack(anchor="w")
        ctk.CTkLabel(
            name_row, text="Ghost", font=self._font(19, "bold", self.sans_display), text_color=C["text"]
        ).pack(side="left")
        ctk.CTkLabel(
            name_row, text="Macro", font=self._font(19, "bold", self.sans_display), text_color=C["text"]
        ).pack(side="left")
        ctk.CTkLabel(
            name_row, text="Recorder", font=self._font(19, "bold", self.sans_display), text_color=C["accent"]
        ).pack(side="left")
        ctk.CTkLabel(
            name_row, text=f"  v{APP_VERSION}", font=self._font(11), text_color=C["muted"]
        ).pack(side="left", pady=(5, 0))
        ctk.CTkLabel(
            words, text=APP_TAGLINE, font=self._font(11), text_color=C["muted"], height=14
        ).pack(anchor="w")

        # Status pill: LED + message
        self.status_pill = ctk.CTkFrame(
            header, corner_radius=16, fg_color=C["panel"], border_width=1, border_color=C["line"]
        )
        self.status_pill.grid(row=0, column=1, padx=16, sticky="e")
        self.lbl_led = ctk.CTkLabel(
            self.status_pill, text="●", font=self._font(14), text_color=C["info"], width=14
        )
        self.lbl_led.pack(side="left", padx=(12, 6), pady=4)
        self.lbl_status = ctk.CTkLabel(
            self.status_pill, text="", font=self._font(12, "bold"), text_color=C["text"]
        )
        self.lbl_status.pack(side="left", padx=(0, 14), pady=4)

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e")
        self.btn_new = self._ghost_button(actions, "＋ New", self.new_macro)
        self.btn_new.pack(side="left", padx=3)
        self.btn_open = self._ghost_button(actions, "Open", self.load_macro_dialog)
        self.btn_open.pack(side="left", padx=3)
        self.btn_save = self._ghost_button(actions, "Save", self.save_macro_dialog)
        self.btn_save.pack(side="left", padx=3)
        self.btn_clear = self._ghost_button(actions, "Clear", self.clear_macro)
        self.btn_clear.pack(side="left", padx=3)
        self.btn_theme = self._ghost_button(actions, "", self._toggle_theme, width=36)
        self.btn_theme.pack(side="left", padx=3)
        self.btn_about = self._ghost_button(actions, "?", self.show_about_dialog, width=36)
        self.btn_about.pack(side="left", padx=(3, 0))
        self._update_theme_glyph()

    def _build_deck(self) -> None:
        deck = self._card(self)
        deck.grid(row=1, column=0, padx=20, pady=6, sticky="ew")
        deck.grid_columnconfigure(2, weight=1)

        # --- Transport keys -------------------------------------------------
        transport = ctk.CTkFrame(deck, fg_color="transparent")
        transport.grid(row=0, column=0, padx=(20, 10), pady=18, sticky="w")

        def transport_key(column: int, glyph: str, fg, hover, text_color, command, caption: str):
            holder = ctk.CTkFrame(transport, fg_color="transparent")
            holder.grid(row=0, column=column, padx=7)
            btn = ctk.CTkButton(
                holder,
                text=glyph,
                width=64,
                height=64,
                corner_radius=32,
                fg_color=fg,
                hover_color=hover,
                text_color=text_color,
                font=self._font(24, "bold"),
                border_width=3,
                border_color=C["panel"],
                command=command,
            )
            btn.pack()
            cap_row = ctk.CTkFrame(holder, fg_color="transparent")
            cap_row.pack(pady=(7, 0))
            ctk.CTkLabel(
                cap_row, text=caption, font=self._font(10, "bold"), text_color=C["muted"]
            ).pack(side="left", padx=(0, 4))
            keycap = self._keycap(cap_row, "")
            keycap.pack(side="left")
            return btn, keycap

        self.btn_record, self.cap_record = transport_key(
            0, "●", C["rec"], C["rec_hover"], "#ffffff", self.toggle_record, "REC"
        )
        self.btn_play, self.cap_play = transport_key(
            1, "▶", C["play"], C["play_hover"], ("#ffffff", "#06261a"), self.toggle_play, "PLAY"
        )
        self.btn_stop, self.cap_stop = transport_key(
            2, "■", C["stop"], C["stop_hover"], C["text"], self.stop_all, "STOP"
        )

        # --- Timecode readout ----------------------------------------------
        readout = ctk.CTkFrame(deck, fg_color=C["panel_hi"], corner_radius=10, border_width=1,
                               border_color=C["line"])
        readout.grid(row=0, column=1, padx=10, pady=18, sticky="w")
        self._eyebrow(readout, "timecode").pack(anchor="w", padx=16, pady=(10, 0))
        self.lbl_timecode = ctk.CTkLabel(
            readout,
            text=fmt_timecode(0),
            font=self._font(34, "bold", self.mono),
            text_color=C["accent"],
        )
        self.lbl_timecode.pack(anchor="w", padx=14, pady=(0, 0))
        self.lbl_counts = ctk.CTkLabel(
            readout,
            text="0 events · 0.00s",
            font=self._font(11, family=self.mono),
            text_color=C["muted"],
        )
        self.lbl_counts.pack(anchor="w", padx=16, pady=(0, 10))

        # --- Tape strip ------------------------------------------------------
        tape_wrap = ctk.CTkFrame(deck, fg_color="transparent")
        tape_wrap.grid(row=0, column=2, padx=(10, 20), pady=14, sticky="nsew")
        tape_wrap.grid_columnconfigure(0, weight=1)
        tape_wrap.grid_rowconfigure(1, weight=1)

        tape_head = ctk.CTkFrame(tape_wrap, fg_color="transparent")
        tape_head.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._eyebrow(tape_head, "tape").pack(side="left")
        self.lbl_tape_info = ctk.CTkLabel(
            tape_head, text="empty reel", font=self._font(10), text_color=C["muted"]
        )
        self.lbl_tape_info.pack(side="right")

        self.tape = tk.Canvas(tape_wrap, height=108, highlightthickness=0, bd=0)
        self.tape.grid(row=1, column=0, sticky="nsew")
        self.tape.bind("<Configure>", lambda _e: self._mark_tape_dirty())

    def _build_target_strip(self) -> None:
        strip = self._card(self._left)
        strip.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        strip.grid_columnconfigure(1, weight=1)

        self._eyebrow(strip, "target").grid(row=0, column=0, padx=(20, 12), pady=(12, 2), sticky="w")

        self.picker = TargetPicker(strip, self, self._on_target_selected)
        self.picker.grid(row=0, column=1, padx=4, pady=(12, 2), sticky="ew")

        self.btn_refresh_win = self._ghost_button(strip, "↻", self.refresh_windows, width=38)
        self.btn_refresh_win.grid(row=0, column=2, padx=4, pady=(12, 2))

        self.btn_pick_win = ctk.CTkButton(
            strip,
            text="◎  Pick window",
            width=130,
            height=38,
            corner_radius=8,
            fg_color=C["accent"],
            hover_color=C["accent_hover"],
            text_color=("#ffffff", "#1a1206"),
            font=self._font(12, "bold"),
            command=self.start_pick_window,
        )
        self.btn_pick_win.grid(row=0, column=3, padx=(4, 16), pady=(12, 2))

        self.scope_var = ctk.StringVar(
            value="This window only" if self.settings.record_scope == "target" else "Every window"
        )
        scope_row = ctk.CTkFrame(strip, fg_color="transparent")
        scope_row.grid(row=1, column=1, columnspan=3, padx=4, pady=(8, 12), sticky="ew")
        scope_row.grid_columnconfigure(1, weight=1)
        self.seg_scope = ctk.CTkSegmentedButton(
            scope_row,
            values=["This window only", "Every window"],
            variable=self.scope_var,
            command=self._on_settings_changed,
            height=38,
            corner_radius=8,
            font=self._font(12),
        )
        self.seg_scope.grid(row=0, column=0, sticky="w")
        self._style_segmented(self.seg_scope)

        self.lbl_target_hint = ctk.CTkLabel(
            scope_row,
            text="",
            font=self._font(11),
            text_color=C["hint"],
            anchor="w",
            justify="left",
        )
        self.lbl_target_hint.grid(row=0, column=1, padx=(14, 4), sticky="ew")
        scope_row.bind("<Configure>", lambda e: self.lbl_target_hint.configure(
            wraplength=max(160, int(e.width / self._get_window_scaling()) - 280)), add="+")
        self._update_target_hint()

    def _update_target_hint(self) -> None:
        self._update_summary()
        t = self._selected_target
        scope_target = self.scope_var.get() == "This window only"
        if t is None:
            msg = ("Choose the app you want to automate, or press Pick window and click on it."
                   if scope_target else
                   "Recording every app you click. Each step remembers which window it happened in.")
        elif scope_target:
            msg = (f"Only clicks and keys inside {t.process_name} are recorded — use other apps freely "
                   f"while recording or playing.")
        else:
            msg = f"Playback goes to {t.process_name}. While recording, clicks in every window are captured."
        self.lbl_target_hint.configure(text=msg)

    def _style_segmented(self, seg: ctk.CTkSegmentedButton) -> None:
        """Segmented buttons: selected = inverted ink, unselected = plain panel."""
        seg.configure(
            selected_color=C["text"],
            selected_hover_color=C["text"],
            unselected_color=C["seg"],
            unselected_hover_color=C["ghost_hover"],
            fg_color=C["seg"],  # same as the buttons: one clean pill, no box-in-box or edge line
        )
        # CTk uses one text color for all segments; we repaint per-segment so the
        # selected (inverted) segment stays readable in both light and dark mode.
        self._repaint_segment_text(seg)
        seg.configure(command=self._wrap_seg_command(seg, getattr(seg, "_command", None)))

    def _wrap_seg_command(self, seg: ctk.CTkSegmentedButton, original):
        def handler(value: str) -> None:
            self._repaint_segment_text(seg)
            if original:
                original(value)

        return handler

    def _repaint_all_segments(self) -> None:
        """Keep inverted segment labels readable even when changed programmatically."""
        segs = [self.seg_scope, self.seg_mode, self.seg_limit, self.seg_theme, self.tabs._segmented_button,  # noqa: SLF001
                *self._extra_segs]
        for seg in segs:
            if getattr(seg, "_deck_painted", None) != seg.get():
                self._repaint_segment_text(seg)

    def _repaint_segment_text(self, seg: ctk.CTkSegmentedButton) -> None:
        current = seg.get()
        seg._deck_painted = current  # type: ignore[attr-defined]
        for value, button in seg._buttons_dict.items():  # noqa: SLF001 — CTk has no public API
            if value == current:
                button.configure(text_color=(C["panel_hi"][0], C["bg"][1]))
            else:
                button.configure(text_color=C["text"])

    def _build_body(self) -> None:
        body = self._lower

        # --- Steps list ------------------------------------------------------
        steps = self._card(self._left)
        steps.grid(row=1, column=0, sticky="nsew")
        steps.grid_columnconfigure(0, weight=1)
        steps.grid_rowconfigure(1, weight=1)

        steps_head = ctk.CTkFrame(steps, fg_color="transparent")
        steps_head.grid(row=0, column=0, padx=18, pady=(14, 8), sticky="ew")
        steps_head.grid_columnconfigure(0, weight=1)
        title = ctk.CTkFrame(steps_head, fg_color="transparent")
        title.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title, text="Steps", font=self._font(15, "bold", self.sans_display),
            text_color=C["text"],
        ).pack(side="left")
        ctk.CTkLabel(
            title, text="drag to select many · Del removes", font=self._font(10), text_color=C["muted"],
        ).pack(side="left", padx=(10, 0), pady=(3, 0))

        legend = ctk.CTkFrame(steps_head, fg_color="transparent")
        legend.grid(row=0, column=1, sticky="e", padx=(0, 10))
        for _lane, label, color, _types in LANES:
            ctk.CTkLabel(legend, text="■", font=self._font(10), text_color=color).pack(side="left")
            ctk.CTkLabel(
                legend, text=f"{label.title()}  ", font=self._font(10), text_color=C["muted"]
            ).pack(side="left")

        self._ghost_button(steps_head, "Trim moves", self.trim_mouse_moves, width=96).grid(
            row=0, column=2, padx=(0, 6)
        )
        self._ghost_button(steps_head, "Delete", self.delete_selected_events, width=70).grid(
            row=0, column=3
        )

        tree_container = ctk.CTkFrame(steps, fg_color="transparent")
        tree_container.grid(row=1, column=0, padx=(14, 8), pady=(0, 14), sticky="nsew")
        tree_container.grid_columnconfigure(0, weight=1)
        tree_container.grid_rowconfigure(0, weight=1)

        columns = ("idx", "time", "action", "target", "details")
        self.tree = ttk.Treeview(
            tree_container, columns=columns, show="headings", selectmode="extended", style="Deck.Treeview"
        )
        self.tree.heading("idx", text="#")
        self.tree.heading("time", text="TIME")
        self.tree.heading("action", text="ACTION")
        self.tree.heading("target", text="WINDOW")
        self.tree.heading("details", text="DETAILS")

        self.tree.column("idx", width=52, anchor="e", stretch=False)
        self.tree.column("time", width=84, anchor="e", stretch=False)
        self.tree.column("action", width=130, anchor="w", stretch=False)
        self.tree.column("target", width=220, anchor="w")
        self.tree.column("details", width=220, anchor="w")

        scrollbar = ctk.CTkScrollbar(
            tree_container,
            orientation="vertical",
            command=self.tree.yview,
            button_color=C["line"],
            button_hover_color=C["muted"],
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        # Select many steps at once: drag over them (the list scrolls at its edges),
        # Shift/Ctrl+click, Ctrl+A for all; Delete removes the selection.
        self._drag_anchor: Optional[str] = None
        self._drag_scroll_job: Optional[str] = None
        self._drag_y = 0
        self.tree.bind("<ButtonPress-1>", self._on_tree_press, add="+")
        self.tree.bind("<B1-Motion>", self._on_tree_drag, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release, add="+")
        self.tree.bind("<Delete>", lambda _e: self.delete_selected_events())
        self.tree.bind("<BackSpace>", lambda _e: self.delete_selected_events())
        self.tree.bind("<Control-a>", self._select_all_steps)
        self.tree.bind("<Control-A>", self._select_all_steps)

        self.lbl_empty = ctk.CTkLabel(
            tree_container,
            text="Nothing on the reel yet.\nPress ● REC (or your hotkey) and use your target app.",
            font=self._font(13),
            text_color=C["muted"],
            justify="center",
        )
        self.lbl_empty.place(relx=0.5, rely=0.5, anchor="center")

        # --- Settings tabs (fixed, no scrolling) -----------------------------
        self._right = ctk.CTkFrame(body, fg_color="transparent")
        self._right.grid(row=0, column=1, padx=(12, 0), sticky="nsew")
        self._right.grid_columnconfigure(0, weight=1)
        self._right.grid_rowconfigure(1, weight=1)
        self.tabs = ctk.CTkTabview(
            self._right,
            width=372,
            corner_radius=14,
            fg_color=C["panel"],
            border_width=1,
            border_color=C["line"],
            segmented_button_fg_color=C["seg"],
            segmented_button_selected_color=C["text"],
            segmented_button_selected_hover_color=C["text"],
            segmented_button_unselected_color=C["seg"],
            segmented_button_unselected_hover_color=C["ghost_hover"],
            text_color=C["text"],
            command=lambda: self._repaint_segment_text(self.tabs._segmented_button),  # noqa: SLF001
        )
        self.tabs.grid(row=0, column=0, sticky="new")
        self.tabs._segmented_button.configure(font=self._font(12))  # noqa: SLF001
        pages = {}
        for name in ("Play", "Repeat", "Record", "Keys", "App"):
            page = self.tabs.add(name)
            page.grid_columnconfigure(0, weight=1)
            pages[name] = page
        self._repaint_segment_text(self.tabs._segmented_button)  # noqa: SLF001

        self._extra_segs: list[ctk.CTkSegmentedButton] = []
        self._build_summary_card()
        self._build_play_tab(pages["Play"])
        self._build_repeat_tab(pages["Repeat"])
        self._build_record_tab(pages["Record"])
        self._build_keys_tab(pages["Keys"])
        self._build_app_tab(pages["App"])

    WRAP = 320

    SUMMARY_ROWS = (("macro", "Macro"), ("steps", "Steps"), ("target", "Target"), ("engine", "Plays"),
                    ("runs", "Runs"))

    def _build_summary_card(self) -> None:
        """'This run' card: fills the space under the settings with what will actually happen."""
        card = self._card(self._right)
        card.grid(row=1, column=0, pady=(10, 0), sticky="nsew")
        card.grid_columnconfigure(1, weight=1)
        self.summary_card = card
        self._summary_shown = True
        self.after(10, self._place_summary)
        self._eyebrow(card, "this run").grid(row=0, column=0, columnspan=2, padx=18, pady=(14, 6), sticky="w")
        self.summary_vals: dict[str, ctk.CTkLabel] = {}
        for i, (key, label) in enumerate(self.SUMMARY_ROWS, start=1):
            ctk.CTkLabel(card, text=label, font=self._font(12), text_color=C["hint"], anchor="w").grid(
                row=i, column=0, padx=(18, 12), pady=3, sticky="nw"
            )
            val = ctk.CTkLabel(card, text="—", font=self._font(12, "bold"), text_color=C["text"], anchor="w",
                               justify="left", wraplength=250)
            val.grid(row=i, column=1, padx=(0, 16), pady=3, sticky="w")
            self.summary_vals[key] = val
        self._right.bind("<Configure>", lambda _e: self._place_summary(), add="+")

    def _place_summary(self) -> None:
        """Show the summary only when there is real room for it under the settings."""
        try:
            scale = self._get_window_scaling()
            room = (self._right.winfo_height() - self.tabs.winfo_reqheight()) / scale
            want = room >= 170
            if want != self._summary_shown:
                self._summary_shown = want
                if want:
                    # Tall window: settings hug their content, "This run" fills the rest
                    self._right.grid_rowconfigure(0, weight=0)
                    self._right.grid_rowconfigure(1, weight=1)
                    self.tabs.grid_configure(sticky="new")
                    self.summary_card.grid()
                else:
                    # Short window: settings card runs to the bottom, lined up with Steps
                    self.summary_card.grid_remove()
                    self._right.grid_rowconfigure(1, weight=0)
                    self._right.grid_rowconfigure(0, weight=1)
                    self.tabs.grid_configure(sticky="nsew")
        except Exception:
            pass

    def _update_summary(self) -> None:
        if not hasattr(self, "summary_vals"):
            return
        v = self.summary_vals
        events = self.macro.events
        name = self._macro_file.stem if getattr(self, "_macro_file", None) else (
            "Untitled (not saved)" if events else "Nothing recorded yet")
        if events and getattr(self, "_dirty", False) and getattr(self, "_macro_file", None):
            name += "  •  unsaved changes"
        v["macro"].configure(text=name)
        v["steps"].configure(text=f"{len(events):,} steps · {fmt_duration(self.macro.duration)} long" if events else "—")
        t = self._selected_target
        v["target"].configure(text=(t.process_name if t else "Any app you click"))
        mode = "In the background" if self.settings.playback_mode == "background" else "With your real mouse & keys"
        v["engine"].configure(text=f"{mode} · {self.settings.speed:g}× speed")
        v["runs"].configure(text=getattr(self, "_run_summary", "—"))

    def _setting_label(self, parent, text: str, row: int, sub: str = "", top: int = 10) -> Optional[ctk.CTkLabel]:
        ctk.CTkLabel(parent, text=text, font=self._font(13, "bold"), text_color=C["text"]).grid(
            row=row, column=0, padx=8, pady=(top, 0), sticky="w"
        )
        if not sub:
            return None
        lbl = ctk.CTkLabel(
            parent, text=sub, font=self._font(11), text_color=C["hint"], justify="left",
            wraplength=self.WRAP, anchor="w",
        )
        lbl.grid(row=row + 1, column=0, padx=8, pady=(1, 0), sticky="w")
        return lbl

    def _option(self, parent, row: int, title: str, desc: str, value: bool, command=None) -> ctk.CTkSwitch:
        """A switch with a plain-language explanation underneath."""
        sw = ctk.CTkSwitch(
            parent,
            text=title,
            command=command or self._on_settings_changed,
            font=self._font(13, "bold"),
            text_color=C["text"],
            progress_color=C["accent"],
            button_color=("#ffffff", "#e7e9ec"),
            button_hover_color=("#f2f2f2", "#ffffff"),
            fg_color=C["line"],
        )
        if value:
            sw.select()
        sw.grid(row=row, column=0, padx=8, pady=(10, 0), sticky="w")
        ctk.CTkLabel(
            parent, text=desc, font=self._font(11), text_color=C["hint"], justify="left",
            wraplength=self.WRAP - 50, anchor="w",
        ).grid(row=row + 1, column=0, padx=(56, 8), sticky="w")
        return sw

    ENGINE_HELP = {
        "Background": "Plays inside the target window on its own. Your mouse and keyboard stay free — "
        "keep working in other apps while it runs.",
        "Foreground": "Moves your real mouse and presses real keys, like a person would. Don't touch "
        "the PC while it plays. Use this if an app ignores Background mode.",
    }
    LIMIT_HELP = {
        "Repeat count": "Play the macro a set number of times. 0 = keep repeating until you press Stop.",
        "Run for time": "Keep repeating the macro until this much time has passed, then stop by itself.",
    }

    def _pill(self, parent, values: list[str], current: str, height: int = 28) -> tuple[ctk.CTkSegmentedButton, ctk.StringVar]:
        var = ctk.StringVar(value=current if current in values else values[0])
        seg = ctk.CTkSegmentedButton(parent, values=values, variable=var, command=self._on_settings_changed,
                                     height=height, corner_radius=8, font=self._font(11))
        self._style_segmented(seg)
        self._extra_segs.append(seg)
        return seg, var

    def _mini_box(self, parent, column: int, title: str) -> ctk.CTkFrame:
        box = ctk.CTkFrame(parent, fg_color=C["panel_hi"], corner_radius=10, border_width=1, border_color=C["line"])
        box.grid(row=0, column=column, padx=(0 if column == 0 else 5, 5 if column == 0 else 0), sticky="ew")
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=title, font=self._font(10, "bold"), text_color=C["muted"], anchor="w").grid(
            row=0, column=0, padx=10, pady=(7, 3), sticky="w"
        )
        return box

    COUNTDOWN = {"Off": 0, "3 s": 3, "5 s": 5}
    HUMANIZE = {"Off": 0, "Light": 5, "Strong": 15}
    ON_FINISH = {"Nothing": "none", "Notify": "notify", "Sound": "sound"}

    def _build_play_tab(self, tab: ctk.CTkFrame) -> None:
        self._setting_label(tab, "How should it play?", 0, top=6)
        self.mode_var = ctk.StringVar(
            value="Background" if self.settings.playback_mode == "background" else "Foreground"
        )
        self.seg_mode = ctk.CTkSegmentedButton(
            tab,
            values=["Background", "Foreground"],
            variable=self.mode_var,
            command=self._on_settings_changed,
            height=32,
            corner_radius=8,
            font=self._font(12),
        )
        self.seg_mode.grid(row=1, column=0, padx=8, pady=(6, 0), sticky="ew")
        self._style_segmented(self.seg_mode)
        self.lbl_engine_help = ctk.CTkLabel(
            tab, text="", font=self._font(11), text_color=C["hint"], justify="left",
            wraplength=self.WRAP, anchor="w",
        )
        self.lbl_engine_help.grid(row=2, column=0, padx=8, pady=(4, 0), sticky="w")

        speed_row = ctk.CTkFrame(tab, fg_color="transparent")
        speed_row.grid(row=3, column=0, padx=8, pady=(12, 0), sticky="ew")
        speed_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(speed_row, text="Speed", font=self._font(13, "bold"), text_color=C["text"]).grid(
            row=0, column=0, sticky="w"
        )
        self.lbl_speed = ctk.CTkLabel(
            speed_row,
            text=f"{self.settings.speed:.2f}×",
            font=self._font(13, "bold", self.mono),
            text_color=C["accent"],
        )
        self.lbl_speed.grid(row=0, column=1, sticky="e")

        self.slider_speed = ctk.CTkSlider(
            tab,
            from_=0.25,
            to=5.0,
            number_of_steps=19,
            command=self._on_speed_slide,
            progress_color=C["accent"],
            button_color=C["accent"],
            button_hover_color=C["accent_hover"],
            fg_color=C["line"],
        )
        self.slider_speed.set(self.settings.speed)
        self.slider_speed.grid(row=5, column=0, padx=8, pady=(8, 0), sticky="ew")
        ticks = ctk.CTkFrame(tab, fg_color="transparent")
        ticks.grid(row=6, column=0, padx=8, sticky="ew")
        ticks.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(ticks, text="0.25× slower", font=self._font(10), text_color=C["muted"]).grid(row=0, column=0)
        ctk.CTkLabel(ticks, text="faster 5×", font=self._font(10), text_color=C["muted"]).grid(row=0, column=2)

        extras = ctk.CTkFrame(tab, fg_color="transparent")
        extras.grid(row=7, column=0, padx=8, pady=(10, 0), sticky="ew")
        extras.grid_columnconfigure((0, 1), weight=1)
        box = self._mini_box(extras, 0, "COUNTDOWN · time to switch apps")
        rev = {v: k for k, v in self.COUNTDOWN.items()}
        self.seg_countdown, self.countdown_var = self._pill(box, list(self.COUNTDOWN), rev.get(self.settings.start_delay, "Off"))
        self.seg_countdown.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")
        box = self._mini_box(extras, 1, "HUMANIZE · natural timing")
        rev = {v: k for k, v in self.HUMANIZE.items()}
        self.seg_humanize, self.humanize_var = self._pill(box, list(self.HUMANIZE), rev.get(self.settings.humanize_pct, "Off"))
        self.seg_humanize.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")

    def _build_repeat_tab(self, tab: ctk.CTkFrame) -> None:
        self._setting_label(tab, "When should it stop?", 0, top=6)
        self.limit_var = ctk.StringVar(
            value="Run for time" if self.settings.run_limit_mode == "time" else "Repeat count"
        )
        self.seg_limit = ctk.CTkSegmentedButton(
            tab,
            values=["Repeat count", "Run for time"],
            variable=self.limit_var,
            command=self._on_settings_changed,
            height=32,
            corner_radius=8,
            font=self._font(12),
        )
        self.seg_limit.grid(row=1, column=0, padx=8, pady=(6, 0), sticky="ew")
        self._style_segmented(self.seg_limit)
        self.lbl_limit_help = ctk.CTkLabel(
            tab, text="", font=self._font(11), text_color=C["hint"], justify="left",
            wraplength=self.WRAP, anchor="w",
        )
        self.lbl_limit_help.grid(row=2, column=0, padx=8, pady=(4, 0), sticky="w")

        loop = ctk.CTkFrame(tab, fg_color="transparent")
        loop.grid(row=3, column=0, padx=8, pady=(10, 0), sticky="ew")
        loop.grid_columnconfigure((0, 1), weight=1)

        def numeric_field(column: int, title: str, hint: str, var: ctk.StringVar) -> ctk.CTkEntry:
            box = ctk.CTkFrame(loop, fg_color=C["panel_hi"], corner_radius=10, border_width=1,
                               border_color=C["line"])
            box.grid(row=0, column=column, padx=(0 if column == 0 else 5, 5 if column == 0 else 0),
                     sticky="ew")
            ctk.CTkLabel(box, text=title, font=self._font(10, "bold"), text_color=C["muted"]).pack(
                anchor="w", padx=10, pady=(8, 0)
            )
            entry = ctk.CTkEntry(
                box,
                textvariable=var,
                width=80,
                height=30,
                border_width=0,
                fg_color="transparent",
                text_color=C["text"],
                font=self._font(18, "bold", self.mono),
            )
            entry.pack(fill="x", padx=4)
            ctk.CTkLabel(box, text=hint, font=self._font(10), text_color=C["hint"]).pack(
                anchor="w", padx=10, pady=(0, 6)
            )
            entry.bind("<FocusOut>", lambda _e: self._on_settings_changed())
            entry.bind("<Return>", lambda _e: self._on_settings_changed())
            return entry

        self.repeat_var = ctk.StringVar(value=str(self.settings.repeat_count))
        self.entry_repeat = numeric_field(0, "TIMES", "0 = forever", self.repeat_var)
        self.duration_var = ctk.StringVar(value=fmt_duration(self.settings.run_duration))
        self.entry_duration = numeric_field(0, "RUN FOR", "1:00 · 90s · 5m · 1h", self.duration_var)
        self.loop_delay_var = ctk.StringVar(value=str(self.settings.loop_delay))
        self.entry_loop_delay = numeric_field(1, "WAIT BETWEEN (s)", "pause after each run", self.loop_delay_var)

        self.lbl_estimate = ctk.CTkLabel(
            tab, text="", font=self._font(12, "bold", self.mono), text_color=C["accent"], anchor="w",
            justify="left", wraplength=self.WRAP,
        )
        self.lbl_estimate.grid(row=4, column=0, padx=10, pady=(6, 0), sticky="w")

        finish = ctk.CTkFrame(tab, fg_color="transparent")
        finish.grid(row=5, column=0, padx=8, pady=(8, 0), sticky="ew")
        finish.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(finish, text="When it's done", font=self._font(13, "bold"), text_color=C["text"]).grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        rev = {v: k for k, v in self.ON_FINISH.items()}
        self.seg_finish, self.finish_var = self._pill(finish, list(self.ON_FINISH), rev.get(self.settings.on_finish, "Nothing"))
        self.seg_finish.grid(row=0, column=1, sticky="ew")
        self._apply_limit_mode_ui()

    def _build_record_tab(self, tab: ctk.CTkFrame) -> None:
        self.sw_moves = self._option(
            tab, 0, "Record mouse movement",
            "Also save the path your mouse travels, not just clicks. Needed for hover menus and "
            "drawing — makes macros much longer.",
            self.settings.record_mouse_moves,
        )
        self.sw_scale = self._option(
            tab, 2, "Adjust if the window is resized",
            "If the target window is bigger or smaller than when you recorded, clicks land on the "
            "same spot relative to its size.",
            self.settings.scale_coordinates,
        )
        self.sw_min_rec = self._option(
            tab, 4, "Hide this app while recording",
            "Minimises Ghost so it's out of the way. Use your Record hotkey to stop.",
            self.settings.minimize_on_record,
        )
        self.sw_min_play = self._option(
            tab, 6, "Hide this app while playing",
            "Minimises Ghost during playback and brings it back when it finishes.",
            self.settings.minimize_on_play,
        )

    def _build_keys_tab(self, tab: ctk.CTkFrame) -> None:
        self._setting_label(
            tab, "Keyboard shortcuts", 0,
            "Work even when Ghost is hidden. Click a box, press a key.",
            top=6,
        )
        grid = ctk.CTkFrame(tab, fg_color="transparent")
        grid.grid(row=2, column=0, padx=8, pady=(8, 0), sticky="ew")
        grid.grid_columnconfigure(1, weight=1)
        self.hotkey_fields: dict[str, HotkeyField] = {}
        self.hotkey_status_lbls: dict[str, ctk.CTkLabel] = {}
        rows = [
            ("record", "hotkey_record", C["rec"], "Record / stop"),
            ("play", "hotkey_play", C["play"], "Play / stop"),
            ("stop", "hotkey_stop", C["muted"], "Stop everything"),
            ("target", "hotkey_target", C["accent"], "Target current app"),
        ]
        for r, (action, attr, dot, label) in enumerate(rows):
            ctk.CTkLabel(grid, text="●", font=self._font(11), text_color=dot, width=14).grid(
                row=r * 2, column=0, padx=(0, 8), pady=(4, 0)
            )
            ctk.CTkLabel(grid, text=label, font=self._font(13), text_color=C["text"], anchor="w").grid(
                row=r * 2, column=1, sticky="w", pady=(4, 0)
            )
            field = HotkeyField(grid, self, attr)
            field.grid(row=r * 2, column=2, sticky="e", pady=(4, 0))
            self.hotkey_fields[action] = field
            status = ctk.CTkLabel(grid, text="", font=self._font(10), text_color=C["hint"], anchor="e",
                                  height=13)
            status.grid(row=r * 2 + 1, column=1, columnspan=2, sticky="e")
            self.hotkey_status_lbls[action] = status
        self.lbl_hotkey_msg = ctk.CTkLabel(
            tab, text="", font=self._font(11), text_color=C["warn"], justify="left", wraplength=self.WRAP,
            anchor="w",
        )
        self.lbl_hotkey_msg.grid(row=3, column=0, padx=8, pady=(6, 0), sticky="w")

    def _build_app_tab(self, tab: ctk.CTkFrame) -> None:
        theme_row = ctk.CTkFrame(tab, fg_color="transparent")
        theme_row.grid(row=0, column=0, padx=8, pady=(6, 0), sticky="ew")
        theme_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(theme_row, text="Theme", font=self._font(13, "bold"), text_color=C["text"]).grid(
            row=0, column=0, sticky="w", padx=(0, 14)
        )
        mode = self.settings.appearance_mode.title()
        self.theme_var = ctk.StringVar(value=mode if mode in ("Light", "Dark", "System") else "Dark")
        self.seg_theme = ctk.CTkSegmentedButton(
            theme_row,
            values=["Light", "Dark", "System"],
            variable=self.theme_var,
            command=self._on_theme_changed,
            height=32,
            corner_radius=8,
            font=self._font(12),
        )
        self.seg_theme.grid(row=0, column=1, sticky="ew")
        self._style_segmented(self.seg_theme)

        self.sw_close_tray = self._option(
            tab, 3, "Keep running in the tray when closed",
            "✕ hides Ghost by the clock; tray ghost → Exit quits.",
            self.settings.close_to_tray,
        )
        self.sw_autostart = self._option(
            tab, 5, "Start with Windows",
            "Opens quietly in the tray when you sign in.",
            autostart.is_enabled(), command=self._on_autostart_toggled,
        )
        self.sw_on_top = self._option(
            tab, 7, "Always on top",
            "Keep Ghost above other windows.",
            self.settings.always_on_top,
        )
        self.sw_updates = self._option(
            tab, 9, "Tell me when a new version is out",
            "Asks GitHub once a day. Nothing about you is sent.",
            self.settings.check_updates,
        )
        buttons = ctk.CTkFrame(tab, fg_color="transparent")
        buttons.grid(row=11, column=0, padx=8, pady=(12, 0), sticky="w")
        self._ghost_button(buttons, "📂  Open macros folder", self.open_macros_folder, width=170).pack(side="left")
        self.btn_check_updates = self._ghost_button(
            buttons, "⟳  Check for updates", lambda: self.check_for_updates(manual=True), width=170
        )
        self.btn_check_updates.pack(side="left", padx=(8, 0))

    # ------------------------------------------------------------------
    # Hotkey capture
    # ------------------------------------------------------------------
    HOTKEY_LABELS = {"hotkey_record": "Record / stop", "hotkey_play": "Play / stop", "hotkey_stop": "Stop everything",
                     "hotkey_target": "Target current app"}
    HOTKEY_ATTRS = {"record": "hotkey_record", "play": "hotkey_play", "stop": "hotkey_stop", "target": "hotkey_target"}
    TK_KEY_NAMES = {
        "Prior": "PAGEUP", "Next": "PAGEDOWN", "Scroll_Lock": "SCROLLLOCK", "Pause": "PAUSE",
        "Insert": "INSERT", "Delete": "DELETE", "Home": "HOME", "End": "END", "space": "SPACE",
    }
    MODIFIER_KEYSYMS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Win_L", "Win_R",
                        "Caps_Lock", "Num_Lock", "App"}

    def _start_hotkey_capture(self, field: HotkeyField) -> None:
        if self._capture_field is not None:
            self._end_hotkey_capture()
        self._capture_field = field
        field.waiting()
        self.lbl_hotkey_msg.configure(text="")
        self.hotkeys.set_suspended(True)  # release keys so the one you press reaches us
        self._capture_bind = self.bind("<KeyPress>", self._on_capture_key, add="+")
        self._capture_click = self.bind("<Button-1>", self._on_capture_click, add="+")
        self.focus_force()

    def _on_capture_click(self, event) -> None:
        if self._capture_field is not None and event.widget is not self._capture_field and not str(
            event.widget
        ).startswith(str(self._capture_field)):
            self._end_hotkey_capture()

    def _end_hotkey_capture(self) -> None:
        field, self._capture_field = self._capture_field, None
        try:
            self.unbind("<KeyPress>", self._capture_bind)
            self.unbind("<Button-1>", self._capture_click)
        except Exception:
            pass
        if field is not None:
            field.show()
        self.hotkeys.set_suspended(False)

    def _on_capture_key(self, event) -> str:
        field = self._capture_field
        if field is None:
            return ""
        keysym = event.keysym
        if keysym in self.MODIFIER_KEYSYMS:
            return "break"  # wait for the real key
        if keysym == "Escape":
            self._end_hotkey_capture()
            return "break"
        if keysym in self.TK_KEY_NAMES:
            key = self.TK_KEY_NAMES[keysym]
        elif len(keysym) == 1 and keysym.isalnum():
            key = keysym.upper()
        elif keysym.upper().startswith("F") and keysym[1:].isdigit():
            key = keysym.upper()
        else:
            self.lbl_hotkey_msg.configure(text=f"“{keysym}” can't be used. Try an F-key or a Ctrl/Alt combo.")
            return "break"
        mods = []
        if event.state & 0x4:
            mods.append("CTRL")
        if event.state & 0x20000:
            mods.append("ALT")
        if event.state & 0x1:
            mods.append("SHIFT")
        combo = canonical_hotkey("+".join(mods + [key]))
        if (len(key) == 1 or key == "SPACE") and not ({"CTRL", "ALT"} & set(mods)):
            self.lbl_hotkey_msg.configure(
                text="Letters, numbers and Space need Ctrl or Alt with them — otherwise you couldn't type them."
            )
            return "break"
        for other_attr, other_label in self.HOTKEY_LABELS.items():
            if other_attr != field.attr and canonical_hotkey(getattr(self.settings, other_attr)) == combo:
                self.lbl_hotkey_msg.configure(text=f"{display_hotkey(combo)} is already used for {other_label}.")
                return "break"
        setattr(self.settings, field.attr, combo)
        self._end_hotkey_capture()
        self._on_settings_changed()
        return "break"

    def _on_hotkeys_registered(self, results: dict[str, bool]) -> None:
        self._hotkey_status = results
        if not hasattr(self, "hotkey_status_lbls"):
            return
        failed = []
        for action, ok in results.items():
            lbl = self.hotkey_status_lbls.get(action)
            if lbl is None:
                continue
            lbl.unbind("<Button-1>")
            if ok:
                lbl.configure(text="✓ active", text_color=C["play"], cursor="")
            else:
                failed.append(action)
                fix = self.hotkeys.last_suggestions.get(action, "")
                if fix:
                    lbl.configure(text=f"⚠ taken by another app — click to use {display_hotkey(fix)}",
                                  text_color=C["warn"], cursor="hand2")
                    lbl.bind("<Button-1>", lambda _e, a=action, k=fix: self._use_hotkey(a, k))
                else:
                    lbl.configure(text="⚠ taken by another app — pick a different key", text_color=C["warn"],
                                  cursor="")
        if failed and self._capture_field is None:
            self._set_status("A hotkey couldn't be set — see Settings › Keys", "warn")

    def _use_hotkey(self, action: str, key: str) -> None:
        setattr(self.settings, self.HOTKEY_ATTRS[action], key)
        self.lbl_hotkey_msg.configure(text="")
        self._on_settings_changed()
        self._set_status(f"{self.HOTKEY_LABELS[self.HOTKEY_ATTRS[action]]} is now {display_hotkey(key)}", "ok")

    def _on_autostart_toggled(self) -> None:
        want = bool(self.sw_autostart.get())
        try:
            autostart.set_enabled(want)
            self._set_status("Ghost will start with Windows" if want else "Ghost won't start with Windows", "ok")
        except PermissionError:
            self.sw_autostart.select() if autostart.is_enabled() else self.sw_autostart.deselect()
            self._set_status("Windows security blocked the startup setting", "warn")
            if messagebox.askyesno(
                "Start with Windows",
                "Windows security on this PC blocked Ghost from adding itself to startup.\n\n"
                "You can still do it yourself: put a shortcut to Ghost Macro Recorder in your "
                "Startup folder.\n\nOpen the Startup folder now?",
                parent=self,
            ):
                os.startfile(autostart.startup_folder())  # noqa: S606
        except OSError as exc:
            self.sw_autostart.select() if autostart.is_enabled() else self.sw_autostart.deselect()
            self._set_status(f"Couldn't change startup setting: {exc}", "warn")

    def open_macros_folder(self) -> None:
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(MACROS_DIR)  # noqa: S606 - opens Explorer on our own data folder

    def set_target_to_current_window(self) -> None:
        """Hotkey: make whatever window you're in right now the target."""
        if self.recorder.is_recording or self.player.is_playing:
            return
        hwnd = get_foreground_root_window()
        target = get_window_target(hwnd) if hwnd else None
        if target is None or target.pid == self.own_pid:
            self._set_status("Switch to the app you want, then press the hotkey", "warn")
            return
        self._finish_pick_window(target)

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=22, pady=(4, 12), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self.lbl_footer = ctk.CTkLabel(
            footer,
            text="Elevated targets need this app run as Administrator. "
            "Chromium/UWP apps may need Foreground mode.",
            font=self._font(10),
            text_color=C["muted"],
            anchor="w",
        )
        self.lbl_footer.grid(row=0, column=0, sticky="w")
        # Shown in place of the footer hint when a newer version is out
        self.update_bar = ctk.CTkFrame(footer, fg_color=C["panel"], corner_radius=10, border_width=1,
                                       border_color=C["accent"])
        self.lbl_update = ctk.CTkLabel(self.update_bar, text="", font=self._font(12, "bold"), text_color=C["text"])
        self.lbl_update.pack(side="left", padx=(12, 10), pady=4)
        self.btn_update = ctk.CTkButton(
            self.update_bar, text="Update now", command=self.start_update, width=110, height=28,
            corner_radius=8, fg_color=C["accent"], hover_color=C["accent_hover"],
            text_color="#0c0d10", font=self._font(12, "bold"),
        )
        self.btn_update.pack(side="left", padx=(0, 6), pady=4)
        self.btn_update_notes = self._ghost_button(self.update_bar, "What's new", self._open_update_page, width=90)
        self.btn_update_notes.configure(height=28)
        self.btn_update_notes.pack(side="left", padx=(0, 6), pady=4)
        self.btn_update_skip = self._ghost_button(self.update_bar, "Skip", self._skip_update, width=56)
        self.btn_update_skip.configure(height=28)
        self.btn_update_skip.pack(side="left", padx=(0, 8), pady=4)
        caps = ctk.CTkFrame(footer, fg_color="transparent")
        caps.grid(row=0, column=1, sticky="e")
        self.footer_caps: list[tuple[ctk.CTkLabel, str]] = []
        for attr, word in (("hotkey_record", "rec"), ("hotkey_play", "play"), ("hotkey_stop", "panic")):
            cap = self._keycap(caps, "")
            cap.pack(side="left", padx=(8, 3))
            ctk.CTkLabel(caps, text=word, font=self._font(10), text_color=C["muted"]).pack(side="left")
            self.footer_caps.append((cap, attr))
        self._refresh_button_labels()

    def _apply_treeview_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        bg = col("panel")
        fg = col("text")
        style.configure(
            "Deck.Treeview",
            background=bg,
            foreground=fg,
            fieldbackground=bg,
            borderwidth=0,
            relief="flat",
            rowheight=31,
            font=(self.sans, 10),
        )
        style.layout("Deck.Treeview", [("Deck.Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Deck.Treeview.Heading",
            background=bg,
            foreground=col("muted"),
            relief="flat",
            borderwidth=0,
            padding=(6, 6),
            font=(self.sans, 8, "bold"),
        )
        style.map(
            "Deck.Treeview.Heading",
            background=[("active", col("panel_hi"))],
            relief=[("active", "flat")],
        )
        style.map(
            "Deck.Treeview",
            background=[("selected", col("ghost_hover"))],
            foreground=[("selected", col("accent"))],
        )
        for lane, _label, color, _types in LANES:
            self.tree.tag_configure(lane, foreground=color[_mode_index()] if lane != "move" else col("muted"))
        self.tree.tag_configure("odd", background=col("panel_hi"))
        self._mark_tape_dirty()

    # ------------------------------------------------------------------
    # Status, theme & tape rendering
    # ------------------------------------------------------------------
    def _apply_limit_mode_ui(self) -> None:
        timed = self.limit_var.get() == "Run for time"
        show, hide = (self.entry_duration, self.entry_repeat) if timed else (self.entry_repeat, self.entry_duration)
        hide.master.grid_remove()
        show.master.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self._update_estimate()

    def _update_estimate(self) -> None:
        """Preview how many loops / steps the current run settings will play."""
        if not hasattr(self, "lbl_estimate"):
            return
        events = self.macro.events
        if self.settings.run_limit_mode == "time":
            self._run_summary = f"Keeps repeating for {fmt_duration(self.settings.run_duration)}"
        elif self.settings.repeat_count == 0:
            self._run_summary = "Repeats until you press Stop"
        else:
            n = self.settings.repeat_count
            self._run_summary = f"{n} time{'s' if n != 1 else ''}"
        if events and self.settings.run_limit_mode == "count" and self.settings.repeat_count:
            n = self.settings.repeat_count
            total = n * self.macro.duration / max(0.05, self.settings.speed) + (n - 1) * self.settings.loop_delay
            self._run_summary += f" · about {fmt_duration(total)}"
        self._update_summary()
        if not events:
            self.lbl_estimate.configure(text="Record a macro to see a run estimate.")
            return
        speed = max(0.05, self.settings.speed)
        gap = self.settings.loop_delay
        loop_len = self.macro.duration / speed
        steps = len(events)
        if self.settings.run_limit_mode == "time":
            total = self.settings.run_duration
            cycle = loop_len + gap
            if cycle <= 0:
                self.lbl_estimate.configure(text=f"Loops continuously for {fmt_duration(total)}")
                return
            full = int(total // cycle)
            if full == 0 and total >= loop_len:
                full = 1
            remainder = max(0.0, total - full * cycle)
            t0 = events[0].timestamp
            partial = sum(1 for ev in events if (ev.timestamp - t0) / speed < remainder)
            partial = partial if partial < steps else 0
            loops_txt = f"{full} full loop{'s' if full != 1 else ''}"
            if partial:
                loops_txt += f" + {partial} steps"
            self.lbl_estimate.configure(
                text=f"≈ {loops_txt}\n≈ {full * steps + partial:,} steps in {fmt_duration(total)}"
            )
        else:
            n = self.settings.repeat_count
            if n == 0:
                self.lbl_estimate.configure(text=f"∞ loops · {steps} steps each\nRuns until you press stop")
            else:
                total = n * loop_len + (n - 1) * gap
                self.lbl_estimate.configure(
                    text=f"{n} loop{'s' if n != 1 else ''} · {n * steps:,} steps\n≈ {fmt_duration(total)} total"
                )

    def _set_status(self, text: str, tone: str = "info") -> None:
        color = {
            "info": C["info"],
            "ok": C["play"],
            "rec": C["rec"],
            "warn": C["warn"],
            "accent": C["accent"],
        }.get(tone, C["info"])
        self._status_tone = tone
        self.lbl_led.configure(text_color=color)
        self.lbl_status.configure(text=text)

    def _update_theme_glyph(self) -> None:
        # Show the mode you'd switch *to*.
        self.btn_theme.configure(text="☀" if _mode_index() == 1 else "☾")

    def _toggle_theme(self) -> None:
        new_mode = "Light" if _mode_index() == 1 else "Dark"
        self._on_theme_changed(new_mode)

    def _mark_tape_dirty(self) -> None:
        self._tape_dirty = True

    def _tape_events(self) -> list[MacroEvent]:
        return self._live_events if self.recorder.is_recording else self.macro.events

    def _draw_tape(self) -> None:
        cv = self.tape
        cv.configure(bg=col("panel_hi"))
        cv.delete("all")
        w = max(cv.winfo_width(), 50)
        h = max(cv.winfo_height(), 40)
        label_font = (self.sans, 7, "bold")
        measure = tkfont.Font(font=label_font)
        gutter = 22 + max(measure.measure(label) for _l, label, _c, _t in LANES)
        lane_h = h / len(LANES)
        x0, x1 = gutter, w - 8
        span_w = max(1, x1 - x0)

        # Lanes & labels
        for i, (_lane, label, _color, _types) in enumerate(LANES):
            y = i * lane_h
            if i:
                cv.create_line(0, y, w, y, fill=col("line"))
            cv.create_text(
                10, y + lane_h / 2, text=label, anchor="w", fill=col("muted"), font=label_font
            )
        cv.create_line(gutter - 6, 0, gutter - 6, h, fill=col("line"))

        events = self._tape_events()
        recording = self.recorder.is_recording
        if not events and not recording:
            cv.create_text(
                x0 + span_w / 2, h / 2, text="— blank tape —", fill=col("muted"), font=(self.sans, 9)
            )
            self.lbl_tape_info.configure(text="empty reel")
            return

        t0 = events[0].timestamp if events else 0.0
        if recording and self._record_started_at is not None:
            span = max(time.perf_counter() - self._record_started_at, 1.0)
            t0 = 0.0 if not events else min(t0, 0.0)
        else:
            span = max((events[-1].timestamp - t0) if events else 0.0, 0.5)

        # Second grid
        step = 1.0
        for candidate in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
            if span / candidate <= 12:
                step = float(candidate)
                break
        s = 0.0
        while s <= span:
            gx = x0 + (s / span) * span_w
            cv.create_line(gx, 0, gx, h, fill=col("line"), dash=(1, 3))
            s += step

        # Bucket events per pixel column per lane to keep huge reels fast
        lane_index = {lane: i for i, (lane, *_rest) in enumerate(LANES)}
        seen: set[tuple[int, int]] = set()
        mode = _mode_index()
        colors = {lane: c[mode] for lane, _l, c, _t in LANES}
        for ev in events:
            lane = LANE_OF.get(ev.event_type)
            if lane is None:
                continue
            px = int(x0 + ((ev.timestamp - t0) / span) * span_w)
            key = (lane_index[lane], px)
            if key in seen:
                continue
            seen.add(key)
            li = lane_index[lane]
            cy = li * lane_h + lane_h / 2
            half = lane_h * (0.18 if lane == "move" else 0.32)
            cv.create_line(px, cy - half, px, cy + half, fill=colors[lane], width=2)

        # Heads
        if recording:
            cv.create_line(x1, 0, x1, h, fill=col("rec"), width=2)
            cv.create_polygon(x1 - 5, 0, x1 + 5, 0, x1, 7, fill=col("rec"), outline="")
        elif self.player.is_playing and events and self._play_ev_idx:
            idx = min(self._play_ev_idx, len(events)) - 1
            px = x0 + ((events[idx].timestamp - t0) / span) * span_w
            cv.create_rectangle(x0, 0, px, h, fill=col("accent"), stipple="gray12", outline="")
            cv.create_line(px, 0, px, h, fill=col("accent"), width=2)
            cv.create_polygon(px - 5, 0, px + 5, 0, px, 7, fill=col("accent"), outline="")

        counts = {lane: 0 for lane, *_r in LANES}
        for ev in events:
            lane = LANE_OF.get(ev.event_type)
            if lane:
                counts[lane] += 1
        self.lbl_tape_info.configure(
            text=f"{counts['click']} clicks · {counts['key']} keys · "
            f"{counts['scroll']} scrolls · {counts['move']} moves"
        )

    def _tick(self) -> None:
        """UI heartbeat: timecode, LED blink and throttled tape redraws."""
        if self._is_closing:
            return
        recording = self.recorder.is_recording
        # "System" mode can flip under us when Windows changes theme; the raw tk
        # canvas and ttk treeview don't follow CTk automatically, so repaint them.
        mode_now = _mode_index()
        if mode_now != getattr(self, "_last_mode", mode_now):
            self._apply_treeview_style()
            self._rebuild_timeline()
            self._update_theme_glyph()
        self._last_mode = mode_now
        self._repaint_all_segments()
        if self.hotkeys.results_version != self._hotkey_results_seen:
            self._hotkey_results_seen = self.hotkeys.results_version
            self._on_hotkeys_registered(dict(self.hotkeys.last_results))
        if recording and self._record_started_at is not None:
            self.lbl_timecode.configure(
                text=fmt_timecode(time.perf_counter() - self._record_started_at),
                text_color=C["rec"],
            )
            self._blink = not self._blink
            self.lbl_led.configure(text_color=C["rec"] if self._blink else C["line"])
            self._tape_dirty = True
        if self._tape_dirty:
            self._tape_dirty = False
            try:
                self._draw_tape()
            except tk.TclError:
                pass
        self.after(250 if recording else 120, self._tick)

    # ------------------------------------------------------------------
    # Window Picker & Target Management
    # ------------------------------------------------------------------
    def refresh_windows(self) -> None:
        self._window_choices = list_visible_windows(exclude_pid=self.own_pid)
        if self._selected_target is not None:
            matched = next((w for w in self._window_choices if w.hwnd == self._selected_target.hwnd), None)
            if matched:
                self._selected_target = matched
            else:
                # Keep the chosen window visible in the list even if it's minimised/hidden now
                self._window_choices.insert(0, self._selected_target)
        self.picker.set_choices(self._window_choices)
        self.picker.set_selected(self._selected_target)

    def _on_target_selected(self, target: Optional[WindowTarget]) -> None:
        self._selected_target = target
        self._update_target_hint()
        if target is not None:
            self._set_status(f"Target: {target.process_name}", "ok")

    def start_pick_window(self) -> None:
        if self._picking_window:
            return
        self._picking_window = True
        self.btn_pick_win.configure(state="disabled")

        def countdown() -> None:
            for sec in (3, 2, 1):
                self.after(
                    0,
                    lambda s=sec: (
                        self._set_status(f"Switch to your target window… {s}", "accent"),
                        self.btn_pick_win.configure(text=f"◎  {s}…"),
                    ),
                )
                time.sleep(1.0)
            hwnd = get_foreground_root_window()
            target = get_window_target(hwnd) if hwnd else None
            self.after(0, lambda t=target: self._finish_pick_window(t))

        threading.Thread(target=countdown, daemon=True).start()

    def _finish_pick_window(self, target: Optional[WindowTarget]) -> None:
        self._picking_window = False
        self.btn_pick_win.configure(state="normal", text="◎  Pick window")
        self.refresh_windows()
        if target and target.pid != self.own_pid:
            if not any(w.hwnd == target.hwnd for w in self._window_choices):
                self._window_choices.insert(0, target)
                self.picker.set_choices(self._window_choices)
            self._selected_target = target
            self.picker.set_selected(target)
            self._set_status(f"Target locked: {target.process_name}", "ok")
            self._update_target_hint()
        else:
            self._set_status("Picked this app — switch to another window next time", "warn")

    # ------------------------------------------------------------------
    # Settings Handlers
    # ------------------------------------------------------------------
    def _on_speed_slide(self, value: float) -> None:
        rounded = round(float(value), 2)
        self.lbl_speed.configure(text=f"{rounded:.2f}×")
        self._on_settings_changed()

    def _on_theme_changed(self, value: str) -> None:
        # Lay a plain panel over the window, repaint every widget underneath it, then
        # fade the panel away, so nobody sees widgets switching colour one at a time.
        cover = self._cover_window() if self._revealed and self.state() == "normal" else None
        self._apply_theme(value)
        if cover is not None:
            self.update_idletasks()
            self._fade_out_cover(cover)

    def _cover_window(self) -> Optional[tk.Toplevel]:
        try:
            cover = tk.Toplevel(self)
            cover.overrideredirect(True)
            cover.configure(bg=col("bg"))
            cover.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{self.winfo_rootx()}+{self.winfo_rooty()}")
            cover.attributes("-topmost", True)
            cover.update()
            return cover
        except Exception:
            return None

    def _fade_out_cover(self, cover: tk.Toplevel, alpha: float = 1.0) -> None:
        alpha -= 0.12
        try:
            if alpha <= 0:
                cover.destroy()
                return
            cover.attributes("-alpha", alpha)
        except Exception:
            return
        self.after(16, self._fade_out_cover, cover, alpha)

    def _apply_theme(self, value: str) -> None:
        self.settings.appearance_mode = value
        ctk.set_appearance_mode(value)
        if hasattr(self, "theme_var") and self.theme_var.get() != value:
            self.theme_var.set(value)
            self._repaint_segment_text(self.seg_theme)
        self._update_theme_glyph()
        self._apply_treeview_style()
        self._rebuild_timeline()
        self.settings.save(SETTINGS_PATH)

    def _on_settings_changed(self, *_args: object) -> None:
        self.settings.playback_mode = (
            "background" if self.mode_var.get().startswith("Background") else "foreground"
        )
        self.settings.record_scope = "target" if self.scope_var.get() == "This window only" else "all"
        self.lbl_engine_help.configure(text=self.ENGINE_HELP[self.mode_var.get()])
        self.lbl_limit_help.configure(text=self.LIMIT_HELP[self.limit_var.get()])
        self._update_target_hint()
        self.settings.speed = round(float(self.slider_speed.get()), 2)
        self.settings.record_mouse_moves = bool(self.sw_moves.get())
        self.settings.scale_coordinates = bool(self.sw_scale.get())
        self.settings.minimize_on_record = bool(self.sw_min_rec.get())
        self.settings.minimize_on_play = bool(self.sw_min_play.get())
        self.settings.close_to_tray = bool(self.sw_close_tray.get())
        self.settings.start_delay = self.COUNTDOWN.get(self.countdown_var.get(), 0)
        self.settings.humanize_pct = self.HUMANIZE.get(self.humanize_var.get(), 0)
        self.settings.on_finish = self.ON_FINISH.get(self.finish_var.get(), "none")
        self.settings.always_on_top = bool(self.sw_on_top.get())
        self.attributes("-topmost", self.settings.always_on_top)
        self.settings.check_updates = bool(self.sw_updates.get())

        try:
            self.settings.repeat_count = max(0, int(self.repeat_var.get().strip()))
        except ValueError:
            self.settings.repeat_count = 1
            self.repeat_var.set("1")

        try:
            self.settings.loop_delay = max(0.0, float(self.loop_delay_var.get().strip()))
        except ValueError:
            self.settings.loop_delay = 0.25
            self.loop_delay_var.set("0.25")

        self.settings.run_limit_mode = "time" if self.limit_var.get() == "Run for time" else "count"
        duration = parse_duration(self.duration_var.get())
        if duration is None:
            duration = self.settings.run_duration
        self.settings.run_duration = min(max(duration, 1.0), 24 * 3600.0)
        self.duration_var.set(fmt_duration(self.settings.run_duration))
        self._apply_limit_mode_ui()

        for field in getattr(self, "hotkey_fields", {}).values():
            if field is not self._capture_field:
                field.show()
        self.hotkeys.set_hotkeys(
            self.settings.hotkey_record,
            self.settings.hotkey_play,
            self.settings.hotkey_stop,
            self.settings.hotkey_target,
        )
        self._refresh_button_labels()
        self._update_estimate()
        self.settings.save(SETTINGS_PATH)

    def _refresh_button_labels(self) -> None:
        self.btn_record.configure(text="■" if self.recorder.is_recording else "●")
        self.btn_play.configure(text="■" if self.player.is_playing else "▶")
        self.cap_record.configure(text=f" {display_hotkey(self.settings.hotkey_record)} ")
        self.cap_play.configure(text=f" {display_hotkey(self.settings.hotkey_play)} ")
        self.cap_stop.configure(text=f" {display_hotkey(self.settings.hotkey_stop)} ")
        for cap, attr in getattr(self, "footer_caps", []):
            cap.configure(text=f" {display_hotkey(getattr(self.settings, attr))} ")

    # ------------------------------------------------------------------
    # Recording & Playback Control
    # ------------------------------------------------------------------
    def toggle_record(self) -> None:
        if self.player.is_playing:
            return
        self._cancel_countdown()  # never start playback in the middle of a new recording
        if self.recorder.is_recording:
            events = self.recorder.stop()
            self.macro.events = events
            self.macro.default_target = self._selected_target
            self._live_events = []
            self._record_started_at = None
            self._macro_file = None
            self._set_dirty(bool(events))
            self._rebuild_timeline()
            if self.settings.minimize_on_record:
                self.show_from_tray()
            return

        if not self._confirm_discard("start a new recording"):
            return
        self._on_settings_changed()
        if self.settings.record_scope == "target" and self._selected_target is None:
            self._set_status("Choose a target window first (or switch to Every window)", "warn")
            return
        self.tree.delete(*self.tree.get_children())
        self.macro = Macro(default_target=self._selected_target)
        self._live_events = []
        ignored = {
            self.settings.hotkey_record,
            self.settings.hotkey_play,
            self.settings.hotkey_stop,
            self.settings.hotkey_target,
        }
        if self.settings.minimize_on_record:
            self.iconify()
        try:
            self._record_started_at = time.perf_counter()
            self.recorder.start(
                target_window=self._selected_target,
                scope=self.settings.record_scope,
                record_mouse_moves=self.settings.record_mouse_moves,
                ignored_hotkeys=ignored,
            )
        except Exception as exc:
            self._record_started_at = None
            self.show_from_tray()
            self._set_status(f"Record failed: {exc}", "rec")

    def toggle_play(self) -> None:
        if self.recorder.is_recording:
            return
        if self.player.is_playing:
            self.player.stop()
            return
        if self._countdown_job is not None:
            self._cancel_countdown()
            self._set_status("Playback cancelled", "info")
            return
        if not self.macro.events:
            self._set_status("Record or open a macro first", "warn")
            return

        self._on_settings_changed()
        if self.settings.minimize_on_play:
            self.iconify()
        if self.settings.start_delay > 0:
            self._countdown_left = int(self.settings.start_delay)
            self._countdown_tick()
            return
        self._start_playback()

    def _countdown_tick(self) -> None:
        if self._countdown_left <= 0:
            self._countdown_job = None
            self._start_playback()
            return
        self._set_status(f"Playing in {self._countdown_left}…  (press Play again to cancel)", "accent")
        self.lbl_timecode.configure(text=f"-{self._countdown_left:02d}.000", text_color=C["play"])
        self._countdown_left -= 1
        self._countdown_job = self.after(1000, self._countdown_tick)

    def _cancel_countdown(self) -> None:
        if self._countdown_job is not None:
            self.after_cancel(self._countdown_job)
            self._countdown_job = None
            self.lbl_timecode.configure(text=fmt_timecode(self.macro.duration), text_color=C["accent"])

    def _start_playback(self) -> None:
        self._play_ev_idx = 0
        self._play_started_at = time.perf_counter()
        self.player.start(
            macro=self.macro,
            settings=self.settings,
            override_target=self._selected_target,
        )

    def stop_all(self) -> None:
        self._cancel_countdown()
        if self.recorder.is_recording:
            self.toggle_record()
        if self.player.is_playing:
            self.player.stop()

    # ------------------------------------------------------------------
    # Background Callbacks -> Main Thread
    # ------------------------------------------------------------------
    def _on_recorded_event_bg(self, ev: MacroEvent) -> None:
        self.after(0, lambda e=ev: self._append_timeline_row(e))

    def _on_record_state_bg(self, is_recording: bool) -> None:
        self.after(0, lambda rec=is_recording: self._update_record_ui(rec))

    def _on_play_progress_bg(self, loop_idx: int, total_loops: int, ev_idx: int, total_ev: int) -> None:
        self.after(
            0,
            lambda l=loop_idx, tl=total_loops, i=ev_idx, te=total_ev: self._update_play_progress(
                l, tl, i, te
            ),
        )

    def _on_play_state_bg(self, is_playing: bool, message: str) -> None:
        self.after(0, lambda p=is_playing, m=message: self._update_play_ui(p, m))

    def _update_record_ui(self, is_recording: bool) -> None:
        self._refresh_button_labels()
        if is_recording:
            self.btn_play.configure(state="disabled")
            self.btn_record.configure(border_color=C["rec"])
            scope_txt = (
                self._selected_target.process_name
                if (self.settings.record_scope == "target" and self._selected_target)
                else "all windows"
            )
            self._set_status(f"Recording · {scope_txt}", "rec")
            self.tray.set_state("recording", "Recording in background...")
        else:
            self.btn_play.configure(state="normal")
            self.btn_record.configure(border_color=C["panel"])
            self.lbl_timecode.configure(
                text=fmt_timecode(self.macro.duration), text_color=C["accent"]
            )
            self._set_status(f"Idle — {len(self.macro.events)} events on the reel", "info")
            self.tray.set_state("idle", APP_NAME)
        self._mark_tape_dirty()

    def _update_play_progress(self, loop_idx: int, total_loops: int, ev_idx: int, total_ev: int) -> None:
        if self.settings.run_limit_mode == "time" and self._play_started_at is not None:
            left = max(0.0, self.settings.run_duration - (time.perf_counter() - self._play_started_at))
            loop_str = f"{loop_idx} · {fmt_duration(left)} left"
        else:
            loop_str = f"{loop_idx}/∞" if total_loops == 0 else f"{loop_idx}/{total_loops}"
        mode = "BG" if self.settings.playback_mode == "background" else "FG"
        self._set_status(f"Playing [{mode}] · loop {loop_str} · step {ev_idx}/{total_ev}", "ok")
        self._play_ev_idx = ev_idx
        events = self.macro.events
        if events and 0 < ev_idx <= len(events):
            self.lbl_timecode.configure(
                text=fmt_timecode(events[ev_idx - 1].timestamp - events[0].timestamp),
                text_color=C["play"],
            )
        self._mark_tape_dirty()

    def _update_play_ui(self, is_playing: bool, message: str) -> None:
        self._refresh_button_labels()
        if is_playing:
            self.btn_record.configure(state="disabled")
            self.btn_play.configure(border_color=C["play"])
            self._set_status(message, "ok")
            self.tray.set_state("playing", message)
        else:
            self.btn_record.configure(state="normal")
            self.btn_play.configure(border_color=C["panel"])
            self._play_ev_idx = 0
            self.lbl_timecode.configure(
                text=fmt_timecode(self.macro.duration), text_color=C["accent"]
            )
            self._set_status(message, "info")
            self.tray.set_state("idle", APP_NAME)
            if message.startswith(("Playback complete", "Time limit")):
                self._on_playback_finished(message)
            if self.settings.minimize_on_play and not self._is_closing:
                self.show_from_tray()
        self._mark_tape_dirty()

    def _on_playback_finished(self, message: str) -> None:
        if self.settings.on_finish == "notify":
            self.tray.notify(APP_NAME, f"Finished: {message}")
        elif self.settings.on_finish == "sound":
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Timeline & File Operations
    # ------------------------------------------------------------------
    def _insert_row(self, idx: int, ev: MacroEvent) -> str:
        action, details = ev.summary()
        target_name = ev.target.display_label if ev.target else "—"
        tags = [LANE_OF.get(ev.event_type, "move")]
        if idx % 2 == 0:
            tags.append("odd")
        return self.tree.insert(
            "",
            "end",
            values=(idx, f"{ev.timestamp:.3f}", action, target_name, details),
            tags=tuple(tags),
        )

    def _append_timeline_row(self, ev: MacroEvent) -> None:
        self._live_events.append(ev)
        idx = len(self.tree.get_children()) + 1
        iid = self._insert_row(idx, ev)
        self.tree.see(iid)
        self.lbl_empty.place_forget()
        self.lbl_counts.configure(text=f"{idx} events · {ev.timestamp:.2f}s")
        self._mark_tape_dirty()

    def _rebuild_timeline(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for idx, ev in enumerate(self.macro.events, start=1):
            self._insert_row(idx, ev)
        self.lbl_counts.configure(
            text=f"{len(self.macro.events)} events · {self.macro.duration:.2f}s"
        )
        if not self.recorder.is_recording:
            self.lbl_timecode.configure(text=fmt_timecode(self.macro.duration))
        self._update_estimate()
        if self.macro.events:
            self.lbl_empty.place_forget()
        else:
            self.lbl_empty.place(relx=0.5, rely=0.5, anchor="center")
        self._mark_tape_dirty()

    def clear_macro(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            return
        if not self._confirm_discard("clear it"):
            return
        self.macro.events.clear()
        self._macro_file = None
        self._set_dirty(False)
        self._rebuild_timeline()
        self._set_status("Reel cleared", "info")

    def new_macro(self) -> None:
        """Start fresh: offer to save the current macro, then empty the reel."""
        if self.recorder.is_recording or self.player.is_playing:
            self._set_status("Stop recording / playback first", "warn")
            return
        if not self._confirm_discard("start a new one"):
            return
        self.macro = Macro(default_target=self._selected_target)
        self._macro_file = None
        self._set_dirty(False)
        self._rebuild_timeline()
        self.lbl_timecode.configure(text=fmt_timecode(0))
        self._set_status(f"New macro — press ● REC ({display_hotkey(self.settings.hotkey_record)}) to record", "info")

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        name = self._macro_file.stem if self._macro_file else ("Untitled macro" if self.macro.events else "")
        mark = " •" if dirty else ""
        self._update_summary()
        self.title(f"{name}{mark} — {APP_NAME}" if name else f"{APP_NAME} v{APP_VERSION}")

    def _confirm_discard(self, action: str) -> bool:
        """Ask to save unsaved work before it gets replaced. Returns False if the user cancels."""
        if not self._dirty or not self.macro.events:
            return True
        self.show_from_tray()
        name = self._macro_file.name if self._macro_file else "Your current macro"
        answer = messagebox.askyesnocancel(
            "Save your macro?",
            f"{name} ({len(self.macro.events)} steps) has unsaved changes.\n\n"
            f"Do you want to save it before you {action}?\n\n"
            "Yes — save it first\nNo — throw it away\nCancel — go back",
            icon="warning",
            parent=self,
        )
        if answer is None:
            return False
        if answer:
            return self.save_macro_dialog()
        return True

    def request_exit(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            self.stop_all()
        if self._confirm_discard("quit"):
            self.quit_app()

    # --- steps list: drag-select -------------------------------------
    def _on_tree_press(self, event) -> None:
        self.tree.focus_set()
        if event.state & 0x0005:  # Shift / Ctrl: let the list's own range/toggle click work
            self._drag_anchor = None
            return
        if self.tree.identify_region(event.x, event.y) == "heading":
            self._drag_anchor = None
            return
        self._drag_anchor = self.tree.identify_row(event.y) or None

    def _select_range_to(self, row: str) -> None:
        if not self._drag_anchor or not row:
            return
        items = self.tree.get_children()
        try:
            a, b = items.index(self._drag_anchor), items.index(row)
        except ValueError:
            return
        lo, hi = min(a, b), max(a, b)
        self.tree.selection_set(items[lo:hi + 1])
        self.tree.focus(row)

    def _on_tree_drag(self, event) -> str | None:
        if not self._drag_anchor:
            return None
        self._drag_y = event.y
        height = self.tree.winfo_height()
        if event.y < 4 or event.y > height - 4:
            if self._drag_scroll_job is None:
                self._drag_autoscroll()
        else:
            self._select_range_to(self.tree.identify_row(event.y))
        return "break"  # stop the default handler from moving the anchor

    def _drag_autoscroll(self) -> None:
        self._drag_scroll_job = None
        if not self._drag_anchor:
            return
        height = self.tree.winfo_height()
        if self._drag_y < 4:
            self.tree.yview_scroll(-1, "units")
            row = self.tree.identify_row(6)
        elif self._drag_y > height - 4:
            self.tree.yview_scroll(1, "units")
            row = self.tree.identify_row(height - 6)
        else:
            return
        self._select_range_to(row)
        self._drag_scroll_job = self.after(40, self._drag_autoscroll)

    def _on_tree_release(self, _event) -> None:
        self._drag_anchor = None
        if self._drag_scroll_job:
            self.after_cancel(self._drag_scroll_job)
            self._drag_scroll_job = None

    def _select_all_steps(self, _event=None) -> str:
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def delete_selected_events(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            return
        selected = self.tree.selection()
        if not selected:
            return
        indices = sorted((self.tree.index(item) for item in selected), reverse=True)
        for idx in indices:
            if 0 <= idx < len(self.macro.events):
                self.macro.events.pop(idx)
        self._set_dirty(True)
        self._rebuild_timeline()
        self._set_status(f"Deleted {len(indices)} step(s)", "info")

    def trim_mouse_moves(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            return
        before = len(self.macro.events)
        self.macro.events = [ev for ev in self.macro.events if ev.event_type != "mouse_move"]
        removed = before - len(self.macro.events)
        if removed:
            self._set_dirty(True)
        self._rebuild_timeline()
        self._set_status(f"Trimmed {removed} mouse moves", "info")

    def save_macro_dialog(self) -> bool:
        """Save the current macro. Returns True if it was saved."""
        if not self.macro.events:
            messagebox.showinfo("Save Macro", "There are no recorded steps to save yet.", parent=self)
            return False
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self,
            initialdir=str(self._macro_file.parent if self._macro_file else MACROS_DIR),
            initialfile=self._macro_file.name if self._macro_file else "",
            defaultextension=".json",
            filetypes=[("Macro JSON", "*.json")],
            title="Save Macro",
        )
        if not path:
            return False
        try:
            self.macro.name = Path(path).stem
            self.macro.save(path)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return False
        self._macro_file = Path(path)
        self._set_dirty(False)
        self._set_status(f"Saved {Path(path).name}", "ok")
        return True

    def load_macro_dialog(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            return
        if not self._confirm_discard("open another macro"):
            return
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        path = filedialog.askopenfilename(
            initialdir=str(MACROS_DIR),
            filetypes=[("Macro JSON", "*.json")],
            title="Load Macro",
        )
        if not path:
            return
        try:
            self.macro = Macro.load(path)
        except Exception as exc:
            messagebox.showerror("Load Macro Failed", str(exc), parent=self)
            return
        self._macro_file = Path(path)
        self._set_dirty(False)
        self._rebuild_timeline()
        self._set_status(f"Loaded {Path(path).name} · {len(self.macro.events)} events", "info")

    def show_about_dialog(self) -> None:
        data_dir = get_user_data_dir()
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "Window-aware background macro recorder and player.\n\n"
            f"Hotkeys: {self.settings.hotkey_record} Record/Stop | "
            f"{self.settings.hotkey_play} Play/Stop | "
            f"{self.settings.hotkey_stop} Emergency Stop\n\n"
            f"Settings & Macros folder:\n{data_dir}\n\n"
            "Tip: If an app runs as Administrator or ignores background Win32 "
            "messages, switch Playback Mode to Foreground (Standard).",
        )

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    def _auto_update_check(self) -> None:
        if self._is_closing:
            return
        due = time.time() - self.settings.last_update_check >= updater.CHECK_EVERY
        if self.settings.check_updates and due and self._update_info is None:
            self.check_for_updates(manual=False)
        self.after(3600 * 1000, self._auto_update_check)  # look again in an hour (checks stay once a day)

    def check_for_updates(self, manual: bool = False) -> None:
        if self._updating:
            return
        if manual:
            self.btn_check_updates.configure(text="Checking…", state="disabled")

        def work() -> None:
            info, error = None, ""
            try:
                info = updater.check_latest()
            except Exception:  # offline, GitHub down, rate limit...
                error = "Couldn't reach GitHub. Check your internet connection and try again."
            self.after(0, lambda: self._on_update_result(info, error, manual))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_result(self, info: Optional[updater.UpdateInfo], error: str, manual: bool) -> None:
        self.btn_check_updates.configure(text="⟳  Check for updates", state="normal")
        if not error:
            self.settings.last_update_check = time.time()
            self.settings.save(SETTINGS_PATH)
        if error:
            if manual:
                messagebox.showwarning("Check for updates", error, parent=self)
            return
        if info is None:
            if manual:
                messagebox.showinfo(
                    "Check for updates", f"You have the newest version ({APP_VERSION}).", parent=self
                )
            return
        if not manual and info.version == self.settings.skipped_version:
            return
        self._update_info = info
        self._show_update_bar(info)
        if not manual:
            self.tray.notify(
                f"{APP_NAME} {info.version} is available",
                "Open Ghost and click Update now. Your macros and settings stay.",
            )

    def _show_update_bar(self, info: updater.UpdateInfo) -> None:
        size = f" · {info.size / 1e6:.1f} MB" if info.size else ""
        self.lbl_update.configure(text=f"✨  Version {info.version} is available{size}")
        self.btn_update.configure(text="Update now", state="normal")
        self.lbl_footer.grid_remove()
        self.update_bar.grid(row=0, column=0, sticky="w")

    def _hide_update_bar(self) -> None:
        self.update_bar.grid_remove()
        self.lbl_footer.grid()

    def _skip_update(self) -> None:
        if self._update_info and not self._updating:
            self.settings.skipped_version = self._update_info.version
            self.settings.save(SETTINGS_PATH)
            self._update_info = None
            self._hide_update_bar()

    def _open_update_page(self) -> None:
        import webbrowser

        webbrowser.open(self._update_info.page_url if self._update_info else updater.RELEASES_PAGE)

    def start_update(self) -> None:
        info = self._update_info
        if info is None or self._updating:
            return
        if self.recorder.is_recording or self.player.is_playing:
            messagebox.showinfo("Update", "Stop recording or playback first, then click Update now.", parent=self)
            return
        if not self._confirm_discard("update"):
            return
        self._updating = True
        self.btn_update.configure(state="disabled", text="Downloading…")
        self.btn_update_skip.configure(state="disabled")

        def progress(fraction: float) -> None:
            self.after(0, lambda: self.lbl_update.configure(
                text=f"⬇  Downloading version {info.version}… {int(fraction * 100)}%"))

        def work() -> None:
            try:
                path = updater.download(info, progress, should_stop=lambda: self._is_closing)
                self.after(0, lambda: self._install_update(path))
            except Exception as exc:
                msg = str(exc) if isinstance(exc, RuntimeError) else "The download failed. Check your connection."
                self.after(0, lambda: self._update_failed(msg))

        threading.Thread(target=work, daemon=True).start()

    def _install_update(self, path: Path) -> None:
        self.lbl_update.configure(text="Installing… Ghost will close and open again.")
        self.update_idletasks()
        try:
            updater.run_installer(path)
        except Exception as exc:
            self._update_failed(f"{exc} You can download it from the website instead.")
            return
        # The installer replaces the files; get out of its way. It reopens Ghost when done.
        self.after(250, self.quit_app)

    def _update_failed(self, message: str) -> None:
        self._updating = False
        self.btn_update.configure(state="normal", text="Try again")
        self.btn_update_skip.configure(state="normal")
        if self._update_info:
            self.lbl_update.configure(text=f"✨  Version {self._update_info.version} is available")
        messagebox.showwarning("Update", message, parent=self)

    # ------------------------------------------------------------------
    # Tray & Lifecycle
    # ------------------------------------------------------------------
    def show_from_tray(self) -> None:
        hidden = self.state() != "normal"
        self._revealed = True
        if hidden:
            try:
                self.attributes("-alpha", 0.0)
            except Exception:
                pass
        self.deiconify()
        self.after(20, lambda: self._fade(1.0, 180 if hidden else 1))
        self.state("normal")
        self.lift()
        self.focus_force()
        self._apply_icons()

    @staticmethod
    def _apply_theme_defaults() -> None:
        """Point CustomTkinter's built-in defaults at our palette.

        Some CTk widgets paint a pixel or two with their theme default (e.g. a 1px
        gray line at the end of segmented buttons). With the defaults set to our
        own colours, nothing foreign can show through.
        """
        theme = ctk.ThemeManager.theme
        seg = theme["CTkSegmentedButton"]
        seg["fg_color"] = list(C["seg"])
        seg["unselected_color"] = list(C["seg"])
        seg["unselected_hover_color"] = list(C["ghost_hover"])
        seg["selected_color"] = list(C["text"])
        seg["selected_hover_color"] = list(C["text"])
        seg["text_color"] = list(C["text"])
        theme["CTkFrame"]["border_color"] = list(C["line"])
        theme["CTkFrame"]["top_fg_color"] = list(C["panel"])
        theme["CTk"]["fg_color"] = list(C["bg"])
        theme["CTkToplevel"]["fg_color"] = list(C["bg"])
        theme["CTkScrollbar"]["button_color"] = list(C["scroll"])
        theme["CTkScrollbar"]["button_hover_color"] = list(C["accent"])

    def _fit_min_size(self) -> None:
        """Never let the window get so short that settings text is cut off.

        Measures how tall the tallest settings tab really needs to be, and sets the
        window's minimum height so that tab always fits (growing it now if needed).
        """
        try:
            self.update_idletasks()
            scale = self._get_window_scaling()
            pages = [self.tabs.tab(n) for n in self.tabs._name_list]  # noqa: SLF001
            need = max(p.winfo_reqheight() for p in pages)
            have = self.tabs.tab(self.tabs.get()).winfo_height()
            if have <= 1:
                self.after(300, self._fit_min_size)
                return
            # 1) Size the settings card to its tallest tab (no big empty area underneath)
            header = self.tabs.winfo_height() - have
            self.tabs.configure(height=int((header + need) / scale) + 14)
            self.update_idletasks()
            # 2) The window may not get shorter than what that card needs
            win_h = self.winfo_height() / scale
            slack = (self._right.winfo_height() - self.tabs.winfo_reqheight()) / scale
            min_h = int(win_h - slack + 4)
            self.minsize(self.MIN_W, min_h)
            if win_h < min_h:
                self.geometry(f"{int(self.winfo_width() / scale)}x{min_h}")
            self._place_summary()
        except Exception:
            pass
        self.after(30, self._reveal)

    # ------------------------------------------------------------------
    # Smooth window transitions
    # ------------------------------------------------------------------
    def _fade(self, target: float, ms: int = 160, then=None) -> None:
        """Animate the window's opacity to `target` (0..1) with an ease-out curve."""
        if self._fade_job:
            self.after_cancel(self._fade_job)
            self._fade_job = None
        try:
            start = float(self.attributes("-alpha"))
        except Exception:
            start = 1.0
        steps = max(1, ms // 12)

        def step(i: int = 1) -> None:
            t = i / steps
            eased = 1 - (1 - t) ** 3
            try:
                self.attributes("-alpha", start + (target - start) * eased)
            except Exception:
                pass
            if i < steps:
                self._fade_job = self.after(12, step, i + 1)
            else:
                self._fade_job = None
                if then:
                    then()

        step()

    def _on_root_configure(self, event) -> None:
        if event.widget is not self:
            return
        size = (event.width, event.height)
        old, self._last_size = self._last_size, size
        if not self._revealed or old == (0, 0) or size == old:
            return
        jump = abs(size[0] - old[0]) > 120 or abs(size[1] - old[1]) > 120
        if jump and not self._resize_cover.winfo_ismapped():
            # A big jump = maximize/restore/snap. Cover now, uncover once the layout settled.
            self._resize_cover.configure(bg=col("bg"))
            self._resize_cover.place(x=0, y=0, relwidth=1, relheight=1)
            self._resize_cover.lift()
        if self._resize_cover.winfo_ismapped() or jump:
            if self._resize_cover_job:
                self.after_cancel(self._resize_cover_job)
            self._resize_cover_job = self.after(140, self._uncover_after_resize)

    def _uncover_after_resize(self) -> None:
        self._resize_cover_job = None
        self.update_idletasks()  # finish every widget's redraw behind the cover
        self._resize_cover.place_forget()

    def _show_splash(self) -> None:
        """A small loading card that appears instantly while the main window is built."""
        try:
            bg, line, text, muted = col("panel"), col("line"), col("text"), col("muted")
            splash = tk.Toplevel(self)
            splash.overrideredirect(True)
            splash.configure(bg=bg, highlightthickness=1, highlightbackground=line)
            splash.attributes("-topmost", True)
            scale = self._get_window_scaling()
            w, h = int(340 * scale), int(210 * scale)
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2 - int(40 * scale)
            splash.geometry(f"{w}x{h}+{x}+{y}")
            logo = get_resource_path("assets/icon_ui.png")
            if not logo.exists():
                logo = get_resource_path("assets/icon.png")
            if logo.exists():
                from PIL import Image, ImageTk

                size = int(72 * scale)
                self._splash_img = ImageTk.PhotoImage(Image.open(logo).resize((size, size), Image.LANCZOS))
                tk.Label(splash, image=self._splash_img, bg=bg).pack(pady=(int(30 * scale), int(10 * scale)))
            tk.Label(splash, text=APP_NAME, bg=bg, fg=text, font=("Segoe UI Semibold", 14)).pack()
            tk.Label(splash, text="Loading…", bg=bg, fg=muted, font=("Segoe UI", 10)).pack(pady=(2, 0))
            try:  # Windows 11: rounded corners like a normal window
                hwnd = ctypes.windll.user32.GetParent(splash.winfo_id()) or splash.winfo_id()
                pref = ctypes.c_int(2)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
            except Exception:
                pass
            splash.update()
            self._splash = splash
        except Exception:
            self._splash = None

    def _close_splash(self) -> None:
        splash, self._splash = self._splash, None
        if splash is None:
            return

        def step(alpha: float = 1.0) -> None:
            alpha -= 0.2
            if alpha <= 0:
                try:
                    splash.destroy()
                except Exception:
                    pass
                return
            try:
                splash.attributes("-alpha", alpha)
            except Exception:
                pass
            self.after(16, step, alpha)

        step()

    def _reveal(self) -> None:
        """First appearance: fade in once everything is drawn at its final size."""
        if self._revealed or self._is_closing:
            return
        self._revealed = True
        if self._start_hidden:
            self.attributes("-alpha", 1.0)  # stays withdrawn in the tray
            return
        self.update_idletasks()
        self._fade(1.0, 220)
        self.after(120, self._close_splash)

    def _apply_icons(self) -> None:
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            apply_window_icons(hwnd)
        except Exception:
            pass

    def _on_window_close(self) -> None:
        if self.settings.close_to_tray:
            self.withdraw()
            return
        self.request_exit()

    def quit_app(self) -> None:
        self._is_closing = True
        if self._splash is not None:
            try:
                self._splash.destroy()
            except Exception:
                pass
            self._splash = None
        self.recorder.stop()
        self.player.stop()
        self.hotkeys.stop()
        self.tray.stop()
        try:
            self.quit()
            self.destroy()
        except Exception:
            pass
