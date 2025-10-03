"""Konfigurationsverwaltung für die Slideshow."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import pathlib
import threading
from typing import Any, Dict, List, Optional

import yaml

LOGGER = logging.getLogger(__name__)
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent


def _determine_data_dir() -> pathlib.Path:
    """Bestimmt ein beschreibbares Datenverzeichnis."""

    env_path = os.environ.get("SLIDESHOW_DATA_DIR")
    candidates = []
    if env_path:
        candidates.append(pathlib.Path(env_path).expanduser())

    default_path = pathlib.Path.home() / ".slideshow"
    candidates.append(default_path)

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        else:
            return candidate

    # Sollte keiner der Kandidaten funktionieren, nutzen wir den Default-Pfad.
    default_path.mkdir(parents=True, exist_ok=True)
    return default_path


DATA_DIR = _determine_data_dir()
CONFIG_PATH = DATA_DIR / "config.yml"
SECRETS_PATH = DATA_DIR / "secrets.json"
DEFAULT_CONFIG = {
    "media_sources": [
        {
            "name": "local",
            "type": "local",
            "path": str((DATA_DIR / "media").resolve()),
            "options": {},
            "auto_scan": True,
            "subpath": None,
        }
    ],
    "playlist": [],
    "playback": {
        "image_duration": 10,
        "video_player": "mpv",
        "image_viewer": "mpv",
        "auto_start": True,
        "refresh_interval": 30,
        "info_screen_enabled": True,
        "image_fit": "contain",
        "image_rotation": 0,
        "transition_type": "none",
        "transition_duration": 1.0,
        "display_resolution": "1920x1080",
        "splitscreen_enabled": False,
        "splitscreen_left_source": None,
        "splitscreen_left_path": "",
        "splitscreen_right_source": None,
        "splitscreen_right_path": "",
    },
    "network": {
        "hostname": None,
        "mode": "dhcp",
        "static": {
            "address": "192.168.0.100/24",
            "router": "192.168.0.1",
            "dns": ["1.1.1.1", "8.8.8.8"],
        },
        "interface": "eth0",
    },
    "server": {
        "bind": "0.0.0.0",
        "port": 8080,
    },
}

_lock = threading.Lock()


@dataclasses.dataclass
class MediaSource:
    name: str
    type: str  # "local" oder "smb"
    path: str
    options: Dict[str, Any]
    auto_scan: bool = False
    subpath: Optional[str] = None


@dataclasses.dataclass
class PlaylistItem:
    source: str
    path: str
    type: str  # "image" oder "video"
    duration: Optional[int] = None


@dataclasses.dataclass
class NetworkConfig:
    hostname: Optional[str]
    mode: str  # dhcp oder static
    interface: str
    static: Dict[str, Any]


@dataclasses.dataclass
class PlaybackConfig:
    image_duration: int
    video_player: str
    image_viewer: str
    auto_start: bool
    refresh_interval: int
    info_screen_enabled: bool
    image_fit: str
    image_rotation: int
    transition_type: str
    transition_duration: float
    display_resolution: str
    splitscreen_enabled: bool
    splitscreen_left_source: Optional[str]
    splitscreen_left_path: str
    splitscreen_right_source: Optional[str]
    splitscreen_right_path: str


@dataclasses.dataclass
class ServerConfig:
    bind: str
    port: int


@dataclasses.dataclass
class AppConfig:
    media_sources: List[MediaSource]
    playlist: List[PlaylistItem]
    playback: PlaybackConfig
    network: NetworkConfig
    server: ServerConfig

    @classmethod
    def load(cls) -> "AppConfig":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_PATH.exists():
            CONFIG_PATH.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False), encoding="utf-8")
        with _lock:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        config = _merge_dict(DEFAULT_CONFIG, raw)
        instance = cls(
            media_sources=[
                MediaSource(
                    name=src.get("name"),
                    type=src.get("type"),
                    path=src.get("path"),
                    options=src.get("options", {}),
                    auto_scan=src.get("auto_scan", False),
                    subpath=src.get("subpath"),
                )
                for src in config["media_sources"]
            ],
            playlist=[PlaylistItem(**item) for item in config["playlist"]],
            playback=PlaybackConfig(**config["playback"]),
            network=NetworkConfig(**config["network"]),
            server=ServerConfig(**config["server"]),
        )
        instance.ensure_local_paths()
        return instance

    def save(self) -> None:
        raw = {
            "media_sources": [dataclasses.asdict(src) for src in self.media_sources],
            "playlist": [dataclasses.asdict(item) for item in self.playlist],
            "playback": dataclasses.asdict(self.playback),
            "network": dataclasses.asdict(self.network),
            "server": dataclasses.asdict(self.server),
        }
        with _lock:
            CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    @property
    def media_root(self) -> pathlib.Path:
        return pathlib.Path(self.media_sources[0].path)

    def get_source(self, name: str) -> Optional[MediaSource]:
        for src in self.media_sources:
            if src.name == name:
                return src
        return None

    # Helpers -------------------------------------------------------------
    def ensure_local_paths(self) -> None:
        for source in self.media_sources:
            if source.type != "local":
                continue
            try:
                pathlib.Path(source.path).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                LOGGER.warning("Konnte lokales Medienverzeichnis %s nicht erstellen: %s", source.path, exc)


def _merge_dict(default: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(default)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(default.get(key), dict):
            result[key] = _merge_dict(default[key], value)
        else:
            result[key] = value
    return result


def save_secret(key: str, value: Any) -> None:
    """Speichert vertrauliche Informationen (z. B. SMB-Passwörter)."""
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SECRETS_PATH.exists():
        secrets = json.loads(SECRETS_PATH.read_text("utf-8"))
    else:
        secrets = {}
    secrets[key] = value
    SECRETS_PATH.write_text(json.dumps(secrets), encoding="utf-8")


def load_secret(key: str, default: Any = None) -> Any:
    if not SECRETS_PATH.exists():
        return default
    secrets = json.loads(SECRETS_PATH.read_text("utf-8"))
    return secrets.get(key, default)


def delete_secret(key: str) -> None:
    if not SECRETS_PATH.exists():
        return
    secrets = json.loads(SECRETS_PATH.read_text("utf-8"))
    if key in secrets:
        del secrets[key]
        SECRETS_PATH.write_text(json.dumps(secrets), encoding="utf-8")
