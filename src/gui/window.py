"""Main window of Ghost Macro Recorder (Qt).

A studio "tape deck": round REC / PLAY / STOP keys, a timecode readout and a multi-lane
tape that shows every click, key, scroll and move. The engine (recorder, player, hotkeys,
models, updater) is shared with the rest of the app; this module is only the interface.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import threading
import time
from typing import Optional
import webbrowser
import winsound

from PySide6.QtCore import QObject, QPoint, QSize, Qt, QTimer, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSizePolicy, QSlider,
    QStackedWidget, QTableView, QVBoxLayout, QWidget,
)

from src import autostart, updater
from src.app_paths import APP_NAME, APP_TAGLINE, APP_VERSION, get_macros_dir, get_resource_path, get_settings_path, get_user_data_dir
from src.gui.theme import LANES, LANE_OF, Theme, stylesheet
from src.gui.tray import QtTray
from src.gui.widgets import (
    FadeStack, RoundKey, Segmented, StepsModel, TapeView, TargetField, TargetPopup, Toggle, _anim, _run,
)
from src.hotkeys import GlobalHotkeyManager, canonical_hotkey, display_hotkey
from src.models import AppSettings, Macro, MacroEvent, WindowTarget
from src.player import MacroPlayer
from src.recorder import MacroRecorder
from src.win32_backend import get_foreground_root_window, get_window_target, list_visible_windows

SETTINGS_PATH = get_settings_path()
MACROS_DIR = get_macros_dir()
user32 = ctypes.windll.user32


def fmt_timecode(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:06.3f}"


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


class Bridge(QObject):
    """Signals that carry work from background threads to the UI thread."""

    recorded = Signal(object)
    record_state = Signal(bool)
    play_progress = Signal(int, int, int, int)
    play_state = Signal(bool, str)
    show_requested = Signal()
    hotkey = Signal(str)
    update_result = Signal(object, str, bool)
    download_progress = Signal(float)
    download_done = Signal(object)
    download_failed = Signal(str)


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if wrap:
        lbl.setWordWrap(True)
    return lbl


def eyebrow(text: str) -> QLabel:
    return label(text.upper(), "eyebrow")


def card(name: str = "card") -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    return f


def ghost_button(text: str, fn, width: int = 0) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("ghost")
    b.setCursor(Qt.PointingHandCursor)
    if width:
        b.setFixedWidth(width)
    b.clicked.connect(fn)
    return b


def keycap(text: str = "") -> QLabel:
    k = QLabel(text)
    k.setObjectName("keycap")
    k.setFixedHeight(18)
    k.setAlignment(Qt.AlignCenter)
    k.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return k


class HotkeyField(QPushButton):
    """Click, then press the key (or combo) you want."""

    captured = Signal(object)  # the QKeyEvent

    def __init__(self, attr: str) -> None:
        super().__init__()
        self.attr = attr
        self.setObjectName("hotkey")
        self.setCursor(Qt.PointingHandCursor)
        self.capturing = False

    def show_key(self, key: str) -> None:
        self.capturing = False
        self.setProperty("waiting", False)
        self.setText(display_hotkey(key))
        self.style().unpolish(self)
        self.style().polish(self)

    def wait(self) -> None:
        self.capturing = True
        self.setProperty("waiting", True)
        self.setText("Press a key…")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setFocus()
        self.grabKeyboard()

    def release(self) -> None:
        self.releaseKeyboard()

    def keyPressEvent(self, e) -> None:
        if self.capturing:
            self.captured.emit(e)
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        if self.capturing:
            self.captured.emit(None)


class MainWindow(QMainWindow):
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
    COUNTDOWN = {"Off": 0, "3 s": 3, "5 s": 5}
    HUMANIZE = {"Off": 0, "Light": 5, "Strong": 15}
    ON_FINISH = {"Nothing": "none", "Notify": "notify", "Sound": "sound"}
    HOTKEY_LABELS = {"hotkey_record": "Record / stop", "hotkey_play": "Play / stop",
                     "hotkey_stop": "Stop everything", "hotkey_target": "Target current app"}
    HOTKEY_ATTRS = {"record": "hotkey_record", "play": "hotkey_play", "stop": "hotkey_stop", "target": "hotkey_target"}
    SUMMARY_ROWS = (("macro", "Macro"), ("steps", "Steps"), ("target", "Target"), ("engine", "Plays"), ("runs", "Runs"))

    def __init__(self, start_hidden: bool = False) -> None:
        super().__init__()
        self.settings = AppSettings.load(SETTINGS_PATH)
        self.own_pid = os.getpid()
        self.macro = Macro()
        self._dirty = False
        self._macro_file: Optional[Path] = None
        self._window_choices: list[WindowTarget] = []
        self._selected_target: Optional[WindowTarget] = None
        self._picking = 0
        self._is_closing = False
        self._live_events: list[MacroEvent] = []
        self._record_started_at: Optional[float] = None
        self._play_ev_idx = 0
        self._play_started_at: Optional[float] = None
        self._blink = False
        self._countdown_left = 0
        self._capture_field: Optional[HotkeyField] = None
        self._hotkey_results_seen = -1
        self._update_info: Optional[updater.UpdateInfo] = None
        self._updating = False
        self._run_summary = "—"

        self.bridge = Bridge()
        self.recorder = MacroRecorder(
            own_pid=self.own_pid,
            on_event=self.bridge.recorded.emit,
            on_state_change=self.bridge.record_state.emit,
        )
        self.player = MacroPlayer(
            on_progress=self.bridge.play_progress.emit,
            on_state_change=self.bridge.play_state.emit,
        )
        self.hotkeys = GlobalHotkeyManager(
            on_toggle_record=lambda: self.bridge.hotkey.emit("record"),
            on_toggle_play=lambda: self.bridge.hotkey.emit("play"),
            on_stop_all=lambda: self.bridge.hotkey.emit("stop"),
            on_set_target=lambda: self.bridge.hotkey.emit("target"),
        )
        b = self.bridge
        b.recorded.connect(self._append_row)
        b.record_state.connect(self._update_record_ui)
        b.play_progress.connect(self._update_play_progress)
        b.play_state.connect(self._update_play_ui)
        b.show_requested.connect(self.show_from_tray)
        b.hotkey.connect(self._on_hotkey)
        b.update_result.connect(self._on_update_result)
        b.download_progress.connect(lambda f: self.lbl_update.setText(
            f"⬇  Downloading version {self._update_info.version if self._update_info else ''}… {int(f * 100)}%"))
        b.download_done.connect(self._install_update)
        b.download_failed.connect(self._update_failed)

        self._apply_theme_mode(self.settings.appearance_mode, initial=True)
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        icon = QIcon(str(get_resource_path("assets/app.ico")))
        self.setWindowIcon(icon)
        self._build()
        self._load_settings_into_ui()

        self.popup = TargetPopup(self)
        self.popup.chosen.connect(self._on_target_chosen)
        self.tray = QtTray(self, self.show_from_tray, self.toggle_record, self.toggle_play, self.request_exit)

        screen = QApplication.primaryScreen().availableGeometry()
        w, h = min(1180, int(screen.width() * 0.92)), min(780, int(screen.height() * 0.88))
        self.resize(w, h)
        self.move(screen.x() + (screen.width() - w) // 2, screen.y() + (screen.height() - h) // 3)
        self.setMinimumSize(1000, 620)

        self.refresh_windows()
        self._rebuild_steps()
        self._set_status("Idle — ready to record", "info")
        self.hotkeys.set_hotkeys(self.settings.hotkey_record, self.settings.hotkey_play,
                                 self.settings.hotkey_stop, self.settings.hotkey_target)
        self.hotkeys.start()
        self.tray.start()

        self._cd_timer = QTimer(self)
        self._cd_timer.setInterval(1000)
        self._cd_timer.timeout.connect(self._countdown_tick)
        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self._tick)
        self.ticker.start(100)
        QTimer.singleShot(6000, self._auto_update_check)
        self._start_hidden = start_hidden

    # ================================================================== build
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 14, 20, 10)
        outer.setSpacing(12)
        outer.addLayout(self._build_header())
        outer.addWidget(self._build_deck())
        lower = QHBoxLayout()
        lower.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(self._build_target())
        left.addWidget(self._build_steps(), 1)
        lower.addLayout(left, 1)
        lower.addWidget(self._build_right())
        outer.addLayout(lower, 1)
        outer.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        logo = QLabel()
        src = get_resource_path("assets/icon_ui.png")
        if not src.exists():
            src = get_resource_path("assets/icon.png")
        pm = QPixmap(str(src))
        if not pm.isNull():
            dpr = self.devicePixelRatioF() or 1.0
            pm = pm.scaled(int(40 * dpr), int(40 * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            logo.setPixmap(pm)
        logo.setFixedSize(40, 40)
        row.addWidget(logo)
        words = QVBoxLayout()
        words.setSpacing(0)
        self.lbl_name = QLabel()
        self.lbl_name.setTextFormat(Qt.RichText)
        words.addWidget(self.lbl_name)
        words.addWidget(label(APP_TAGLINE, "muted"))
        row.addLayout(words)
        row.addStretch(1)

        pill = card("pill")
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(12, 4, 14, 4)
        pl.setSpacing(8)
        self.lbl_led = QLabel("●")
        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet("font-weight: 700; font-size: 12px;")
        pl.addWidget(self.lbl_led)
        pl.addWidget(self.lbl_status)
        row.addWidget(pill)
        row.addSpacing(8)
        for text, fn in (("＋ New", self.new_macro), ("Open", self.load_macro_dialog),
                         ("Save", self.save_macro_dialog), ("Clear", self.clear_macro)):
            row.addWidget(ghost_button(text, fn))
        self.btn_theme = ghost_button("", self._toggle_theme, 36)
        row.addWidget(self.btn_theme)
        row.addWidget(ghost_button("?", self.show_about_dialog, 36))
        return row

    def _paint_name(self) -> None:
        self.lbl_name.setText(
            f'<span style="font-family:\'{Theme.display}\'; font-size:20px; font-weight:700;">'
            f'Ghost Macro <span style="color:{Theme.c("accent")}">Recorder</span></span>'
            f'<span style="color:{Theme.c("muted")}; font-size:11px;">&nbsp;&nbsp;v{APP_VERSION}</span>'
        )
        self.btn_theme.setText("☀" if Theme.dark else "☾")

    def _build_deck(self) -> QFrame:
        deck = card()
        lay = QHBoxLayout(deck)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(18)

        def transport(colour, glyph, glyph_colour, caption, fn):
            col = QVBoxLayout()
            col.setSpacing(6)
            key = RoundKey(colour, glyph, glyph_colour)
            key.clicked.connect(fn)
            col.addWidget(key, 0, Qt.AlignHCenter)
            cap = QHBoxLayout()
            cap.setSpacing(4)
            cap.addStretch(1)
            word = label(caption, "muted")
            word.setStyleSheet("font-size: 10px; font-weight: 700;")
            cap.addWidget(word)
            kc = keycap()
            cap.addWidget(kc)
            cap.addStretch(1)
            col.addLayout(cap)
            lay.addLayout(col)
            return key, kc

        self.btn_record, self.cap_record = transport("rec", "rec", "accent_text", "REC", self.toggle_record)
        self.btn_play, self.cap_play = transport("play", "play", "play_text", "PLAY", self.toggle_play)
        self.btn_stop, self.cap_stop = transport("stop", "stop", "text", "STOP", self.stop_all)
        self.btn_record.glyph_colour = "accent_text"

        readout = card("well")
        rl = QVBoxLayout(readout)
        rl.setContentsMargins(16, 10, 16, 10)
        rl.setSpacing(0)
        rl.addWidget(eyebrow("timecode"))
        self.lbl_timecode = QLabel(fmt_timecode(0))
        self.lbl_timecode.setObjectName("timecode")
        self.lbl_timecode.setMinimumWidth(220)
        rl.addWidget(self.lbl_timecode)
        self.lbl_counts = QLabel("0 events · 0.00s")
        self.lbl_counts.setObjectName("mono")
        rl.addWidget(self.lbl_counts)
        lay.addWidget(readout, 0, Qt.AlignVCenter)

        tape_col = QVBoxLayout()
        tape_col.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(eyebrow("tape"))
        head.addStretch(1)
        self.lbl_tape_info = label("empty reel", "muted")
        self.lbl_tape_info.setStyleSheet("font-size: 10px;")
        head.addWidget(self.lbl_tape_info)
        tape_col.addLayout(head)
        self.tape = TapeView(self._tape_state)
        self.tape.setFixedHeight(104)
        tape_col.addWidget(self.tape)
        lay.addLayout(tape_col, 1)
        return deck

    def _build_target(self) -> QFrame:
        strip = card()
        g = QGridLayout(strip)
        g.setContentsMargins(20, 12, 16, 12)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(10)
        g.addWidget(eyebrow("target"), 0, 0)
        self.target_field = TargetField()
        self.target_field.clicked.connect(self._open_picker)
        g.addWidget(self.target_field, 0, 1)
        g.addWidget(ghost_button("↻", self.refresh_windows, 38), 0, 2)
        self.btn_pick = QPushButton("◎  Pick window")
        self.btn_pick.setObjectName("accent")
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        self.btn_pick.setFixedSize(136, 38)
        self.btn_pick.clicked.connect(self.start_pick_window)
        g.addWidget(self.btn_pick, 0, 3)
        self.seg_scope = Segmented(["This window only", "Every window"], height=36)
        self.seg_scope.setFixedWidth(270)
        self.seg_scope.changed.connect(self._on_settings_changed)
        g.addWidget(self.seg_scope, 1, 1, Qt.AlignLeft)
        self.lbl_target_hint = label("", "hint", wrap=True)
        g.addWidget(self.lbl_target_hint, 1, 1, 1, 3)
        g.setColumnStretch(1, 1)
        # the hint sits to the right of the scope switch
        self.lbl_target_hint.setContentsMargins(284, 0, 0, 0)
        return strip

    def _build_steps(self) -> QFrame:
        steps = card()
        lay = QVBoxLayout(steps)
        lay.setContentsMargins(18, 14, 14, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        title = label("Steps", "title")
        head.addWidget(title)
        hint = label("drag to select many · Del removes", "muted")
        hint.setStyleSheet("font-size: 10px; padding-top: 3px;")
        head.addWidget(hint)
        head.addStretch(1)
        self.legend = QLabel()
        head.addWidget(self.legend)
        head.addSpacing(8)
        head.addWidget(ghost_button("Trim moves", self.trim_mouse_moves))
        head.addWidget(ghost_button("Delete", self.delete_selected))
        lay.addLayout(head)

        self.model = StepsModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate((56, 86, 130, 220)):
            self.table.setColumnWidth(col, width)
        hh.setStretchLastSection(True)
        for seq in (QKeySequence.Delete, QKeySequence(Qt.Key_Backspace)):
            sc = QShortcut(seq, self.table)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(self.delete_selected)

        self.steps_stack = QStackedWidget()
        empty = label("Nothing on the reel yet.\nPress ● REC (or your hotkey) and use your target app.", "muted")
        empty.setAlignment(Qt.AlignCenter)
        empty.setStyleSheet("font-size: 13px;")
        self.steps_stack.addWidget(empty)
        self.steps_stack.addWidget(self.table)
        lay.addWidget(self.steps_stack, 1)
        return steps

    def _paint_legend(self) -> None:
        parts = [f'<span style="color:{Theme.lane(lane).name()}">■</span>'
                 f'<span style="color:{Theme.c("muted")}">&nbsp;{lbl.title()}&nbsp;&nbsp;</span>'
                 for lane, lbl, _c, _t in LANES]
        self.legend.setText('<span style="font-size:10px">' + "".join(parts) + "</span>")

    # ---------------------------------------------------------------- settings column
    def _build_right(self) -> QWidget:
        right = QWidget()
        right.setFixedWidth(392)
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        self.tabs_card = card()
        tl = QVBoxLayout(self.tabs_card)
        tl.setContentsMargins(14, 14, 14, 14)
        tl.setSpacing(10)
        self.tab_bar = Segmented(["Play", "Repeat", "Record", "Keys", "App"], height=32)
        tl.addWidget(self.tab_bar)
        self.pages = FadeStack()
        self.tab_bar.changed.connect(lambda v: self.pages.fade_to(self.tab_bar.values.index(v)))
        for build in (self._page_play, self._page_repeat, self._page_record, self._page_keys, self._page_app):
            page = QWidget()
            pl = QVBoxLayout(page)
            pl.setContentsMargins(2, 2, 2, 2)
            pl.setSpacing(4)
            build(pl)
            pl.addStretch(1)
            self.pages.addWidget(page)
        tl.addWidget(self.pages)
        col.addWidget(self.tabs_card)

        self.summary = card()
        sl = QGridLayout(self.summary)
        sl.setContentsMargins(18, 14, 18, 14)
        sl.setVerticalSpacing(6)
        sl.addWidget(eyebrow("this run"), 0, 0, 1, 2)
        self.summary_vals: dict[str, QLabel] = {}
        for i, (key, text) in enumerate(self.SUMMARY_ROWS, start=1):
            sl.addWidget(label(text, "hint"), i, 0, Qt.AlignTop)
            val = label("—", wrap=True)
            val.setStyleSheet("font-weight: 700; font-size: 12px;")
            sl.addWidget(val, i, 1)
            self.summary_vals[key] = val
        sl.setColumnStretch(1, 1)
        sl.setRowStretch(len(self.SUMMARY_ROWS) + 1, 1)
        col.addWidget(self.summary, 1)
        self.right = right
        return right

    def _setting(self, lay: QVBoxLayout, title: str, sub: str = "", top: int = 8) -> Optional[QLabel]:
        lay.addSpacing(top)
        lay.addWidget(label(title, "setting"))
        if sub:
            s = label(sub, "hint", wrap=True)
            s.setStyleSheet("font-size: 11px;")
            lay.addWidget(s)
            return s
        return None

    def _option(self, lay: QVBoxLayout, title: str, desc: str, on_toggle=None) -> Toggle:
        lay.addSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(12)
        sw = Toggle()
        sw.toggled.connect(on_toggle or (lambda _v: self._on_settings_changed()))
        row.addWidget(sw, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(title, "setting"))
        d = label(desc, "hint", wrap=True)
        d.setStyleSheet("font-size: 11px;")
        text.addWidget(d)
        row.addLayout(text, 1)
        lay.addLayout(row)
        return sw

    def _mini_box(self, title: str, widget: QWidget) -> QFrame:
        box = card("well")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(10, 7, 10, 8)
        bl.setSpacing(4)
        t = label(title, "muted")
        t.setStyleSheet("font-size: 10px; font-weight: 700;")
        bl.addWidget(t)
        bl.addWidget(widget)
        return box

    def _page_play(self, lay: QVBoxLayout) -> None:
        self._setting(lay, "How should it play?", top=2)
        self.seg_mode = Segmented(["Background", "Foreground"])
        self.seg_mode.changed.connect(self._on_settings_changed)
        lay.addWidget(self.seg_mode)
        self.lbl_engine_help = label("", "hint", wrap=True)
        self.lbl_engine_help.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.lbl_engine_help)
        lay.addSpacing(10)
        row = QHBoxLayout()
        row.addWidget(label("Speed", "setting"))
        row.addStretch(1)
        self.lbl_speed = QLabel("1.00×")
        self.lbl_speed.setObjectName("speed")
        row.addWidget(self.lbl_speed)
        lay.addLayout(row)
        self.slider_speed = QSlider(Qt.Horizontal)
        self.slider_speed.setRange(1, 20)  # x 0.25
        self.slider_speed.valueChanged.connect(self._on_speed)
        self.slider_speed.sliderReleased.connect(self._on_settings_changed)
        lay.addWidget(self.slider_speed)
        ticks = QHBoxLayout()
        a, b = label("0.25× slower", "muted"), label("faster 5×", "muted")
        for t in (a, b):
            t.setStyleSheet("font-size: 10px;")
        ticks.addWidget(a)
        ticks.addStretch(1)
        ticks.addWidget(b)
        lay.addLayout(ticks)
        lay.addSpacing(8)
        extras = QHBoxLayout()
        extras.setSpacing(10)
        self.seg_countdown = Segmented(list(self.COUNTDOWN), height=28, font_px=11)
        self.seg_humanize = Segmented(list(self.HUMANIZE), height=28, font_px=11)
        for s in (self.seg_countdown, self.seg_humanize):
            s.setMinimumWidth(120)
            s.changed.connect(self._on_settings_changed)
        extras.addWidget(self._mini_box("COUNTDOWN · time to switch apps", self.seg_countdown))
        extras.addWidget(self._mini_box("HUMANIZE · natural timing", self.seg_humanize))
        lay.addLayout(extras)

    def _page_repeat(self, lay: QVBoxLayout) -> None:
        self._setting(lay, "When should it stop?", top=2)
        self.seg_limit = Segmented(["Repeat count", "Run for time"])
        self.seg_limit.changed.connect(self._on_settings_changed)
        lay.addWidget(self.seg_limit)
        self.lbl_limit_help = label("", "hint", wrap=True)
        self.lbl_limit_help.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.lbl_limit_help)
        lay.addSpacing(10)
        boxes = QHBoxLayout()
        boxes.setSpacing(10)

        def field(title: str, hint: str) -> tuple[QFrame, QLineEdit]:
            box = card("well")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 8, 10, 6)
            bl.setSpacing(0)
            t = label(title, "muted")
            t.setStyleSheet("font-size: 10px; font-weight: 700;")
            bl.addWidget(t)
            entry = QLineEdit()
            entry.setObjectName("big")
            entry.editingFinished.connect(self._on_settings_changed)
            bl.addWidget(entry)
            h = label(hint, "hint")
            h.setStyleSheet("font-size: 10px;")
            bl.addWidget(h)
            return box, entry

        self.box_repeat, self.entry_repeat = field("TIMES", "0 = forever")
        self.box_duration, self.entry_duration = field("RUN FOR", "1:00 · 90s · 5m · 1h")
        self.box_delay, self.entry_delay = field("WAIT BETWEEN (s)", "pause after each run")
        self.limit_stack = QStackedWidget()
        self.limit_stack.addWidget(self.box_repeat)
        self.limit_stack.addWidget(self.box_duration)
        boxes.addWidget(self.limit_stack, 1)
        boxes.addWidget(self.box_delay, 1)
        lay.addLayout(boxes)
        self.lbl_estimate = label("", wrap=True)
        self.lbl_estimate.setObjectName("estimate")
        lay.addSpacing(4)
        lay.addWidget(self.lbl_estimate)
        lay.addSpacing(8)
        row = QHBoxLayout()
        row.addWidget(label("When it's done", "setting"))
        row.addSpacing(10)
        self.seg_finish = Segmented(list(self.ON_FINISH), height=28, font_px=11)
        self.seg_finish.changed.connect(self._on_settings_changed)
        row.addWidget(self.seg_finish, 1)
        lay.addLayout(row)

    def _page_record(self, lay: QVBoxLayout) -> None:
        self.sw_moves = self._option(lay, "Record mouse movement",
                                     "Also save the path your mouse travels, not just clicks. Needed for hover menus "
                                     "and drawing — makes macros much longer.")
        self.sw_scale = self._option(lay, "Adjust if the window is resized",
                                     "If the target window is bigger or smaller than when you recorded, clicks land "
                                     "on the same spot relative to its size.")
        self.sw_min_rec = self._option(lay, "Hide this app while recording",
                                       "Minimises Ghost so it's out of the way. Use your Record hotkey to stop.")
        self.sw_min_play = self._option(lay, "Hide this app while playing",
                                        "Minimises Ghost during playback and brings it back when it finishes.")

    def _page_keys(self, lay: QVBoxLayout) -> None:
        self._setting(lay, "Keyboard shortcuts", "Work even when Ghost is hidden. Click a box, press a key.", top=2)
        lay.addSpacing(6)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self.hotkey_fields: dict[str, HotkeyField] = {}
        self.hotkey_status: dict[str, QPushButton] = {}
        rows = [("record", "rec", "Record / stop"), ("play", "play", "Play / stop"),
                ("stop", "muted", "Stop everything"), ("target", "accent", "Target current app")]
        for r, (action, dot, text) in enumerate(rows):
            d = QLabel("●")
            d.setProperty("dot", dot)
            grid.addWidget(d, r * 2, 0)
            grid.addWidget(label(text), r * 2, 1)
            field = HotkeyField(self.HOTKEY_ATTRS[action])
            field.clicked.connect(lambda _c=False, f=field: self._start_capture(f))
            field.captured.connect(lambda e, f=field: self._on_capture(f, e))
            grid.addWidget(field, r * 2, 2)
            self.hotkey_fields[action] = field
            status = QPushButton("")
            status.setObjectName("link")
            status.setFlat(True)
            grid.addWidget(status, r * 2 + 1, 1, 1, 2, Qt.AlignRight)
            self.hotkey_status[action] = status
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self.lbl_hotkey_msg = label("", "warn", wrap=True)
        self.lbl_hotkey_msg.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.lbl_hotkey_msg)
        self._key_dots = [grid.itemAtPosition(r * 2, 0).widget() for r in range(4)]

    def _page_app(self, lay: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.addWidget(label("Theme", "setting"))
        row.addSpacing(14)
        self.seg_theme = Segmented(["Light", "Dark", "System"])
        self.seg_theme.changed.connect(self._on_theme_changed)
        row.addWidget(self.seg_theme, 1)
        lay.addSpacing(2)
        lay.addLayout(row)
        self.sw_tray = self._option(lay, "Keep running in the tray when closed",
                                    "✕ hides Ghost by the clock; tray ghost → Exit quits.")
        self.sw_autostart = self._option(lay, "Start with Windows", "Opens quietly in the tray when you sign in.",
                                         on_toggle=lambda _v: self._on_autostart_toggled())
        self.sw_on_top = self._option(lay, "Always on top", "Keep Ghost above other windows.")
        self.sw_updates = self._option(lay, "Tell me when a new version is out",
                                       "Checks GitHub each time Ghost opens. Nothing about you is sent.")
        lay.addSpacing(12)
        buttons = QHBoxLayout()
        buttons.addWidget(ghost_button("📂  Open macros folder", self.open_macros_folder))
        self.btn_check = ghost_button("⟳  Check for updates", lambda: self.check_for_updates(manual=True))
        buttons.addWidget(self.btn_check)
        buttons.addStretch(1)
        lay.addLayout(buttons)

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_footer = label("Elevated targets need this app run as Administrator. "
                                "Chromium/UWP apps may need Foreground mode.", "muted")
        self.lbl_footer.setStyleSheet("font-size: 10px;")
        row.addWidget(self.lbl_footer)
        self.update_bar = card("updatebar")
        ul = QHBoxLayout(self.update_bar)
        ul.setContentsMargins(12, 4, 6, 4)
        ul.setSpacing(6)
        self.lbl_update = QLabel()
        self.lbl_update.setStyleSheet("font-weight: 700; font-size: 12px;")
        ul.addWidget(self.lbl_update)
        self.btn_update = QPushButton("Update now")
        self.btn_update.setObjectName("accent")
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.clicked.connect(self.start_update)
        ul.addWidget(self.btn_update)
        ul.addWidget(ghost_button("What's new", self._open_update_page))
        self.btn_skip = ghost_button("Skip", self._skip_update)
        ul.addWidget(self.btn_skip)
        self.update_bar.hide()
        row.addWidget(self.update_bar)
        row.addStretch(1)
        self.footer_caps: list[tuple[QLabel, str]] = []
        for attr, word in (("hotkey_record", "rec"), ("hotkey_play", "play"), ("hotkey_stop", "panic")):
            kc = keycap()
            row.addWidget(kc)
            w = label(word, "muted")
            w.setStyleSheet("font-size: 10px;")
            row.addWidget(w)
            row.addSpacing(6)
            self.footer_caps.append((kc, attr))
        return row

    # ================================================================== settings <-> UI
    def _load_settings_into_ui(self) -> None:
        s = self.settings
        self.seg_scope.set_value("This window only" if s.record_scope == "target" else "Every window", animate=False)
        self.seg_mode.set_value("Background" if s.playback_mode == "background" else "Foreground", animate=False)
        self.slider_speed.blockSignals(True)
        self.slider_speed.setValue(max(1, min(20, round(s.speed / 0.25))))
        self.slider_speed.blockSignals(False)
        self.lbl_speed.setText(f"{s.speed:.2f}×")
        rev = {v: k for k, v in self.COUNTDOWN.items()}
        self.seg_countdown.set_value(rev.get(s.start_delay, "Off"), animate=False)
        rev = {v: k for k, v in self.HUMANIZE.items()}
        self.seg_humanize.set_value(rev.get(s.humanize_pct, "Off"), animate=False)
        self.seg_limit.set_value("Run for time" if s.run_limit_mode == "time" else "Repeat count", animate=False)
        self.entry_repeat.setText(str(s.repeat_count))
        self.entry_duration.setText(fmt_duration(s.run_duration))
        self.entry_delay.setText(f"{s.loop_delay:g}")
        rev = {v: k for k, v in self.ON_FINISH.items()}
        self.seg_finish.set_value(rev.get(s.on_finish, "Nothing"), animate=False)
        self.sw_moves.set_quietly(s.record_mouse_moves)
        self.sw_scale.set_quietly(s.scale_coordinates)
        self.sw_min_rec.set_quietly(s.minimize_on_record)
        self.sw_min_play.set_quietly(s.minimize_on_play)
        self.sw_tray.set_quietly(s.close_to_tray)
        self.sw_autostart.set_quietly(autostart.is_enabled())
        self.sw_on_top.set_quietly(s.always_on_top)
        self.sw_updates.set_quietly(s.check_updates)
        mode = s.appearance_mode.title()
        self.seg_theme.set_value(mode if mode in ("Light", "Dark", "System") else "Dark", animate=False)
        for f in self.hotkey_fields.values():
            f.show_key(getattr(s, f.attr))
        self._apply_helps()
        self._refresh_labels()
        self._paint_name()
        self._paint_legend()
        self._paint_dots()

    def _apply_helps(self) -> None:
        self.lbl_engine_help.setText(self.ENGINE_HELP[self.seg_mode.value()])
        self.lbl_limit_help.setText(self.LIMIT_HELP[self.seg_limit.value()])
        self.limit_stack.setCurrentIndex(1 if self.seg_limit.value() == "Run for time" else 0)
        self._update_target_hint()
        self._update_estimate()

    def _on_speed(self, value: int) -> None:
        self.settings.speed = round(value * 0.25, 2)
        self.lbl_speed.setText(f"{self.settings.speed:.2f}×")
        if not self.slider_speed.isSliderDown():
            self._on_settings_changed()
        else:
            self._update_estimate()

    def _on_settings_changed(self, *_a) -> None:
        s = self.settings
        s.playback_mode = "background" if self.seg_mode.value() == "Background" else "foreground"
        s.record_scope = "target" if self.seg_scope.value() == "This window only" else "all"
        s.speed = round(self.slider_speed.value() * 0.25, 2)
        s.record_mouse_moves = self.sw_moves.isChecked()
        s.scale_coordinates = self.sw_scale.isChecked()
        s.minimize_on_record = self.sw_min_rec.isChecked()
        s.minimize_on_play = self.sw_min_play.isChecked()
        s.close_to_tray = self.sw_tray.isChecked()
        s.start_delay = self.COUNTDOWN.get(self.seg_countdown.value(), 0)
        s.humanize_pct = self.HUMANIZE.get(self.seg_humanize.value(), 0)
        s.on_finish = self.ON_FINISH.get(self.seg_finish.value(), "none")
        if s.always_on_top != self.sw_on_top.isChecked():
            s.always_on_top = self.sw_on_top.isChecked()
            self._apply_on_top()
        s.check_updates = self.sw_updates.isChecked()
        try:
            s.repeat_count = max(0, int(self.entry_repeat.text().strip()))
        except ValueError:
            s.repeat_count = 1
        self.entry_repeat.setText(str(s.repeat_count))
        try:
            s.loop_delay = max(0.0, float(self.entry_delay.text().strip()))
        except ValueError:
            s.loop_delay = 0.25
        self.entry_delay.setText(f"{s.loop_delay:g}")
        s.run_limit_mode = "time" if self.seg_limit.value() == "Run for time" else "count"
        duration = parse_duration(self.entry_duration.text())
        s.run_duration = min(max(duration if duration is not None else s.run_duration, 1.0), 24 * 3600.0)
        self.entry_duration.setText(fmt_duration(s.run_duration))
        self.hotkeys.set_hotkeys(s.hotkey_record, s.hotkey_play, s.hotkey_stop, s.hotkey_target)
        self._apply_helps()
        self._refresh_labels()
        s.save(SETTINGS_PATH)

    def _refresh_labels(self) -> None:
        self.btn_record.set_glyph("stop" if self.recorder.is_recording else "rec")
        self.btn_play.set_glyph("stop" if self.player.is_playing else "play")
        self.cap_record.setText(display_hotkey(self.settings.hotkey_record))
        self.cap_play.setText(display_hotkey(self.settings.hotkey_play))
        self.cap_stop.setText(display_hotkey(self.settings.hotkey_stop))
        for kc, attr in self.footer_caps:
            kc.setText(display_hotkey(getattr(self.settings, attr)))

    def _update_target_hint(self) -> None:
        t = self._selected_target
        scope_target = self.seg_scope.value() == "This window only"
        if t is None:
            msg = ("Choose the app you want to automate, or press Pick window and click on it." if scope_target
                   else "Recording every app you click. Each step remembers which window it happened in.")
        elif scope_target:
            msg = f"Only clicks and keys inside {t.process_name} are recorded — use other apps freely while it runs."
        else:
            msg = f"Playback goes to {t.process_name}. While recording, clicks in every window are captured."
        self.lbl_target_hint.setText(msg)
        self._update_summary()

    def _update_summary(self) -> None:
        if not hasattr(self, "summary_vals"):
            return
        v = self.summary_vals
        events = self.macro.events
        name = self._macro_file.stem if self._macro_file else ("Untitled (not saved)" if events else "Nothing recorded yet")
        if events and self._dirty and self._macro_file:
            name += "  •  unsaved changes"
        v["macro"].setText(name)
        v["steps"].setText(f"{len(events):,} steps · {fmt_duration(self.macro.duration)} long" if events else "—")
        t = self._selected_target
        v["target"].setText(t.process_name if t else "Any app you click")
        mode = "In the background" if self.settings.playback_mode == "background" else "With your real mouse & keys"
        v["engine"].setText(f"{mode} · {self.settings.speed:g}× speed")
        v["runs"].setText(self._run_summary)

    def _update_estimate(self) -> None:
        s = self.settings
        events = self.macro.events
        if s.run_limit_mode == "time":
            self._run_summary = f"Keeps repeating for {fmt_duration(s.run_duration)}"
        elif s.repeat_count == 0:
            self._run_summary = "Repeats until you press Stop"
        else:
            self._run_summary = f"{s.repeat_count} time{'s' if s.repeat_count != 1 else ''}"
        if events and s.run_limit_mode == "count" and s.repeat_count:
            n = s.repeat_count
            total = n * self.macro.duration / max(0.05, s.speed) + (n - 1) * s.loop_delay
            self._run_summary += f" · about {fmt_duration(total)}"
        self._update_summary()
        if not events:
            self.lbl_estimate.setText("Record a macro to see a run estimate.")
            return
        speed = max(0.05, s.speed)
        gap = s.loop_delay
        loop_len = self.macro.duration / speed
        steps = len(events)
        if s.run_limit_mode == "time":
            total = s.run_duration
            cycle = loop_len + gap
            if cycle <= 0:
                self.lbl_estimate.setText(f"Loops continuously for {fmt_duration(total)}")
                return
            full = int(total // cycle)
            if full == 0 and total >= loop_len:
                full = 1
            remainder = max(0.0, total - full * cycle)
            t0 = events[0].timestamp
            partial = sum(1 for ev in events if (ev.timestamp - t0) / speed < remainder)
            partial = partial if partial < steps else 0
            loops = f"{full} full loop{'s' if full != 1 else ''}" + (f" + {partial} steps" if partial else "")
            self.lbl_estimate.setText(f"≈ {loops}\n≈ {full * steps + partial:,} steps in {fmt_duration(total)}")
        else:
            n = s.repeat_count
            if n == 0:
                self.lbl_estimate.setText(f"∞ loops · {steps} steps each\nRuns until you press stop")
            else:
                total = n * loop_len + (n - 1) * gap
                self.lbl_estimate.setText(f"{n} loop{'s' if n != 1 else ''} · {n * steps:,} steps\n≈ {fmt_duration(total)} total")

    # ================================================================== theme
    def _system_is_dark(self) -> bool:
        try:
            return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except Exception:
            return True

    def _apply_theme_mode(self, mode: str, initial: bool = False) -> None:
        self.settings.appearance_mode = mode
        dark = self._system_is_dark() if mode == "System" else mode == "Dark"
        if not initial and dark == Theme.dark:
            return
        overlay = None
        if not initial and self.isVisible():
            # Cross-fade: freeze a picture of the window, restyle under it, fade the picture out.
            shot = self.centralWidget().grab()
            overlay = QLabel(self.centralWidget())
            overlay.setPixmap(shot)
            overlay.setGeometry(self.centralWidget().rect())
            overlay.show()
            overlay.raise_()
        Theme.dark = dark
        QApplication.instance().setStyleSheet(stylesheet())
        self._dark_title_bar()
        if not initial:
            self._paint_name()
            self._paint_legend()
            self._paint_dots()
            self._set_status(self.lbl_status.text(), self._tone)
            self.model.refresh_colours()
            self._on_hotkeys_registered(dict(self.hotkeys.last_results))
            for w in self.findChildren(QWidget):
                QWidget.update(w)
        if overlay is not None:
            effect = QGraphicsOpacityEffect(overlay)
            overlay.setGraphicsEffect(effect)
            anim = _anim(overlay, 260, effect.setOpacity)
            anim.finished.connect(overlay.deleteLater)
            _run(anim, 1.0, 0.0)

    def _on_theme_changed(self, value: str) -> None:
        self._apply_theme_mode(value)
        self.settings.save(SETTINGS_PATH)

    def _toggle_theme(self) -> None:
        value = "Light" if Theme.dark else "Dark"
        self.seg_theme.set_value(value)
        self._on_theme_changed(value)

    def _paint_dots(self) -> None:
        for d in getattr(self, "_key_dots", []):
            d.setStyleSheet(f"color: {Theme.c(d.property('dot'))}; font-size: 11px;")

    def _hwnd(self) -> int:
        return int(self.winId())

    def _dark_title_bar(self) -> None:
        try:
            on = ctypes.c_int(1 if Theme.dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(self._hwnd(), 20, ctypes.byref(on), ctypes.sizeof(on))
        except Exception:
            pass

    def _apply_on_top(self) -> None:
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
        try:
            user32.SetWindowPos(self._hwnd(), HWND_TOPMOST if self.settings.always_on_top else HWND_NOTOPMOST,
                                0, 0, 0, 0, flags)
        except Exception:
            pass

    # ================================================================== status & tape
    _tone = "info"

    def _set_status(self, text: str, tone: str = "info") -> None:
        colour = {"info": "info", "ok": "play", "rec": "rec", "warn": "warn", "accent": "accent"}.get(tone, "info")
        self._tone = tone
        self.lbl_led.setStyleSheet(f"color: {Theme.c(colour)}; font-size: 14px;")
        self.lbl_status.setText(text)

    def _set_timecode(self, text: str, colour: str = "accent") -> None:
        self.lbl_timecode.setText(text)
        self.lbl_timecode.setStyleSheet(f"color: {Theme.c(colour)};")

    def _tape_state(self) -> dict:
        recording = self.recorder.is_recording
        return {
            "events": self._live_events if recording else self.macro.events,
            "recording": recording,
            "record_started": self._record_started_at,
            "playing": self.player.is_playing,
            "play_idx": self._play_ev_idx,
        }

    def _update_tape_info(self) -> None:
        events = self._tape_state()["events"]
        if not events:
            self.lbl_tape_info.setText("empty reel")
            return
        counts = {lane: 0 for lane, *_r in LANES}
        for ev in events:
            lane = LANE_OF.get(ev.event_type)
            if lane:
                counts[lane] += 1
        self.lbl_tape_info.setText(f"{counts['click']} clicks · {counts['key']} keys · "
                                   f"{counts['scroll']} scrolls · {counts['move']} moves")

    def _tick(self) -> None:
        if self._is_closing:
            return
        if self.settings.appearance_mode == "System" and self._system_is_dark() != Theme.dark:
            self._apply_theme_mode("System")
        if self.hotkeys.results_version != self._hotkey_results_seen:
            self._hotkey_results_seen = self.hotkeys.results_version
            self._on_hotkeys_registered(dict(self.hotkeys.last_results))
        if self.recorder.is_recording and self._record_started_at is not None:
            self._set_timecode(fmt_timecode(time.perf_counter() - self._record_started_at), "rec")
            blink = int(time.perf_counter() * 2) % 2 == 0
            if blink != self._blink:
                self._blink = blink
                self.lbl_led.setStyleSheet(f"color: {Theme.c('rec' if blink else 'line')}; font-size: 14px;")
            self.tape.update()

    # ================================================================== window picking
    def refresh_windows(self) -> None:
        self._window_choices = list_visible_windows(exclude_pid=self.own_pid)
        if self._selected_target is not None:
            match = next((w for w in self._window_choices if w.hwnd == self._selected_target.hwnd), None)
            if match:
                self._selected_target = match
            else:
                self._window_choices.insert(0, self._selected_target)
        self.target_field.set_target(self._selected_target)

    def _open_picker(self) -> None:
        if self.popup.isVisible():
            self.popup.hide()
            return
        self.refresh_windows()
        self.popup.open_below(self.target_field, self._window_choices, self._selected_target)

    def _on_target_chosen(self, target: Optional[WindowTarget]) -> None:
        self._selected_target = target
        self.target_field.set_target(target)
        self._update_target_hint()
        if target is not None:
            self._set_status(f"Target: {target.process_name}", "ok")

    def start_pick_window(self) -> None:
        if self._picking:
            return
        self._picking = 3
        self.btn_pick.setEnabled(False)
        self._pick_tick()

    def _pick_tick(self) -> None:
        if self._picking > 0:
            self._set_status(f"Switch to your target window… {self._picking}", "accent")
            self.btn_pick.setText(f"◎  {self._picking}…")
            self._picking -= 1
            QTimer.singleShot(1000, self._pick_tick)
            return
        hwnd = get_foreground_root_window()
        self._finish_pick(get_window_target(hwnd) if hwnd else None)

    def _finish_pick(self, target: Optional[WindowTarget]) -> None:
        self._picking = 0
        self.btn_pick.setEnabled(True)
        self.btn_pick.setText("◎  Pick window")
        self.refresh_windows()
        if target and target.pid != self.own_pid:
            if not any(w.hwnd == target.hwnd for w in self._window_choices):
                self._window_choices.insert(0, target)
            self._on_target_chosen(target)
            self._set_status(f"Target locked: {target.process_name}", "ok")
        else:
            self._set_status("Picked this app — switch to another window next time", "warn")

    def set_target_to_current_window(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            return
        hwnd = get_foreground_root_window()
        target = get_window_target(hwnd) if hwnd else None
        if target is None or target.pid == self.own_pid:
            self._set_status("Switch to the app you want, then press the hotkey", "warn")
            return
        self._finish_pick(target)

    # ================================================================== hotkeys
    def _on_hotkey(self, action: str) -> None:
        {"record": self.toggle_record, "play": self.toggle_play, "stop": self.stop_all,
         "target": self.set_target_to_current_window}[action]()

    def _start_capture(self, field: HotkeyField) -> None:
        if self._capture_field is not None and self._capture_field is not field:
            self._end_capture()
        self._capture_field = field
        self.lbl_hotkey_msg.setText("")
        self.hotkeys.set_suspended(True)
        field.wait()

    def _end_capture(self) -> None:
        field, self._capture_field = self._capture_field, None
        if field is not None:
            field.release()
            field.show_key(getattr(self.settings, field.attr))
        self.hotkeys.set_suspended(False)

    NAMED_KEYS = {
        Qt.Key_Space: "SPACE", Qt.Key_PageUp: "PAGEUP", Qt.Key_PageDown: "PAGEDOWN", Qt.Key_Insert: "INSERT",
        Qt.Key_Delete: "DELETE", Qt.Key_Home: "HOME", Qt.Key_End: "END", Qt.Key_Pause: "PAUSE",
        Qt.Key_ScrollLock: "SCROLLLOCK",
    }
    MODIFIER_KEYS = {Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_CapsLock, Qt.Key_NumLock,
                     Qt.Key_AltGr, Qt.Key_Menu}

    def _on_capture(self, field: HotkeyField, e) -> None:
        if self._capture_field is not field:
            return
        if e is None:  # clicked elsewhere
            self._end_capture()
            return
        k = e.key()
        if k in self.MODIFIER_KEYS:
            return
        if k == Qt.Key_Escape:
            self._end_capture()
            return
        if Qt.Key_F1 <= k <= Qt.Key_F24:
            key = f"F{k - Qt.Key_F1 + 1}"
        elif Qt.Key_A <= k <= Qt.Key_Z or Qt.Key_0 <= k <= Qt.Key_9:
            key = chr(k)
        elif k in self.NAMED_KEYS:
            key = self.NAMED_KEYS[k]
        else:
            self.lbl_hotkey_msg.setText(f"“{e.text() or 'That key'}” can't be used. Try an F-key or a Ctrl/Alt combo.")
            return
        mods = e.modifiers()
        parts = []
        if mods & Qt.ControlModifier:
            parts.append("CTRL")
        if mods & Qt.AltModifier:
            parts.append("ALT")
        if mods & Qt.ShiftModifier:
            parts.append("SHIFT")
        combo = canonical_hotkey("+".join(parts + [key]))
        if (len(key) == 1 or key == "SPACE") and not ({"CTRL", "ALT"} & set(parts)):
            self.lbl_hotkey_msg.setText("Letters, numbers and Space need Ctrl or Alt with them — otherwise you couldn't type them.")
            return
        for attr, text in self.HOTKEY_LABELS.items():
            if attr != field.attr and canonical_hotkey(getattr(self.settings, attr)) == combo:
                self.lbl_hotkey_msg.setText(f"{display_hotkey(combo)} is already used for {text}.")
                return
        setattr(self.settings, field.attr, combo)
        self._end_capture()
        self._on_settings_changed()

    def _on_hotkeys_registered(self, results: dict[str, bool]) -> None:
        failed = False
        for action, ok in results.items():
            btn = self.hotkey_status.get(action)
            if btn is None:
                continue
            if btn.property("wired"):
                btn.clicked.disconnect()
                btn.setProperty("wired", False)
            if ok:
                btn.setText("✓ active")
                btn.setStyleSheet(f"color: {Theme.c('play')};")
                btn.setCursor(Qt.ArrowCursor)
            else:
                failed = True
                fix = self.hotkeys.last_suggestions.get(action, "")
                btn.setStyleSheet(f"color: {Theme.c('warn')};")
                if fix:
                    btn.setText(f"⚠ taken by another app — click to use {display_hotkey(fix)}")
                    btn.setCursor(Qt.PointingHandCursor)
                    btn.clicked.connect(lambda _c=False, a=action, k=fix: self._use_hotkey(a, k))
                    btn.setProperty("wired", True)
                else:
                    btn.setText("⚠ taken by another app — pick a different key")
        if failed and self._capture_field is None:
            self._set_status("A hotkey couldn't be set — see Settings › Keys", "warn")

    def _use_hotkey(self, action: str, key: str) -> None:
        attr = self.HOTKEY_ATTRS[action]
        setattr(self.settings, attr, key)
        self.hotkey_fields[action].show_key(key)
        self._on_settings_changed()
        self._set_status(f"{self.HOTKEY_LABELS[attr]} is now {display_hotkey(key)}", "ok")

    # ================================================================== app settings actions
    def _on_autostart_toggled(self) -> None:
        want = self.sw_autostart.isChecked()
        try:
            autostart.set_enabled(want)
            self._set_status("Ghost will start with Windows" if want else "Ghost won't start with Windows", "ok")
        except PermissionError:
            self.sw_autostart.set_quietly(autostart.is_enabled())
            self._set_status("Windows security blocked the startup setting", "warn")
            if QMessageBox.question(
                self, "Start with Windows",
                "Windows security on this PC blocked Ghost from adding itself to startup.\n\n"
                "You can still do it yourself: put a shortcut to Ghost Macro Recorder in your Startup folder.\n\n"
                "Open the Startup folder now?",
            ) == QMessageBox.Yes:
                os.startfile(autostart.startup_folder())  # noqa: S606
        except OSError as exc:
            self.sw_autostart.set_quietly(autostart.is_enabled())
            self._set_status(f"Couldn't change startup setting: {exc}", "warn")

    def open_macros_folder(self) -> None:
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(MACROS_DIR)  # noqa: S606

    # ================================================================== record & play
    def toggle_record(self) -> None:
        if self.player.is_playing:
            return
        self._cancel_countdown()
        if self.recorder.is_recording:
            events = self.recorder.stop()
            self.macro.events = events
            self.macro.default_target = self._selected_target
            self._live_events = []
            self._record_started_at = None
            self._macro_file = None
            self._set_dirty(bool(events))
            self._rebuild_steps()
            if self.settings.minimize_on_record:
                self.show_from_tray()
            return
        if not self._confirm_discard("start a new recording"):
            return
        self._on_settings_changed()
        if self.settings.record_scope == "target" and self._selected_target is None:
            self._set_status("Choose a target window first (or switch to Every window)", "warn")
            return
        self.macro = Macro(default_target=self._selected_target)
        self._live_events = []
        self.model.set_events([])
        self.steps_stack.setCurrentIndex(0)
        ignored = {self.settings.hotkey_record, self.settings.hotkey_play, self.settings.hotkey_stop,
                   self.settings.hotkey_target}
        if self.settings.minimize_on_record:
            self.showMinimized()
        try:
            self._record_started_at = time.perf_counter()
            self.recorder.start(target_window=self._selected_target, scope=self.settings.record_scope,
                                record_mouse_moves=self.settings.record_mouse_moves, ignored_hotkeys=ignored)
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
        if self._cd_timer.isActive():
            self._cancel_countdown()
            self._set_status("Playback cancelled", "info")
            return
        if not self.macro.events:
            self._set_status("Record or open a macro first", "warn")
            return
        self._on_settings_changed()
        if self.settings.minimize_on_play:
            self.showMinimized()
        if self.settings.start_delay > 0:
            self._countdown_left = int(self.settings.start_delay)
            self._countdown_tick()
            self._cd_timer.start()
            return
        self._start_playback()

    def _countdown_tick(self) -> None:
        if self._countdown_left <= 0:
            self._cd_timer.stop()
            self._start_playback()
            return
        self._set_status(f"Playing in {self._countdown_left}…  (press Play again to cancel)", "accent")
        self._set_timecode(f"-{self._countdown_left:02d}.000", "play")
        self._countdown_left -= 1

    def _cancel_countdown(self) -> None:
        if self._cd_timer.isActive():
            self._cd_timer.stop()
            self._countdown_left = 0
            self._set_timecode(fmt_timecode(self.macro.duration))

    def _start_playback(self) -> None:
        self._play_ev_idx = 0
        self._play_started_at = time.perf_counter()
        self.player.start(macro=self.macro, settings=self.settings, override_target=self._selected_target)

    def stop_all(self) -> None:
        self._cancel_countdown()
        if self.recorder.is_recording:
            self.toggle_record()
        if self.player.is_playing:
            self.player.stop()

    def _update_record_ui(self, recording: bool) -> None:
        self._refresh_labels()
        self.btn_play.setEnabled(not recording)
        self.btn_record.set_active(recording)
        if recording:
            scope = (self._selected_target.process_name
                     if self.settings.record_scope == "target" and self._selected_target else "all windows")
            self._set_status(f"Recording · {scope}", "rec")
            self.tray.set_state("recording", "Recording in background…")
        else:
            self._set_timecode(fmt_timecode(self.macro.duration))
            self._set_status(f"Idle — {len(self.macro.events)} events on the reel", "info")
            self.tray.set_state("idle", APP_NAME)
        self.tape.update()
        self._update_tape_info()

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
            self._set_timecode(fmt_timecode(events[ev_idx - 1].timestamp - events[0].timestamp), "play")
        self.tape.update()

    def _update_play_ui(self, playing: bool, message: str) -> None:
        self._refresh_labels()
        self.btn_record.setEnabled(not playing)
        self.btn_play.set_active(playing)
        if playing:
            self._set_status(message, "ok")
            self.tray.set_state("playing", message)
        else:
            self._play_ev_idx = 0
            self._set_timecode(fmt_timecode(self.macro.duration))
            self._set_status(message, "info")
            self.tray.set_state("idle", APP_NAME)
            if message.startswith(("Playback complete", "Time limit")):
                if self.settings.on_finish == "notify":
                    self.tray.notify(APP_NAME, f"Finished: {message}")
                elif self.settings.on_finish == "sound":
                    try:
                        winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    except Exception:
                        pass
            if self.settings.minimize_on_play and not self._is_closing:
                self.show_from_tray()
        self.tape.update()

    # ================================================================== steps list
    def _append_row(self, ev: MacroEvent) -> None:
        self._live_events.append(ev)
        self.model.append(ev)
        self.steps_stack.setCurrentIndex(1)
        self.table.scrollToBottom()
        self.lbl_counts.setText(f"{len(self._live_events)} events · {ev.timestamp:.2f}s")
        self._update_tape_info()

    def _rebuild_steps(self) -> None:
        self.model.set_events(self.macro.events)
        self.steps_stack.setCurrentIndex(1 if self.macro.events else 0)
        self.lbl_counts.setText(f"{len(self.macro.events)} events · {self.macro.duration:.2f}s")
        if not self.recorder.is_recording:
            self._set_timecode(fmt_timecode(self.macro.duration))
        self._update_estimate()
        self._update_tape_info()
        self.tape.update()

    def delete_selected(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            return
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            return
        for r in rows:
            if 0 <= r < len(self.macro.events):
                self.macro.events.pop(r)
        self._set_dirty(True)
        self._rebuild_steps()
        self._set_status(f"Deleted {len(rows)} step(s)", "info")

    def trim_mouse_moves(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            return
        before = len(self.macro.events)
        self.macro.events = [ev for ev in self.macro.events if ev.event_type != "mouse_move"]
        removed = before - len(self.macro.events)
        if removed:
            self._set_dirty(True)
        self._rebuild_steps()
        self._set_status(f"Trimmed {removed} mouse moves", "info")

    # ================================================================== files
    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        name = self._macro_file.stem if self._macro_file else ("Untitled macro" if self.macro.events else "")
        self.setWindowTitle(f"{name}{' •' if dirty else ''} — {APP_NAME}" if name else f"{APP_NAME} v{APP_VERSION}")
        self._update_summary()

    def _confirm_discard(self, action: str) -> bool:
        if not self._dirty or not self.macro.events:
            return True
        self.show_from_tray()
        name = self._macro_file.name if self._macro_file else "Your current macro"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Save your macro?")
        box.setText(f"{name} ({len(self.macro.events)} steps) has unsaved changes.")
        box.setInformativeText(f"Do you want to save it before you {action}?")
        save = box.addButton("Save it", QMessageBox.AcceptRole)
        discard = box.addButton("Throw it away", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() is save:
            return self.save_macro_dialog()
        return box.clickedButton() is discard

    def new_macro(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            self._set_status("Stop recording / playback first", "warn")
            return
        if not self._confirm_discard("start a new one"):
            return
        self.macro = Macro(default_target=self._selected_target)
        self._macro_file = None
        self._set_dirty(False)
        self._rebuild_steps()
        self._set_status(f"New macro — press ● REC ({display_hotkey(self.settings.hotkey_record)}) to record", "info")

    def clear_macro(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            return
        if not self._confirm_discard("clear it"):
            return
        self.macro.events.clear()
        self._macro_file = None
        self._set_dirty(False)
        self._rebuild_steps()
        self._set_status("Reel cleared", "info")

    def save_macro_dialog(self) -> bool:
        if not self.macro.events:
            QMessageBox.information(self, "Save Macro", "There are no recorded steps to save yet.")
            return False
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        start = str(self._macro_file if self._macro_file else MACROS_DIR / "macro.json")
        path, _ = QFileDialog.getSaveFileName(self, "Save Macro", start, "Macro JSON (*.json)")
        if not path:
            return False
        try:
            self.macro.name = Path(path).stem
            self.macro.save(path)
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
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
        path, _ = QFileDialog.getOpenFileName(self, "Open Macro", str(MACROS_DIR), "Macro JSON (*.json)")
        if not path:
            return
        try:
            self.macro = Macro.load(path)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't open the macro", str(exc))
            return
        self._macro_file = Path(path)
        self._set_dirty(False)
        self._rebuild_steps()
        self._set_status(f"Loaded {Path(path).name} · {len(self.macro.events)} events", "info")

    def show_about_dialog(self) -> None:
        s = self.settings
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME} v{APP_VERSION}</b><br>{APP_TAGLINE}<br><br>"
            "Window-aware background macro recorder and player.<br><br>"
            f"Hotkeys: {display_hotkey(s.hotkey_record)} Record · {display_hotkey(s.hotkey_play)} Play · "
            f"{display_hotkey(s.hotkey_stop)} Stop<br><br>"
            f"Settings &amp; macros folder:<br>{get_user_data_dir()}<br><br>"
            "Tip: if an app runs as Administrator or ignores background input, switch Play to Foreground.",
        )

    # ================================================================== updates
    def _auto_update_check(self) -> None:
        if self._is_closing:
            return
        # Every time Ghost opens, then every 6 hours while it keeps running
        if self.settings.check_updates and self._update_info is None:
            self.check_for_updates(manual=False)
        QTimer.singleShot(6 * 3600 * 1000, self._auto_update_check)

    def check_for_updates(self, manual: bool = False) -> None:
        if self._updating:
            return
        if manual:
            self.btn_check.setText("Checking…")
            self.btn_check.setEnabled(False)

        def work() -> None:
            info, error = None, ""
            try:
                info = updater.check_latest()
            except Exception:
                error = "Couldn't reach GitHub. Check your internet connection and try again."
            self.bridge.update_result.emit(info, error, manual)

        threading.Thread(target=work, daemon=True).start()

    def _on_update_result(self, info, error: str, manual: bool) -> None:
        self.btn_check.setText("⟳  Check for updates")
        self.btn_check.setEnabled(True)
        if error:
            if manual:
                QMessageBox.warning(self, "Check for updates", error)
            return
        self.settings.last_update_check = time.time()
        self.settings.save(SETTINGS_PATH)
        if info is None:
            if manual:
                QMessageBox.information(self, "Check for updates", f"You have the newest version ({APP_VERSION}).")
            return
        if not manual and info.version == self.settings.skipped_version:
            return
        self._update_info = info
        size = f" · {info.size / 1e6:.1f} MB" if info.size else ""
        self.lbl_update.setText(f"✨  Version {info.version} is available{size}")
        self.btn_update.setText("Update now")
        self.btn_update.setEnabled(True)
        self.lbl_footer.hide()
        self.update_bar.show()
        if not manual:
            self.tray.notify(f"{APP_NAME} {info.version} is available",
                             "Open Ghost and click Update now. Your macros and settings stay.")

    def _skip_update(self) -> None:
        if self._update_info and not self._updating:
            self.settings.skipped_version = self._update_info.version
            self.settings.save(SETTINGS_PATH)
            self._update_info = None
            self.update_bar.hide()
            self.lbl_footer.show()

    def _open_update_page(self) -> None:
        webbrowser.open(self._update_info.page_url if self._update_info else updater.RELEASES_PAGE)

    def start_update(self) -> None:
        info = self._update_info
        if info is None or self._updating:
            return
        if self.recorder.is_recording or self.player.is_playing:
            QMessageBox.information(self, "Update", "Stop recording or playback first, then click Update now.")
            return
        if not self._confirm_discard("update"):
            return
        self._updating = True
        self.btn_update.setEnabled(False)
        self.btn_update.setText("Downloading…")
        self.btn_skip.setEnabled(False)

        def work() -> None:
            try:
                path = updater.download(info, self.bridge.download_progress.emit, should_stop=lambda: self._is_closing)
                self.bridge.download_done.emit(path)
            except Exception as exc:
                self.bridge.download_failed.emit(
                    str(exc) if isinstance(exc, RuntimeError) else "The download failed. Check your connection.")

        threading.Thread(target=work, daemon=True).start()

    def _install_update(self, path) -> None:
        self.lbl_update.setText("Installing… Ghost will close and open again.")
        try:
            updater.run_installer(path)
        except Exception as exc:
            self._update_failed(f"{exc} You can download it from the website instead.")
            return
        QTimer.singleShot(250, self.quit_app)

    def _update_failed(self, message: str) -> None:
        self._updating = False
        self.btn_update.setEnabled(True)
        self.btn_update.setText("Try again")
        self.btn_skip.setEnabled(True)
        if self._update_info:
            self.lbl_update.setText(f"✨  Version {self._update_info.version} is available")
        QMessageBox.warning(self, "Update", message)

    # ================================================================== window life
    def present(self) -> None:
        """First appearance: fade in."""
        if self._start_hidden:
            return
        self.setWindowOpacity(0.0)
        self.show()
        self._dark_title_bar()
        self._apply_on_top()
        anim = QVariantAnimation(self)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        self._fade_in = anim

    def show_from_tray(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.setWindowOpacity(1.0)
        self.raise_()
        self.activateWindow()
        try:
            user32.SetForegroundWindow(self._hwnd())
        except Exception:
            pass
        self._dark_title_bar()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        QTimer.singleShot(0, self._place_summary)

    def _place_summary(self) -> None:
        room = self.right.height() - self.tabs_card.sizeHint().height()
        self.summary.setVisible(room >= 190)

    def closeEvent(self, e) -> None:
        if self._is_closing:
            e.accept()
            return
        if self.settings.close_to_tray:
            e.ignore()
            self.hide()
            return
        e.ignore()
        self.request_exit()

    def request_exit(self) -> None:
        if self.recorder.is_recording or self.player.is_playing:
            self.stop_all()
        if self._confirm_discard("quit"):
            self.quit_app()

    def quit_app(self) -> None:
        self._is_closing = True
        self.recorder.stop()
        self.player.stop()
        self.hotkeys.stop()
        self.tray.stop()
        self.close()
        QApplication.instance().quit()
