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
    primary_source: Optional[str]
    primary_media_path: Optional[str]
    primary_media_type: Optional[str]
    primary_preview: Optional[str]
    secondary_item: Optional[str]
    secondary_started_at: Optional[float]
    secondary_status: str
    secondary_source: Optional[str]
    secondary_media_path: Optional[str]
    secondary_media_type: Optional[str]
    secondary_preview: Optional[str]
    info_screen: bool
    info_manual: bool


_state = PlaybackState(
    primary_item=None,
    primary_started_at=None,
    primary_status="stopped",
    primary_source=None,
    primary_media_path=None,
    primary_media_type=None,
    primary_preview=None,
    secondary_item=None,
    secondary_started_at=None,
    secondary_status="stopped",
    secondary_source=None,
    secondary_media_path=None,
    secondary_media_type=None,
    secondary_preview=None,
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
                primary_source=data.get("primary_source"),
                primary_media_path=data.get("primary_media_path"),
                primary_media_type=data.get("primary_media_type"),
                primary_preview=data.get("primary_preview"),
                secondary_item=data.get("secondary_item"),
                secondary_started_at=data.get("secondary_started_at"),
                secondary_status=data.get("secondary_status", "stopped"),
                secondary_source=data.get("secondary_source"),
                secondary_media_path=data.get("secondary_media_path"),
                secondary_media_type=data.get("secondary_media_type"),
                secondary_preview=data.get("secondary_preview"),
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
    source: Optional[str] = None,
    media_path: Optional[str] = None,
    media_type: Optional[str] = None,
    preview_path: Optional[str] = None,
) -> PlaybackState:
    """Aktualisiert den Wiedergabestatus."""

    with _lock:
        state = load_state()
        now = time.time()
        if side == "secondary":
            state.secondary_item = current_item
            state.secondary_status = status
            state.secondary_started_at = now if current_item else None
            if current_item is None:
                state.secondary_source = None
                state.secondary_media_path = None
                state.secondary_media_type = None
                state.secondary_preview = None
            else:
                if source is not None:
                    state.secondary_source = source
                if media_path is not None:
                    state.secondary_media_path = media_path
                if media_type is not None:
                    state.secondary_media_type = media_type
                if preview_path is not None:
                    state.secondary_preview = preview_path
        else:
            state.primary_item = current_item
            state.primary_status = status
            state.primary_started_at = now if current_item else None
            if current_item is None:
                state.primary_source = None
                state.primary_media_path = None
                state.primary_media_type = None
                state.primary_preview = None
            else:
                if source is not None:
                    state.primary_source = source
                if media_path is not None:
                    state.primary_media_path = media_path
                if media_type is not None:
                    state.primary_media_type = media_type
                if preview_path is not None:
                    state.primary_preview = preview_path
        state.info_screen = info_screen
        state.info_manual = info_manual
        save_state(state)
        return state


def get_state() -> PlaybackState:
    with _lock:
        return load_state()


def set_manual_flag(enabled: bool) -> PlaybackState:
    """Merkt sich, ob der Infobildschirm manuell aktiviert wurde."""

    with _lock:
        state = load_state()
        state.info_manual = enabled
        if enabled:
            state.info_screen = True
        save_state(state)
        return state
