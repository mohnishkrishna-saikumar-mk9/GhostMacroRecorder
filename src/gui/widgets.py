"""Custom-painted controls: transport keys, switches, segmented pickers, the tape, the target picker."""

from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import (
    QAbstractTableModel, QEasingCurve, QModelIndex, QPoint, QPointF, QRectF, QSize, Qt, QTimer,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QStackedWidget, QStyledItemDelegate, QStyle, QVBoxLayout, QWidget,
)

from src.gui.theme import LANE_OF, LANES, Theme
from src.models import MacroEvent, WindowTarget


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def _anim(owner, ms: int, on_value: Callable[[float], None]) -> QVariantAnimation:
    anim = QVariantAnimation(owner)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    return anim


def _run(anim: QVariantAnimation, start: float, end: float) -> None:
    anim.stop()
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.start()


# ----------------------------------------------------------------------------- transport key
class RoundKey(QAbstractButton):
    """Big round REC / PLAY / STOP key: glows on hover, dips when pressed, rings when active."""

    def __init__(self, colour: str, glyph: str, glyph_colour: str, parent=None) -> None:
        super().__init__(parent)
        self.colour, self.glyph, self.glyph_colour = colour, glyph, glyph_colour
        self.active = False
        self._hover = 0.0
        self._press = 0.0
        self.setFixedSize(68, 68)
        self.setCursor(Qt.PointingHandCursor)
        self._hover_anim = _anim(self, 140, self._set_hover)
        self._press_anim = _anim(self, 90, self._set_press)

    def _set_hover(self, v: float) -> None:
        self._hover = v
        self.update()

    def _set_press(self, v: float) -> None:
        self._press = v
        self.update()

    def set_glyph(self, glyph: str) -> None:
        if glyph != self.glyph:
            self.glyph = glyph
            self.update()

    def set_active(self, on: bool) -> None:
        if on != self.active:
            self.active = on
            self.update()

    def enterEvent(self, e) -> None:
        _run(self._hover_anim, self._hover, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        _run(self._hover_anim, self._hover, 0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:
        _run(self._press_anim, self._press, 1.0)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        _run(self._press_anim, self._press, 0.0)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = Theme.q(self.colour)
        if not self.isEnabled():
            base = _mix(base, Theme.q("panel"), 0.55)
        hover_to = QColor("#ffffff") if Theme.dark else QColor("#000000")
        fill = _mix(base, hover_to, 0.10 * self._hover)
        r = 30 - 2.0 * self._press
        cx, cy = self.width() / 2, self.height() / 2
        if self.active:
            ring = QColor(base)
            ring.setAlpha(110)
            p.setPen(QPen(ring, 3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), 32.5, 32.5)
        elif self._hover > 0:
            glow = QColor(base)
            glow.setAlpha(int(55 * self._hover))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), r + 4, r + 4)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawEllipse(QPointF(cx, cy), r, r)
        # glyph
        g = Theme.q(self.glyph_colour)
        if not self.isEnabled():
            g.setAlpha(140)
        p.setBrush(g)
        s = 10 - self._press
        if self.glyph == "rec":
            p.drawEllipse(QPointF(cx, cy), s, s)
        elif self.glyph == "play":
            p.drawPolygon(QPolygonF([QPointF(cx - s * 0.7, cy - s), QPointF(cx - s * 0.7, cy + s),
                                     QPointF(cx + s * 1.05, cy)]))
        else:  # stop square
            p.drawRoundedRect(QRectF(cx - s * 0.85, cy - s * 0.85, s * 1.7, s * 1.7), 2.5, 2.5)


# ----------------------------------------------------------------------------- switch
class Toggle(QAbstractButton):
    """iOS-style switch with a gliding knob."""

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._pos = 1.0 if checked else 0.0
        self._anim = _anim(self, 160, self._set_pos)
        self.toggled.connect(lambda on: _run(self._anim, self._pos, 1.0 if on else 0.0))

    def _set_pos(self, v: float) -> None:
        self._pos = v
        self.update()

    def set_quietly(self, on: bool) -> None:
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._pos = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = _mix(Theme.q("line"), Theme.q("accent"), self._pos)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor("#ffffff") if not Theme.dark else QColor("#eef0f3"))
        x = 3 + self._pos * 18
        p.drawEllipse(QRectF(x, 3, 16, 16))


# ----------------------------------------------------------------------------- segmented picker
class Segmented(QWidget):
    """Pill of options; the dark (inverted) highlight slides to the chosen one."""

    changed = Signal(str)

    def __init__(self, values: list[str], current: str = "", height: int = 32, font_px: int = 12, parent=None) -> None:
        super().__init__(parent)
        self.values = list(values)
        self.index = self.values.index(current) if current in self.values else 0
        self._x = float(self.index)
        self._hover = -1
        self.font_px = font_px
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(60 * len(values))
        self._anim = _anim(self, 200, self._set_x)

    def _set_x(self, v: float) -> None:
        self._x = v
        self.update()

    def value(self) -> str:
        return self.values[self.index]

    def set_value(self, value: str, animate: bool = True, emit: bool = False) -> None:
        if value not in self.values:
            return
        i = self.values.index(value)
        if i == self.index:
            return
        self.index = i
        if animate and self.isVisible():
            _run(self._anim, self._x, float(i))
        else:
            self._x = float(i)
            self.update()
        if emit:
            self.changed.emit(value)

    def _seg_at(self, x: float) -> int:
        w = self.width() / len(self.values)
        return max(0, min(len(self.values) - 1, int(x // w)))

    def mouseMoveEvent(self, e) -> None:
        h = self._seg_at(e.position().x())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.set_value(self.values[self._seg_at(e.position().x())], emit=True)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self.values)
        seg_w = w / n
        p.setPen(Qt.NoPen)
        p.setBrush(Theme.q("seg"))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)
        if 0 <= self._hover != self.index:
            p.setBrush(Theme.q("ghost_hover"))
            p.drawRoundedRect(QRectF(self._hover * seg_w + 2, 2, seg_w - 4, h - 4), 6, 6)
        p.setBrush(Theme.q("text"))
        p.drawRoundedRect(QRectF(self._x * seg_w + 2, 2, seg_w - 4, h - 4), 6, 6)
        p.setFont(Theme.font(self.font_px, 600))
        inv = Theme.q("panel_hi") if not Theme.dark else Theme.q("bg")
        for i, label in enumerate(self.values):
            closeness = max(0.0, 1.0 - abs(self._x - i))
            p.setPen(_mix(Theme.q("text"), inv, closeness))
            p.drawText(QRectF(i * seg_w, 0, seg_w, h), Qt.AlignCenter, label)


# ----------------------------------------------------------------------------- fading pages
class FadeStack(QStackedWidget):
    """Stacked pages that fade in when switched."""

    def fade_to(self, index: int) -> None:
        if index == self.currentIndex():
            return
        self.setCurrentIndex(index)
        page = self.currentWidget()
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = _anim(page, 170, effect.setOpacity)
        anim.finished.connect(lambda: page.setGraphicsEffect(None))
        _run(anim, 0.0, 1.0)


# ----------------------------------------------------------------------------- tape
class TapeView(QWidget):
    """Multi-lane tape: every click, key, scroll and move as a tick; a head during record/play."""

    LABEL_W = 62

    def __init__(self, provider: Callable[[], dict], parent=None) -> None:
        super().__init__(parent)
        self.provider = provider
        self.setMinimumHeight(96)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

    def paintEvent(self, _e) -> None:
        state = self.provider()
        events: list[MacroEvent] = state["events"]
        recording: bool = state["recording"]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)
        p.fillPath(path, Theme.q("panel_hi"))
        p.setClipPath(path)
        line = Theme.q("line")
        lane_h = h / len(LANES)
        x0, x1 = self.LABEL_W, w - 10
        span_w = max(1.0, x1 - x0)
        p.setFont(Theme.font(9, 700))
        for i, (_lane, label, _c, _t) in enumerate(LANES):
            y = i * lane_h
            if i:
                p.setPen(QPen(line, 1))
                p.drawLine(QPointF(0, y), QPointF(w, y))
            p.setPen(Theme.q("muted"))
            p.drawText(QRectF(12, y, x0 - 16, lane_h), Qt.AlignVCenter | Qt.AlignLeft, label)
        p.setPen(QPen(line, 1))
        p.drawLine(QPointF(x0 - 6, 0), QPointF(x0 - 6, h))

        if not events and not recording:
            p.setPen(Theme.q("muted"))
            p.setFont(Theme.font(11))
            p.drawText(QRectF(x0, 0, span_w, h), Qt.AlignCenter, "— blank tape —")
            return

        t0 = events[0].timestamp if events else 0.0
        started = state.get("record_started")
        if recording and started is not None:
            span = max(time.perf_counter() - started, 1.0)
            t0 = 0.0 if not events else min(t0, 0.0)
        else:
            span = max((events[-1].timestamp - t0) if events else 0.0, 0.5)

        step = 1.0
        for cand in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
            if span / cand <= 12:
                step = float(cand)
                break
        grid = QPen(line, 1, Qt.DotLine)
        p.setPen(grid)
        s = 0.0
        while s <= span:
            gx = x0 + (s / span) * span_w
            p.drawLine(QPointF(gx, 0), QPointF(gx, h))
            s += step

        lane_index = {lane: i for i, (lane, *_r) in enumerate(LANES)}
        colours = {lane: Theme.lane(lane) for lane, *_r in LANES}
        seen: set[tuple[int, int]] = set()
        p.setRenderHint(QPainter.Antialiasing, False)
        for ev in events:
            lane = LANE_OF.get(ev.event_type)
            if lane is None:
                continue
            px = int(x0 + ((ev.timestamp - t0) / span) * span_w)
            li = lane_index[lane]
            if (li, px) in seen:
                continue
            seen.add((li, px))
            cy = li * lane_h + lane_h / 2
            half = lane_h * (0.18 if lane == "move" else 0.32)
            p.setPen(QPen(colours[lane], 2))
            p.drawLine(QPointF(px, cy - half), QPointF(px, cy + half))
        p.setRenderHint(QPainter.Antialiasing, True)

        play_idx = state.get("play_idx", 0)
        if recording:
            self._head(p, x1, h, Theme.q("rec"))
        elif state.get("playing") and events and play_idx:
            idx = min(play_idx, len(events)) - 1
            px = x0 + ((events[idx].timestamp - t0) / span) * span_w
            done = Theme.q("accent")
            done.setAlpha(34)
            p.fillRect(QRectF(x0, 0, px - x0, h), done)
            self._head(p, px, h, Theme.q("accent"))

    @staticmethod
    def _head(p: QPainter, x: float, h: float, colour: QColor) -> None:
        p.setPen(QPen(colour, 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.setPen(Qt.NoPen)
        p.setBrush(colour)
        p.drawPolygon(QPolygonF([QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, 7)]))


# ----------------------------------------------------------------------------- steps table model
class StepsModel(QAbstractTableModel):
    HEADERS = ("#", "TIME", "ACTION", "WINDOW", "DETAILS")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.events: list[MacroEvent] = []
        self._rows: list[tuple] = []

    @staticmethod
    def _row(i: int, ev: MacroEvent) -> tuple:
        action, details = ev.summary()
        target = ev.target.display_label if ev.target else "—"
        return (str(i), f"{ev.timestamp:.3f}", action, target, details, LANE_OF.get(ev.event_type, "move"))

    def set_events(self, events: list[MacroEvent]) -> None:
        self.beginResetModel()
        self.events = list(events)
        self._rows = [self._row(i, ev) for i, ev in enumerate(self.events, start=1)]
        self.endResetModel()

    def append(self, ev: MacroEvent) -> None:
        n = len(self._rows)
        self.beginInsertRows(QModelIndex(), n, n)
        self.events.append(ev)
        self._rows.append(self._row(n + 1, ev))
        self.endInsertRows()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else 5

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            return row[col]
        if role == Qt.ForegroundRole and col == 2:
            return QBrush(Theme.lane(row[5]) if row[5] != "move" else Theme.q("muted"))
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignRight if col < 2 else Qt.AlignLeft) | Qt.AlignVCenter)
        if role == Qt.FontRole and col in (0, 1):
            return Theme.font(12, 400, Theme.mono)
        if role == Qt.FontRole and col == 2:
            return Theme.font(12, 600)
        return None

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            return int((Qt.AlignRight if section < 2 else Qt.AlignLeft) | Qt.AlignVCenter)
        return None

    def refresh_colours(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0, 2), self.index(len(self._rows) - 1, 2))


# ----------------------------------------------------------------------------- target picker
def short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _TargetDelegate(QStyledItemDelegate):
    """A row in the window list: accent bar when chosen, process chip, window title, check."""

    def paint(self, p: QPainter, option, index) -> None:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(2, 1, -2, -1)
        target, chosen = index.data(Qt.UserRole)
        if chosen or option.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen)
            p.setBrush(Theme.q("ghost_hover"))
            p.drawRoundedRect(r, 8, 8)
        elif option.state & QStyle.State_MouseOver:
            p.setPen(Qt.NoPen)
            p.setBrush(Theme.q("panel"))
            p.drawRoundedRect(r, 8, 8)
        if chosen:
            p.setBrush(Theme.q("accent"))
            p.drawRoundedRect(QRectF(r.left() + 4, r.top() + 9, 3, r.height() - 18), 1.5, 1.5)
        chip = "ANY APP" if target is None else short(target.process_name or "app", 18)
        title = ("All windows — record whatever you click" if target is None
                 else short(target.title or target.class_name or "(untitled window)", 70))
        cf = Theme.font(10, 700, Theme.mono)
        p.setFont(cf)
        cw = min(150, QFontMetrics(cf).horizontalAdvance(chip) + 16)
        chip_r = QRectF(r.left() + 14, r.center().y() - 11, cw, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(Theme.q("key"))
        p.drawRoundedRect(chip_r, 5, 5)
        p.setPen(Theme.q("accent") if chosen else Theme.q("muted"))
        p.drawText(chip_r, Qt.AlignCenter, chip)
        p.setPen(Theme.q("text"))
        p.setFont(Theme.font(12, 700 if chosen else 400))
        text_r = QRectF(chip_r.right() + 10, r.top(), r.right() - chip_r.right() - 40, r.height())
        p.drawText(text_r, Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(p.font()).elidedText(title, Qt.ElideRight, int(text_r.width())))
        if chosen:
            p.setPen(Theme.q("accent"))
            p.setFont(Theme.font(13, 700))
            p.drawText(QRectF(r.right() - 28, r.top(), 20, r.height()), Qt.AlignCenter, "✓")
        p.restore()

    def sizeHint(self, _option, _index) -> QSize:
        return QSize(200, 40)


class TargetPopup(QFrame):
    chosen = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.inner = QFrame(self)
        self.inner.setObjectName("popup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.inner)
        lay = QVBoxLayout(self.inner)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search open windows…")
        self.search.textChanged.connect(self._fill)
        self.search.returnPressed.connect(self._pick_first)
        self.list = QListWidget()
        self.list.setItemDelegate(_TargetDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.itemClicked.connect(lambda it: self._choose(it.data(Qt.UserRole)[0]))
        self.empty = QLabel("No open window matches that search.")
        self.empty.setProperty("role", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.empty)
        self.choices: list[WindowTarget] = []
        self.selected: Optional[WindowTarget] = None

    def open_below(self, anchor: QWidget, choices: list[WindowTarget], selected: Optional[WindowTarget]) -> None:
        self.choices, self.selected = list(choices), selected
        self.search.clear()
        self._fill()
        rows = min(len(self.choices) + 1, 7)
        self.resize(anchor.width(), 62 + rows * 42 + 8)
        self.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        self.show()
        self.search.setFocus()

    def _matches(self) -> list[Optional[WindowTarget]]:
        q = self.search.text().strip().lower()
        items: list[Optional[WindowTarget]] = [None] + self.choices
        if not q:
            return items
        return [t for t in items if t is not None and (q in t.process_name.lower() or q in t.title.lower())]

    def _fill(self, *_a) -> None:
        self.list.clear()
        matches = self._matches()
        for t in matches:
            chosen = (t is None and self.selected is None) or (
                t is not None and self.selected is not None and t.hwnd == self.selected.hwnd)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, (t, chosen))
            self.list.addItem(item)
        self.empty.setVisible(not matches)
        self.list.setVisible(bool(matches))

    def _pick_first(self) -> None:
        if self.list.count():
            self._choose(self.list.item(0).data(Qt.UserRole)[0])

    def _choose(self, target: Optional[WindowTarget]) -> None:
        self.hide()
        self.chosen.emit(target)


class TargetField(QFrame):
    """The field showing the chosen app; click to open the searchable window list."""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("well")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 10, 0)
        lay.setSpacing(10)
        self.chip = QLabel()
        self.chip.setObjectName("chip")
        self.title = QLabel()
        self.chev = QLabel("▾")
        self.chev.setProperty("role", "muted")
        lay.addWidget(self.chip)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.chev)
        self.set_target(None)

    def set_target(self, t: Optional[WindowTarget]) -> None:
        if t is None:
            self.chip.setText("ANY APP")
            self._full = "All windows — record whatever you click"
        else:
            self.chip.setText(short(t.process_name or "app", 22))
            self._full = short(t.title or t.class_name or "(untitled window)", 120)
        self._elide()

    def _elide(self) -> None:
        w = max(40, self.title.width())
        self.title.setText(QFontMetrics(self.title.font()).elidedText(self._full, Qt.ElideRight, w))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._elide()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def enterEvent(self, e) -> None:
        self.setStyleSheet(f"QFrame#well {{ border-color: {Theme.c('accent')}; }}")
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.setStyleSheet("")
        super().leaveEvent(e)
