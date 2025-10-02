"""Zentraler Statusspeicher."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATE_PATH = DATA_DIR / "state.json"

_lock = threading.Lock()


@dataclass
class PlaybackState:
    current_item: Optional[str]
    started_at: Optional[float]
    status: str
    info_screen: bool
    info_manual: bool


_state = PlaybackState(current_item=None, started_at=None, status="stopped", info_screen=False, info_manual=False)


def load_state() -> PlaybackState:
    global _state
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text("utf-8"))
            _state = PlaybackState(
                current_item=data.get("current_item"),
                started_at=data.get("started_at"),
                status=data.get("status", "stopped"),
                info_screen=data.get("info_screen", False),
                info_manual=data.get("info_manual", False),
            )
        except Exception:
            pass
    return _state


def save_state(state: PlaybackState) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(asdict(state)), encoding="utf-8")


def set_state(current_item: Optional[str], status: str, *, info_screen: bool = False, info_manual: bool = False) -> PlaybackState:
    with _lock:
        state = PlaybackState(
            current_item=current_item,
            started_at=time.time() if current_item else None,
            status=status,
            info_screen=info_screen,
            info_manual=info_manual,
        )
        save_state(state)
        return state


def get_state() -> PlaybackState:
    with _lock:
        return load_state()
