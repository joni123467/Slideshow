"""Konfigurationsverwaltung für die Slideshow."""
from __future__ import annotations

import dataclasses
import io
import json
import logging
import os
import pathlib
import threading
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
CACHE_DIR = DATA_DIR / "cache"
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
        "video_player_args": [],
        "image_viewer_args": [],
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
        "splitscreen_ratio": 50,
        "disabled_media": [],
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
    "ui": {
        "theme": "mid",
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
    video_player_args: List[str]
    image_viewer_args: List[str]
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
    splitscreen_ratio: int
    disabled_media: List[Dict[str, Any]]


@dataclasses.dataclass
class ServerConfig:
    bind: str
    port: int


@dataclasses.dataclass
class UIConfig:
    theme: str


@dataclasses.dataclass
class AppConfig:
    media_sources: List[MediaSource]
    playlist: List[PlaylistItem]
    playback: PlaybackConfig
    network: NetworkConfig
    server: ServerConfig
    ui: UIConfig

    @classmethod
    def load(cls) -> "AppConfig":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_PATH.exists():
            CONFIG_PATH.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False), encoding="utf-8")
        with _lock:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        config = _merge_dict(DEFAULT_CONFIG, raw)
        playback_raw = dict(config["playback"])
        playback_raw.pop("video_backend", None)
        playback_raw.pop("image_backend", None)
        ui_raw = dict(config.get("ui") or {})
        ui_raw.setdefault("theme", DEFAULT_CONFIG["ui"]["theme"])

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
            playback=PlaybackConfig(**playback_raw),
            network=NetworkConfig(**config["network"]),
            server=ServerConfig(**config["server"]),
            ui=UIConfig(**ui_raw),
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
            "ui": dataclasses.asdict(self.ui),
        }
        with _lock:
            CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    def refresh(self) -> "AppConfig":
        """Lädt die Konfiguration erneut von der Festplatte."""

        return self.__class__.load()

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

        self.playback.video_player_args = _normalize_str_list(self.playback.video_player_args)
        self.playback.image_viewer_args = _normalize_str_list(self.playback.image_viewer_args)

        video_cleaned, video_removed = _purge_legacy_mpv_args(self.playback.video_player_args)
        image_cleaned, image_removed = _purge_legacy_mpv_args(self.playback.image_viewer_args)

        changed = False
        if video_removed:
            self.playback.video_player_args = video_cleaned
            changed = True
        if image_removed:
            self.playback.image_viewer_args = image_cleaned
            changed = True

        if changed:
            LOGGER.warning(
                "Entferne veraltete DRM-Argumente aus mpv-Konfiguration (Video: %s, Bilder: %s)",
                video_removed or "keine",
                image_removed or "keine",
            )
            # Änderungen an der Konfiguration dauerhaft speichern, damit sie nicht erneut eingelesen werden.
            self.save()
            changed = False

        transition = (self.playback.transition_type or "none").lower()
        if transition == "slide":
            transition = "slideleft"
        valid_transitions = {
            "none",
            "fade",
            "fadeblack",
            "fadewhite",
            "wipeleft",
            "wiperight",
            "wipeup",
            "wipedown",
            "slideleft",
            "slideright",
            "slideup",
            "slidedown",
        }
        if transition not in valid_transitions:
            transition = "none"
        self.playback.transition_type = transition

        ratio = int(self.playback.splitscreen_ratio or 50)
        ratio = max(10, min(90, ratio))
        if ratio != self.playback.splitscreen_ratio:
            self.playback.splitscreen_ratio = ratio
            changed = True

        allowed_themes = {"light", "mid", "dark"}
        if self.ui.theme not in allowed_themes:
            self.ui.theme = "mid"
            changed = True

        if changed:
            self.save()

        transition = (self.playback.transition_type or "none").lower()
        if transition == "slide":
            transition = "slideleft"
        valid_transitions = {
            "none",
            "fade",
            "fadeblack",
            "fadewhite",
            "wipeleft",
            "wiperight",
            "wipeup",
            "wipedown",
            "slideleft",
            "slideright",
            "slideup",
            "slidedown",
        }
        if transition not in valid_transitions:
            transition = "none"
        self.playback.transition_type = transition


def _normalize_str_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    if isinstance(value, str):
        text = value.strip()
        if text:
            return [text]
    return []


def _purge_legacy_mpv_args(args: List[str]) -> Tuple[List[str], List[str]]:
    """Entfernt Argumente, die ausschließlich für den früheren DRM-Modus benötigt wurden."""

    legacy_single = {
        "--gpu-context=drm",
    }
    legacy_pair_options = {
        "--gpu-context": "drm",
    }
    legacy_prefix_equals = (
        "--drm-mode",
        "--drm-connector",
    )
    legacy_combo = {"--vo=gpu", "--hwdec=auto"}

    cleaned: List[str] = []
    removed: List[str] = []

    i = 0
    while i < len(args):
        arg = args[i]

        if arg in legacy_single:
            removed.append(arg)
        elif any(arg.startswith(prefix + "=") for prefix in legacy_prefix_equals):
            removed.append(arg)
        elif arg in legacy_pair_options:
            expected_value = legacy_pair_options[arg]
            if i + 1 < len(args) and args[i + 1] == expected_value:
                removed.extend([arg, args[i + 1]])
                i += 1
            else:
                # Entferne nur das Flag, wenn der erwartete Wert nicht direkt folgt.
                removed.append(arg)
        elif arg in legacy_prefix_equals:
            removed.append(arg)
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                removed.append(args[i + 1])
                i += 1
        else:
            cleaned.append(arg)
        i += 1

    if legacy_combo.issubset(set(cleaned)):
        combo_removed: List[str] = []
        new_cleaned: List[str] = []
        for item in cleaned:
            if item in legacy_combo:
                combo_removed.append(item)
            else:
                new_cleaned.append(item)
        cleaned = new_cleaned
        removed.extend(combo_removed)

    return cleaned, removed


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


def export_config_bundle(include_secrets: bool = True) -> bytes:
    """Erstellt ein ZIP-Archiv mit der aktuellen Konfiguration."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if CONFIG_PATH.exists():
            archive.writestr("config.yml", CONFIG_PATH.read_bytes())
        if include_secrets and SECRETS_PATH.exists():
            archive.writestr("secrets.json", SECRETS_PATH.read_bytes())
    buffer.seek(0)
    return buffer.getvalue()


def _write_file(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def import_config_bundle(payload: bytes, *, allowed_files: Optional[Iterable[str]] = None) -> AppConfig:
    """Importiert Konfigurationsdateien aus einem ZIP-Archiv oder einer einzelnen YAML-Datei."""

    allowed = set(allowed_files or {"config.yml", "secrets.json"})
    stream = io.BytesIO(payload)
    try:
        with zipfile.ZipFile(stream) as archive:
            members = {name for name in archive.namelist() if name in allowed}
            if not members:
                raise ValueError("Archiv enthält keine unterstützten Konfigurationsdateien")
            for name in members:
                data = archive.read(name)
                if name.endswith("config.yml"):
                    _write_file(CONFIG_PATH, data)
                elif name.endswith("secrets.json"):
                    _write_file(SECRETS_PATH, data)
    except zipfile.BadZipFile:
        # Als reine YAML-Datei behandeln
        try:
            yaml.safe_load(payload.decode("utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("Ungültige Konfigurationsdatei") from exc
        _write_file(CONFIG_PATH, payload)

    return AppConfig.load()


def ensure_cache_dir() -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        LOGGER.debug("Konnte Cache-Verzeichnis nicht erstellen")
