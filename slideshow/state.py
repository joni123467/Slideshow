"""Zustandsverwaltung für die Slideshow."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from typing import Optional

from .config import DATA_DIR
STATE_PATH = DATA_DIR / "state.json"

_lock = threading.Lock()


@dataclass
class PlaybackState:
    primary_item: Optional[str]
    primary_started_at: Optional[float]
    primary_status: str
    secondary_item: Optional[str]
    secondary_started_at: Optional[float]
    secondary_status: str
    info_screen: bool
    info_manual: bool


_state = PlaybackState(
    primary_item=None,
    primary_started_at=None,
    primary_status="stopped",
    secondary_item=None,
    secondary_started_at=None,
    secondary_status="stopped",
    info_screen=False,
    info_manual=False,
)


def load_state() -> PlaybackState:
    """Lädt den letzten bekannten Wiedergabestatus."""

    global _state
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text("utf-8"))
            _state = PlaybackState(
                primary_item=data.get("primary_item", data.get("current_item")),
                primary_started_at=data.get("primary_started_at", data.get("started_at")),
                primary_status=data.get("primary_status", data.get("status", "stopped")),
                secondary_item=data.get("secondary_item"),
                secondary_started_at=data.get("secondary_started_at"),
                secondary_status=data.get("secondary_status", "stopped"),
                info_screen=data.get("info_screen", False),
                info_manual=data.get("info_manual", False),
            )
        except Exception:  # pragma: no cover - robust gegen defekte Dateien
            pass
    return _state


def save_state(state: PlaybackState) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(asdict(state)), encoding="utf-8")


def set_state(
    current_item: Optional[str],
    status: str,
    *,
    info_screen: bool = False,
    info_manual: bool = False,
    side: str = "primary",
    secondary_item: Optional[str] = None,
    secondary_status: Optional[str] = None,
) -> PlaybackState:
    """Aktualisiert den Wiedergabestatus."""

    with _lock:
        state = load_state()
        now = time.time()
        if side == "secondary":
            state.secondary_item = current_item
            state.secondary_status = status
            state.secondary_started_at = now if current_item else None
        else:
            state.primary_item = current_item
            state.primary_status = status
            state.primary_started_at = now if current_item else None
            if secondary_item is not None or secondary_status is not None:
                state.secondary_item = secondary_item
                state.secondary_status = secondary_status or (
                    "stopped" if secondary_item is None else status
                )
                state.secondary_started_at = now if secondary_item else None
        state.info_screen = info_screen
        state.info_manual = info_manual
        save_state(state)
        return state


def get_state() -> PlaybackState:
    with _lock:
        return load_state()
