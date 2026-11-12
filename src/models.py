"""Data models and JSON persistence for Ghost Macro Recorder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Optional


ALLOWED_EVENT_TYPES = frozenset(
    {"mouse_down", "mouse_up", "mouse_move", "mouse_scroll", "key_down", "key_up"}
)
ALLOWED_BUTTONS = frozenset({"", "left", "right", "middle"})
MAX_MACRO_FILE_BYTES = 10 * 1024 * 1024
MAX_MACRO_EVENTS = 100_000


@dataclass
class WindowTarget:
    """Identifies a desktop window so events can be recorded and replayed relative to it."""

    hwnd: int = 0
    title: str = ""
    process_name: str = ""
    class_name: str = ""
    pid: int = 0
    client_width: int = 0
    client_height: int = 0

    @property
    def display_label(self) -> str:
        """Return a readable window label for dropdowns and timelines."""
        proc = self.process_name or "unknown"
        title = self.title.strip() or self.class_name or f"HWND {self.hwnd}"
        if len(title) > 48:
            title = title[:45] + "..."
        return f"[{proc}] {title}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> Optional[WindowTarget]:
        if not data:
            return None
        return cls(
            hwnd=int(data.get("hwnd", 0)),
            title=str(data.get("title", "")),
            process_name=str(data.get("process_name", "")),
            class_name=str(data.get("class_name", "")),
            pid=int(data.get("pid", 0)),
            client_width=int(data.get("client_width", 0)),
            client_height=int(data.get("client_height", 0)),
        )


@dataclass
class MacroEvent:
    """A single recorded mouse or keyboard event bound to a window target."""

    timestamp: float
    event_type: str  # mouse_down, mouse_up, mouse_move, mouse_scroll, key_down, key_up
    target: Optional[WindowTarget] = None
    rel_x: int = 0
    rel_y: int = 0
    norm_x: float = 0.0
    norm_y: float = 0.0
    screen_x: int = 0
    screen_y: int = 0
    button: str = ""
    scroll_dx: int = 0
    scroll_dy: int = 0
    vk_code: int = 0
    key_name: str = ""
    char: str = ""
    scan_code: int = 0
    is_extended: bool = False

    def resolve_client_coords(
        self, current_width: int, current_height: int, scale: bool = True
    ) -> tuple[int, int]:
        """Compute target client coordinates, optionally scaling to current window size."""
        if scale and current_width > 0 and current_height > 0 and (self.norm_x or self.norm_y):
            x = int(round(self.norm_x * current_width))
            y = int(round(self.norm_y * current_height))
            return max(0, min(current_width - 1, x)), max(0, min(current_height - 1, y))
        return self.rel_x, self.rel_y

    def summary(self) -> tuple[str, str]:
        """Return (action_label, detail_text) for timeline display."""
        if self.event_type == "mouse_down":
            return f"{self.button.capitalize()} Down", f"Client ({self.rel_x}, {self.rel_y})"
        if self.event_type == "mouse_up":
            return f"{self.button.capitalize()} Up", f"Client ({self.rel_x}, {self.rel_y})"
        if self.event_type == "mouse_move":
            return "Mouse Move", f"Client ({self.rel_x}, {self.rel_y})"
        if self.event_type == "mouse_scroll":
            direction = "Up" if self.scroll_dy > 0 else "Down"
            return f"Scroll {direction}", f"dy={self.scroll_dy} @ ({self.rel_x}, {self.rel_y})"
        if self.event_type == "key_down":
            label = self.key_name or self.char or f"VK_{self.vk_code}"
            return "Key Down", label
        if self.event_type == "key_up":
            label = self.key_name or self.char or f"VK_{self.vk_code}"
            return "Key Up", label
        return self.event_type, ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["target"] = self.target.to_dict() if self.target else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MacroEvent:
        if not isinstance(data, dict):
            raise ValueError("Macro event entry must be an object.")
        event_type = str(data.get("event_type", ""))
        if event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"Unsupported macro event type: {event_type!r}")
        button = str(data.get("button", "")).lower()
        if button not in ALLOWED_BUTTONS:
            raise ValueError(f"Unsupported mouse button: {button!r}")
        timestamp = max(0.0, float(data.get("timestamp", 0.0)))
        vk_code = max(0, min(0xFF, int(data.get("vk_code", 0))))
        char = str(data.get("char", ""))[:1]
        return cls(
            timestamp=timestamp,
            event_type=event_type,
            target=WindowTarget.from_dict(data.get("target")),
            rel_x=int(data.get("rel_x", 0)),
            rel_y=int(data.get("rel_y", 0)),
            norm_x=max(0.0, min(1.0, float(data.get("norm_x", 0.0)))),
            norm_y=max(0.0, min(1.0, float(data.get("norm_y", 0.0)))),
            screen_x=int(data.get("screen_x", 0)),
            screen_y=int(data.get("screen_y", 0)),
            button=button,
            scroll_dx=int(data.get("scroll_dx", 0)),
            scroll_dy=int(data.get("scroll_dy", 0)),
            vk_code=vk_code,
            key_name=str(data.get("key_name", ""))[:32],
            char=char,
            scan_code=max(0, min(0xFF, int(data.get("scan_code", 0)))),
            is_extended=bool(data.get("is_extended", False)),
        )


@dataclass
class Macro:
    """A complete recorded macro with target metadata and ordered events."""

    name: str = "Untitled Macro"
    version: int = 1
    default_target: Optional[WindowTarget] = None
    events: list[MacroEvent] = field(default_factory=list)

    @property
    def duration(self) -> float:
        if not self.events:
            return 0.0
        return max(0.0, self.events[-1].timestamp - self.events[0].timestamp)

    def save(self, path: str | Path) -> Path:
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": self.name,
            "version": self.version,
            "default_target": self.default_target.to_dict() if self.default_target else None,
            "events": [ev.to_dict() for ev in self.events],
        }
        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target_path

    @classmethod
    def load(cls, path: str | Path) -> Macro:
        src_path = Path(path)
        if src_path.stat().st_size > MAX_MACRO_FILE_BYTES:
            raise ValueError("Macro file exceeds maximum allowed size (10 MB).")
        data = json.loads(src_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Macro file root must be a JSON object.")
        raw_events = data.get("events", [])
        if not isinstance(raw_events, list):
            raise ValueError("Macro 'events' field must be a list.")
        if len(raw_events) > MAX_MACRO_EVENTS:
            raise ValueError(f"Macro exceeds maximum event count ({MAX_MACRO_EVENTS}).")
        return cls(
            name=str(data.get("name", src_path.stem))[:120],
            version=int(data.get("version", 1)),
            default_target=WindowTarget.from_dict(data.get("default_target")),
            events=[MacroEvent.from_dict(item) for item in raw_events],
        )


@dataclass
class AppSettings:
    """User-configurable settings persisted locally."""

    playback_mode: str = "background"  # "background" | "foreground"
    record_scope: str = "target"  # "target" | "all"
    record_mouse_moves: bool = False
    scale_coordinates: bool = True
    minimize_on_record: bool = False
    minimize_on_play: bool = False
    close_to_tray: bool = True
    speed: float = 1.0
    repeat_count: int = 1  # 0 = infinite
    run_limit_mode: str = "count"  # "count" (repeat N times) | "time" (loop until duration ends)
    run_duration: float = 60.0  # seconds, used when run_limit_mode == "time"
    loop_delay: float = 0.25
    hotkey_record: str = "F9"
    hotkey_play: str = "F10"
    hotkey_stop: str = "F12"
    appearance_mode: str = "Dark"

    def save(self, path: str | Path) -> Path:
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return target_path

    @classmethod
    def load(cls, path: str | Path) -> AppSettings:
        target_path = Path(path)
        if not target_path.exists():
            return cls()
        try:
            data = json.loads(target_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        defaults = asdict(cls())
        defaults.update({k: v for k, v in data.items() if k in defaults})
        return cls(**defaults)

