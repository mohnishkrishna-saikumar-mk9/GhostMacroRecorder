"""Palette, fonts and the Qt style sheet for both themes."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

# (light, dark) pairs. Light is warm "studio paper", dark is graphite hardware with amber/LED accents.
C = {
    "bg": ("#efebe3", "#0c0d10"),
    "panel": ("#f8f6f1", "#14161a"),
    "panel_hi": ("#ffffff", "#1b1e23"),
    "line": ("#d9d3c7", "#262a31"),
    "text": ("#1b1d21", "#e7e9ec"),
    "muted": ("#6f6a60", "#868d98"),
    "hint": ("#5d584f", "#a2a9b4"),
    "accent": ("#d9820b", "#ffb020"),
    "accent_hover": ("#b86d06", "#e09a12"),
    "accent_text": ("#ffffff", "#1a1206"),
    "rec": ("#e5383b", "#ff4d4f"),
    "play": ("#13a873", "#3ddc97"),
    "play_text": ("#ffffff", "#06261a"),
    "stop": ("#cfc8bb", "#2a2e35"),
    "ghost_hover": ("#e6e0d4", "#20242a"),
    "key": ("#e3ddd1", "#22262c"),
    "info": ("#2f6fd6", "#6aa8ff"),
    "warn": ("#c77700", "#f5a524"),
    "scroll": ("#c9c2b4", "#3d434d"),
    "seg": ("#e9e4da", "#202329"),
}

# Tape lanes: (lane key, label, (light, dark) colour, event types)
LANES = [
    ("click", "CLICK", ("#d9820b", "#ffb020"), {"mouse_down", "mouse_up"}),
    ("key", "KEYS", ("#0f8fb3", "#4cc9f0"), {"key_down", "key_up"}),
    ("scroll", "SCROLL", ("#7b4fd6", "#b388ff"), {"mouse_scroll"}),
    ("move", "MOVE", ("#9a9488", "#5b626d"), {"mouse_move"}),
]
LANE_OF = {etype: lane for lane, _l, _c, types in LANES for etype in types}


class Theme:
    """The current look. Custom-painted widgets read colours from here."""

    dark = True
    sans = "Segoe UI"
    display = "Segoe UI"
    mono = "Consolas"

    @classmethod
    def c(cls, name: str) -> str:
        return C[name][1 if cls.dark else 0]

    @classmethod
    def q(cls, name: str) -> QColor:
        return QColor(cls.c(name))

    @classmethod
    def lane(cls, lane: str) -> QColor:
        for key, _label, colour, _types in LANES:
            if key == lane:
                return QColor(colour[1 if cls.dark else 0])
        return cls.q("muted")

    @classmethod
    def pick_fonts(cls) -> None:
        families = set(QFontDatabase.families())
        cls.sans = "Segoe UI Variable Text" if "Segoe UI Variable Text" in families else "Segoe UI"
        cls.display = "Segoe UI Variable Display" if "Segoe UI Variable Display" in families else cls.sans
        cls.mono = next((f for f in ("Cascadia Mono", "Cascadia Code", "Consolas") if f in families), "Courier New")

    @classmethod
    def font(cls, px: int, weight: int = 400, family: str | None = None) -> QFont:
        f = QFont(family or cls.sans)
        f.setPixelSize(px)
        f.setWeight(QFont.Weight(weight))
        f.setHintingPreference(QFont.PreferNoHinting)
        return f


def stylesheet() -> str:
    c = Theme.c
    return f"""
    * {{ font-family: "{Theme.sans}"; outline: 0; }}
    QWidget#root, QMainWindow {{ background: {c('bg')}; }}
    QWidget {{ color: {c('text')}; font-size: 13px; }}
    QFrame#card {{ background: {c('panel')}; border: 1px solid {c('line')}; border-radius: 14px; }}
    QFrame#well {{ background: {c('panel_hi')}; border: 1px solid {c('line')}; border-radius: 10px; }}
    QFrame#pill {{ background: {c('panel')}; border: 1px solid {c('line')}; border-radius: 15px; }}
    QFrame#updatebar {{ background: {c('panel')}; border: 1px solid {c('accent')}; border-radius: 10px; }}
    QLabel {{ background: transparent; border: 0; }}
    QLabel[role="muted"] {{ color: {c('muted')}; }}
    QLabel[role="hint"] {{ color: {c('hint')}; }}
    QLabel[role="eyebrow"] {{ color: {c('muted')}; font-size: 10px; font-weight: 700; letter-spacing: 2px; }}
    QLabel[role="title"] {{ font-family: "{Theme.display}"; font-size: 16px; font-weight: 700; }}
    QLabel[role="setting"] {{ font-size: 13px; font-weight: 700; }}
    QLabel[role="accent"] {{ color: {c('accent')}; }}
    QLabel[role="warn"] {{ color: {c('warn')}; }}
    QLabel[role="ok"] {{ color: {c('play')}; }}
    QLabel#timecode {{ font-family: "{Theme.mono}"; font-size: 36px; font-weight: 700; }}
    QLabel#mono {{ font-family: "{Theme.mono}"; font-size: 11px; color: {c('muted')}; }}
    QLabel#speed {{ font-family: "{Theme.mono}"; font-size: 13px; font-weight: 700; color: {c('accent')}; }}
    QLabel#estimate {{ font-family: "{Theme.mono}"; font-size: 12px; font-weight: 700; color: {c('accent')}; }}
    QLabel#keycap {{ background: {c('key')}; color: {c('muted')}; border-radius: 4px; padding: 1px 5px;
        font-family: "{Theme.mono}"; font-size: 10px; font-weight: 700; }}
    QLabel#chip {{ background: {c('key')}; color: {c('accent')}; border-radius: 5px; padding: 3px 8px;
        font-family: "{Theme.mono}"; font-size: 11px; font-weight: 700; }}

    QPushButton {{ border-radius: 8px; padding: 0 12px; min-height: 32px; font-size: 12px; }}
    QPushButton#ghost {{ background: transparent; border: 1px solid {c('line')}; color: {c('text')}; }}
    QPushButton#ghost:hover {{ background: {c('ghost_hover')}; }}
    QPushButton#ghost:pressed {{ background: {c('line')}; }}
    QPushButton#ghost:disabled {{ color: {c('muted')}; }}
    QPushButton#accent {{ background: {c('accent')}; color: {c('accent_text')}; border: 0; font-weight: 700; }}
    QPushButton#accent:hover {{ background: {c('accent_hover')}; }}
    QPushButton#accent:pressed {{ background: {c('accent_hover')}; padding-top: 1px; }}
    QPushButton#accent:disabled {{ background: {c('line')}; color: {c('muted')}; }}
    QPushButton#hotkey {{ background: {c('key')}; border: 1px solid {c('line')}; color: {c('text')};
        font-family: "{Theme.mono}"; font-weight: 700; min-width: 140px; min-height: 28px; }}
    QPushButton#hotkey:hover {{ background: {c('ghost_hover')}; }}
    QPushButton#hotkey[waiting="true"] {{ border-color: {c('accent')}; color: {c('accent')}; }}
    QPushButton#link {{ background: transparent; border: 0; color: {c('warn')}; padding: 0; min-height: 0;
        font-size: 11px; text-align: right; }}
    QPushButton#link:hover {{ text-decoration: underline; }}

    QLineEdit {{ background: {c('panel_hi')}; border: 1px solid {c('line')}; border-radius: 8px; padding: 6px 10px;
        selection-background-color: {c('accent')}; selection-color: {c('accent_text')}; }}
    QLineEdit:focus {{ border-color: {c('accent')}; }}
    QLineEdit#big {{ background: transparent; border: 0; padding: 0 2px; font-family: "{Theme.mono}";
        font-size: 20px; font-weight: 700; }}

    QTableView {{ background: {c('panel')}; alternate-background-color: {c('panel_hi')}; border: 0;
        gridline-color: transparent; selection-background-color: {c('ghost_hover')};
        selection-color: {c('accent')}; font-size: 12px; }}
    QTableView::item {{ padding: 0 6px; border: 0; }}
    QHeaderView::section {{ background: {c('panel')}; color: {c('muted')}; border: 0;
        border-bottom: 1px solid {c('line')}; padding: 6px; font-size: 10px; font-weight: 700; }}
    QTableCornerButton::section {{ background: {c('panel')}; border: 0; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c('scroll')}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {c('accent')}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c('scroll')}; border-radius: 3px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSlider {{ min-height: 22px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c('line')}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c('accent')}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {c('accent')}; width: 16px; height: 16px; margin: -6px 0;
        border-radius: 8px; }}
    QSlider::handle:horizontal:hover {{ background: {c('accent_hover')}; }}

    QListWidget {{ background: transparent; border: 0; }}
    QListWidget::item {{ border-radius: 8px; padding: 0; }}
    QListWidget::item:hover {{ background: {c('panel')}; }}
    QListWidget::item:selected {{ background: {c('ghost_hover')}; color: {c('text')}; }}
    QFrame#popup {{ background: {c('panel_hi')}; border: 1px solid {c('line')}; border-radius: 10px; }}

    QMenu {{ background: {c('panel_hi')}; border: 1px solid {c('line')}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {c('ghost_hover')}; }}
    QMenu::separator {{ height: 1px; background: {c('line')}; margin: 4px 8px; }}
    QToolTip {{ background: {c('panel_hi')}; color: {c('text')}; border: 1px solid {c('line')}; padding: 4px 8px; }}
    QMessageBox, QDialog {{ background: {c('panel')}; }}
    QMessageBox QPushButton {{ background: {c('panel_hi')}; border: 1px solid {c('line')}; min-width: 80px; }}
    QMessageBox QPushButton:hover {{ background: {c('ghost_hover')}; }}
    QMessageBox QPushButton:default {{ border-color: {c('accent')}; }}
    """
