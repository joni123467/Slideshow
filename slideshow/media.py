"""Verwaltung von Medienquellen und Playlists."""
from __future__ import annotations

import logging
import io
import mimetypes
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import io
from dataclasses import asdict
from typing import List, Optional, Tuple

from PIL import Image

from .config import (
    AppConfig,
    CACHE_DIR,
    DATA_DIR,
    MediaSource,
    PlaylistItem,
    delete_secret,
    ensure_cache_dir,
    load_secret,
    save_secret,
)

LOGGER = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
IGNORED_EXTENSIONS = {".db", ".ini", ".tmp", ".ds_store"}
CACHEABLE_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_MOUNT_HELPER = BASE_DIR / "scripts" / "mount_smb.sh"
MOUNT_ROOT = (DATA_DIR / "mounts").resolve()


def _paths_equal(left: pathlib.Path, right: pathlib.Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except FileNotFoundError:
        return left.absolute() == right.absolute()


def _unescape_mount_path(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _normalize_subpath(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    sanitized = str(value).replace("\\", "/").strip("/")
    return sanitized or None


def parse_smb_location(raw_path: str) -> tuple[str, str, Optional[str]]:
    """Zerlegt eine SMB-Pfadangabe in Server, Freigabe und Unterordner."""

    if not raw_path:
        raise ValueError("SMB-Pfad darf nicht leer sein")

    cleaned = raw_path.strip()
    if cleaned.lower().startswith("smb://"):
        cleaned = cleaned[6:]
    cleaned = cleaned.lstrip("\\/")
    cleaned = cleaned.replace("\\", "/")
    parts = [part for part in cleaned.split("/") if part]

    if len(parts) < 2:
        raise ValueError("SMB-Pfad muss Server und Freigabe enthalten")

    server = parts[0]
    share = parts[1]
    subpath = "/".join(parts[2:]) if len(parts) > 2 else None
    return server, share, _normalize_subpath(subpath)


class MediaManager:
    def __init__(self, config: AppConfig):
        self.config = config
        helper_path = os.environ.get("SLIDESHOW_MOUNT_HELPER")
        self.mount_helper = pathlib.Path(helper_path) if helper_path else DEFAULT_MOUNT_HELPER
        try:
            MOUNT_ROOT.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            LOGGER.warning("Konnte Mount-Verzeichnis %s nicht anlegen: %s", MOUNT_ROOT, exc)
        ensure_cache_dir()
        self._migrate_mount_points()
        self._ensure_local_directories()

    # Zustandsabfragen -------------------------------------------------
    def _disabled_media_pairs(self) -> set[Tuple[str, str]]:
        pairs: set[Tuple[str, str]] = set()
        entries = getattr(self.config.playback, "disabled_media", []) or []
        for entry in entries:
            source: Optional[str]
            path: Optional[str]
            if isinstance(entry, dict):
                source = entry.get("source")
                path = entry.get("path")
            elif isinstance(entry, PlaylistItem):
                source = entry.source
                path = entry.path
            else:
                source = getattr(entry, "source", None)
                path = getattr(entry, "path", None)
            if source and path:
                pairs.add((str(source), str(path)))
        return pairs

    def disabled_media_keys(self) -> set[str]:
        return {f"{source}|{path}" for source, path in self._disabled_media_pairs()}

    def _relative_from_filesystem(self, source: MediaSource, raw: str) -> Optional[str]:
        if not raw:
            return None
        try:
            path_obj = pathlib.Path(raw)
        except Exception:  # pragma: no cover - defensive
            return None
        try:
            if path_obj.is_absolute():
                relative = path_obj.relative_to(pathlib.Path(source.path))
                normalized = _normalize_subpath(str(relative))
                if not normalized:
                    return None
                configured = _normalize_subpath(source.subpath)
                if configured:
                    conf_parts = [part for part in configured.split("/") if part]
                    rel_parts = [part for part in normalized.split("/") if part]
                    if len(rel_parts) >= len(conf_parts) and [
                        part.lower() for part in rel_parts[: len(conf_parts)]
                    ] == [part.lower() for part in conf_parts]:
                        rel_parts = rel_parts[len(conf_parts) :]
                        normalized = "/".join(rel_parts)
                return normalized or None
        except ValueError:
            return None
        return None

    def _normalize_split_base(self, source: MediaSource, raw: Optional[str]) -> Optional[str]:
        if raw is None:
            return None
        raw_str = str(raw).strip()
        if not raw_str:
            return None
        fs_relative = self._relative_from_filesystem(source, raw_str)
        sanitized = re.sub(r"^smb://", "", raw_str, flags=re.IGNORECASE)
        sanitized = sanitized.replace("\\", "/").strip()
        sanitized = sanitized.strip("/")
        parts = [part for part in sanitized.split("/") if part]
        if parts and ":" in parts[0]:
            parts = parts[1:]
        if source.type == "smb":
            server = str(source.options.get("server") or "").strip().strip("\\/")
            share = str(source.options.get("share") or "").strip().strip("\\/")
            if server and share and len(parts) >= 2:
                if parts[0].lower() == server.lower() and parts[1].lower() == share.lower():
                    parts = parts[2:]
        configured = _normalize_subpath(source.subpath)
        if configured:
            conf_parts = [part for part in configured.split("/") if part]
            if len(parts) >= len(conf_parts) and [
                part.lower() for part in parts[: len(conf_parts)]
            ] == [part.lower() for part in conf_parts]:
                parts = parts[len(conf_parts) :]
        candidate = "/".join(parts)
        if candidate:
            return candidate
        return fs_relative

    def normalize_split_path(self, source_name: Optional[str], raw: Optional[str]) -> str:
        if not raw:
            return ""
        raw_str = str(raw).strip()
        if not raw_str:
            return ""
        source = self.config.get_source(source_name) if source_name else None
        if source:
            normalized = self._normalize_split_base(source, raw_str)
            if normalized:
                return normalized
        cleaned = re.sub(r"^smb://", "", raw_str, flags=re.IGNORECASE)
        cleaned = cleaned.replace("\\", "/").strip("/")
        parts = [part for part in cleaned.split("/") if part]
        if parts and ":" in parts[0]:
            parts = parts[1:]
        cleaned = "/".join(parts)
        return cleaned

    # Initialisierungs-Helfer --------------------------------------------
    def _is_mount_active(self, mount_point: pathlib.Path) -> bool:
        path = pathlib.Path(mount_point)
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            return False
        if os.path.ismount(str(resolved)):
            return True
        try:
            with open("/proc/self/mounts", "r", encoding="utf-8") as handle:
                for line in handle:
                    parts = line.split()
                    if len(parts) >= 2:
                        mount_target = pathlib.Path(_unescape_mount_path(parts[1]))
                        if _paths_equal(mount_target, resolved):
                            return True
        except OSError:
            pass
        return False

    def _ensure_local_directories(self) -> None:
        for source in self.config.media_sources:
            if source.type == "local":
                try:
                    pathlib.Path(source.path).mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    LOGGER.warning("Konnte lokales Verzeichnis %s nicht erstellen: %s", source.path, exc)

    def _slugify(self, name: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")
        return slug or "smb-source"

    def _allocate_mount_point(self, name: str) -> pathlib.Path:
        base_slug = self._slugify(name)
        candidate = MOUNT_ROOT / base_slug
        counter = 2
        existing_paths = {
            pathlib.Path(src.path).expanduser().resolve()
            for src in self.config.media_sources
            if src.type == "smb"
        }
        resolved = candidate.expanduser().resolve()
        while resolved in existing_paths or candidate.exists():
            candidate = MOUNT_ROOT / f"{base_slug}-{counter}"
            counter += 1
            resolved = candidate.expanduser().resolve()
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            # mkdir kann scheitern, der Mount-Helfer legt später erneut an.
            pass
        return resolved

    def _is_writable(self, path: pathlib.Path) -> bool:
        try:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.mkdir(exist_ok=True)
            return os.access(str(path), os.W_OK)
        except OSError:
            return False

    def _migrate_mount_points(self) -> None:
        changed = False
        for source in self.config.media_sources:
            if source.type != "smb":
                continue
            original_path = pathlib.Path(source.path)
            if not original_path.is_absolute():
                continue
            if str(original_path).startswith("/mnt/slideshow"):
                if not original_path.exists() or not os.access(str(original_path.parent), os.W_OK):
                    new_path = self._allocate_mount_point(source.name)
                    LOGGER.info(
                        "Verschiebe Mountpunkt für %s von %s nach %s", source.name, original_path, new_path
                    )
                    source.path = str(new_path)
                    changed = True
        if changed:
            self.config.save()

    def _run_mount_helper(self, *args: str, ignore_busy: bool = False) -> subprocess.CompletedProcess:
        helper = self.mount_helper
        if not helper.exists():
            raise FileNotFoundError(f"Mount-Helfer {helper} nicht gefunden")
        cmd = [str(helper)] + list(args)
        if os.geteuid() != 0:
            sudo = shutil.which("sudo")
            if not sudo:
                raise PermissionError("sudo ist nicht verfügbar, um den Mount-Helfer aufzurufen")
            cmd = [sudo, "-n"] + cmd
        LOGGER.debug("Starte Mount-Helfer: %s", " ".join(shlex.quote(part) for part in cmd))
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            message = stderr or stdout or "unbekannter Fehler"
            if ignore_busy and result.returncode == 16:
                LOGGER.debug(
                    "Mount-Helfer meldete 'busy' (%s), behandle als Erfolg: %s",
                    result.returncode,
                    message,
                )
                return result
            raise RuntimeError(f"Mount-Helfer fehlgeschlagen ({result.returncode}): {message}")
        return result

    # Quellenverwaltung -------------------------------------------------
    def list_sources(self) -> List[MediaSource]:
        return self.config.media_sources

    def add_smb_source(
        self,
        name: str,
        server: Optional[str] = None,
        share: Optional[str] = None,
        *,
        mount_point: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        domain: Optional[str] = None,
        subpath: Optional[str] = None,
        smb_path: Optional[str] = None,
        auto_scan: bool = True,
    ) -> MediaSource:
        if smb_path:
            parsed_server, parsed_share, parsed_subpath = parse_smb_location(smb_path)
            server = server or parsed_server
            share = share or parsed_share
            subpath = subpath or parsed_subpath

        if not server or not share:
            raise ValueError("Server und Freigabe müssen angegeben werden")

        if mount_point:
            mount_path = pathlib.Path(mount_point).expanduser().resolve()
        else:
            mount_path = self._allocate_mount_point(name)
        if not self._is_writable(mount_path):
            raise PermissionError(f"Mount-Ziel {mount_path} ist nicht beschreibbar")
        normalized_subpath = _normalize_subpath(subpath)
        options = {
            "server": server,
            "share": share,
            "username": username,
        }
        if domain:
            options["domain"] = domain
        source = MediaSource(
            name=name,
            type="smb",
            path=str(mount_path),
            options=options,
            auto_scan=auto_scan,
            subpath=normalized_subpath,
        )
        if password:
            save_secret(f"smb:{name}", password)
        self.config.media_sources.append(source)
        self.config.save()
        return source

    def set_auto_scan(self, name: str, enabled: bool) -> MediaSource:
        source = self.config.get_source(name)
        if not source:
            raise ValueError(f"Unbekannte Quelle: {name}")
        if source.auto_scan != enabled:
            source.auto_scan = enabled
            self.config.save()
        return source

    def remove_source(self, name: str) -> None:
        source = self.config.get_source(name)
        if not source:
            raise ValueError(f"Unbekannte Quelle: {name}")
        if source.type == "local":
            raise ValueError("Die lokale Standardquelle kann nicht entfernt werden")
        try:
            self.unmount_source(source)
        except Exception:
            LOGGER.debug("Unmount vor dem Löschen von %s fehlgeschlagen", name)
        mount_path = pathlib.Path(source.path)
        try:
            if mount_path.exists() and mount_path.is_dir():
                if mount_path.resolve().is_relative_to(MOUNT_ROOT):
                    shutil.rmtree(mount_path, ignore_errors=True)
        except Exception as exc:
            LOGGER.debug("Konnte Mount-Verzeichnis %s nicht entfernen: %s", mount_path, exc)
        self.config.media_sources = [src for src in self.config.media_sources if src.name != name]
        delete_secret(f"smb:{name}")
        self.config.save()

    def update_source(
        self,
        name: str,
        *,
        new_name: Optional[str] = None,
        smb_path: Optional[str] = None,
        server: Optional[str] = None,
        share: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        domain: Optional[str] = None,
        subpath: Optional[str] = None,
        auto_scan: Optional[bool] = None,
    ) -> MediaSource:
        source = self.config.get_source(name)
        if not source:
            raise ValueError(f"Unbekannte Quelle: {name}")
        if source.type != "smb":
            raise ValueError("Nur SMB-Quellen können bearbeitet werden")

        target_name = new_name.strip() if new_name else name
        if not target_name:
            raise ValueError("Der Name darf nicht leer sein")
        if target_name != name and self.config.get_source(target_name):
            raise ValueError(f"Eine Quelle mit dem Namen {target_name} existiert bereits")

        parsed_subpath = None
        if smb_path:
            server, share, parsed_subpath = parse_smb_location(smb_path)

        normalized_subpath = _normalize_subpath(subpath or parsed_subpath or source.subpath)

        if target_name != name:
            for item in self.config.playlist:
                if item.source == name:
                    item.source = target_name
            playback = self.config.playback
            if playback.splitscreen_left_source == name:
                playback.splitscreen_left_source = target_name
            if playback.splitscreen_right_source == name:
                playback.splitscreen_right_source = target_name
            secret = load_secret(f"smb:{name}")
            if secret:
                save_secret(f"smb:{target_name}", secret)
            delete_secret(f"smb:{name}")
            for idx, existing in enumerate(self.config.media_sources):
                if existing.name == name:
                    self.config.media_sources[idx].name = target_name
            source = self.config.get_source(target_name)
            if not source:
                raise RuntimeError("Aktualisierte Quelle nicht gefunden")
            name = target_name

        options = dict(source.options)
        if server:
            options["server"] = server
        if share:
            options["share"] = share

        if username is not None:
            username = username or None
            if username:
                options["username"] = username
            else:
                options.pop("username", None)
        if domain is not None:
            domain = domain or None
            if domain:
                options["domain"] = domain
            else:
                options.pop("domain", None)

        if password is not None:
            if password:
                save_secret(f"smb:{name}", password)
            else:
                delete_secret(f"smb:{name}")

        source.options = options
        source.subpath = normalized_subpath
        if auto_scan is not None:
            source.auto_scan = bool(auto_scan)

        self.config.save()
        return source

    def _cache_path(self, source: MediaSource, relative_path: str) -> pathlib.Path:
        return (CACHE_DIR / source.name) / pathlib.Path(relative_path)

    def _should_cache(self, path: pathlib.Path) -> bool:
        return path.suffix.lower() in CACHEABLE_EXTENSIONS

    def _ensure_cached(self, source: MediaSource, path: pathlib.Path, relative_path: str) -> pathlib.Path:
        if source.type == "local" or not self._should_cache(path):
            return path
        cache_target = self._cache_path(source, relative_path)
        try:
            cache_target.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            LOGGER.debug("Konnte Cache-Verzeichnis %s nicht erstellen", cache_target.parent)
            return path
        try:
            if not cache_target.exists() or path.stat().st_mtime > cache_target.stat().st_mtime:
                shutil.copy2(path, cache_target)
        except FileNotFoundError:
            if cache_target.exists():
                return cache_target
        except OSError as exc:
            LOGGER.debug("Konnte %s nicht in den Cache kopieren: %s", path, exc)
            return path
        return cache_target if cache_target.exists() else path

    def resolve_media_path(self, source_name: str, relative_path: str) -> pathlib.Path:
        source = self.config.get_source(source_name)
        if not source:
            raise ValueError(f"Unbekannte Quelle: {source_name}")
        try:
            self.mount_source(source)
        except Exception as exc:
            LOGGER.debug("Mount für %s fehlgeschlagen, nutze ggf. Cache: %s", source_name, exc)
        base = pathlib.Path(source.path).resolve()
        target = (base / pathlib.Path(relative_path)).resolve()
        if base not in target.parents and target != base:
            raise PermissionError("Pfad liegt außerhalb der Quelle")
        if target.exists() and target.is_file():
            return self._ensure_cached(source, target, relative_path)
        cached = self._cache_path(source, relative_path)
        if cached.exists() and cached.is_file():
            return cached
        raise FileNotFoundError(f"Datei {target} nicht gefunden")

    def generate_preview(self, source_name: str, relative_path: str, size: tuple[int, int] = (240, 135)) -> tuple[bytes, str]:
        path = self.resolve_media_path(source_name, relative_path)
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise TypeError("Nur Bilder werden unterstützt")
        try:
            with Image.open(path) as img:  # type: ignore[arg-type]
                img = img.convert("RGB")
                img.thumbnail(size, Image.LANCZOS)
                output = io.BytesIO()
                img.save(output, format="JPEG", quality=85)
        except OSError as exc:
            raise ValueError(f"Konnte Vorschau nicht erzeugen: {exc}") from exc
        return output.getvalue(), "image/jpeg"

    def mount_source(self, source: MediaSource) -> None:
        if source.type != "smb":
            return
        password = load_secret(f"smb:{source.name}")
        mount_point = pathlib.Path(source.path)
        mount_point.mkdir(parents=True, exist_ok=True)
        if self._is_mount_active(mount_point):
            LOGGER.debug("Mountpunkt %s ist bereits aktiv", mount_point)
            return
        uid = os.getuid()
        gid = os.getgid()
        vers = source.options.get("vers", "3.1.1")
        vers_option = vers if isinstance(vers, str) and vers.startswith("vers=") else f"vers={vers}"
        option_parts = ["rw",
            f"uid={uid}",
            f"gid={gid}",
            "file_mode=0775",
            "dir_mode=0775",
            vers_option,
        ]
        username = source.options.get("username")
        if username:
            option_parts.insert(0, f"username={username}")
            option_parts.insert(1, f"password={password or ''}")
        elif password:
            option_parts.insert(0, f"password={password}")
        else:
            option_parts.insert(0, "guest")
        domain = source.options.get("domain")
        if domain:
            option_parts.insert(0, f"domain={domain}")
        extra_options = source.options.get("options") or source.options.get("extra_options")
        if isinstance(extra_options, str) and extra_options.strip():
            option_parts.append(extra_options.strip())
        elif isinstance(extra_options, (list, tuple)):
            option_parts.extend(str(entry) for entry in extra_options if entry)

        options = ",".join(part for part in option_parts if part)
        share = f"//{source.options['server']}/{source.options['share']}"
        LOGGER.info("Mount SMB share %s auf %s", share, mount_point)
        try:
            self._run_mount_helper("mount", share, str(mount_point), options, ignore_busy=True)
        except Exception as exc:
            LOGGER.warning("Mount von %s fehlgeschlagen: %s", share, exc)
            raise

    def unmount_source(self, source: MediaSource) -> None:
        if source.type != "smb":
            return
        try:
            self._run_mount_helper("umount", source.path)
        except Exception as exc:
            LOGGER.debug("Unmount von %s fehlgeschlagen: %s", source.path, exc)

    # Playlistverwaltung ------------------------------------------------
    def list_playlist(self) -> List[PlaylistItem]:
        return self.config.playlist

    def add_to_playlist(self, item: PlaylistItem) -> None:
        detected = self.detect_item_type(pathlib.Path(item.path).name)
        if not detected:
            raise ValueError(f"Datei {item.path} wird nicht unterstützt")
        item.type = detected
        self.config.playlist.append(item)
        self.config.save()

    def remove_from_playlist(self, index: int) -> None:
        if 0 <= index < len(self.config.playlist):
            del self.config.playlist[index]
            self.config.save()

    def detect_item_type(self, path: str) -> Optional[str]:
        ext = pathlib.Path(path).suffix.lower()
        if ext in IGNORED_EXTENSIONS:
            return None
        if ext in IMAGE_EXTENSIONS:
            return "image"
        if ext in VIDEO_EXTENSIONS:
            return "video"
        mime, _ = mimetypes.guess_type(path)
        if mime:
            if mime.startswith("image"):
                return "image"
            if mime.startswith("video"):
                return "video"
        return None

    def scan_directory(self, source: MediaSource, base_path: Optional[str] = None) -> List[PlaylistItem]:
        items: List[PlaylistItem] = []
        source_root = pathlib.Path(source.path)
        subpath = base_path
        if not subpath:
            subpath = source.subpath
        normalized = _normalize_subpath(subpath)
        base = source_root / pathlib.Path(normalized) if normalized else source_root
        if not base.exists():
            LOGGER.warning("Verzeichnis %s existiert nicht", base)
            return []
        if base.is_file():
            item_type = self.detect_item_type(base.name)
            if not item_type:
                return []
            try:
                relative = base.relative_to(source_root)
            except ValueError:
                relative = pathlib.Path(base.name)
            items.append(
                PlaylistItem(
                    source=source.name,
                    path=str(relative),
                    type=item_type,
                )
            )
            return items
        try:
            iterator = base.rglob("*")
        except NotADirectoryError:
            LOGGER.warning("Pfad %s konnte nicht durchsucht werden", base)
            return items
        for file in sorted(iterator):
            if file.is_dir():
                continue
            item_type = self.detect_item_type(file.name)
            if not item_type:
                continue
            try:
                relative = file.relative_to(source_root)
            except ValueError:
                relative = file.relative_to(base)
            items.append(
                PlaylistItem(
                    source=source.name,
                    path=str(relative),
                    type=item_type,
                )
            )
        return items

    def build_playlist(self) -> List[PlaylistItem]:
        disabled = self._disabled_media_pairs()
        manual_items = [
            item for item in self.config.playlist if (item.source, item.path) not in disabled
        ]
        auto_items: List[PlaylistItem] = []
        seen = {(item.source, item.path) for item in manual_items}
        seen.update(disabled)
        for source in self.config.media_sources:
            if not source.auto_scan:
                continue
            try:
                self.mount_source(source)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Konnte Quelle %s nicht mounten: %s", source.name, exc)
                continue
            for item in self.scan_directory(source):
                key = (item.source, item.path)
                if key in seen:
                    continue
                auto_items.append(item)
                seen.add(key)
        auto_items.sort(key=lambda item: (item.source, item.path))
        return manual_items + auto_items

    def refresh_playlist_from_source(self, source_name: str, replace: bool = False) -> None:
        source = self.config.get_source(source_name)
        if not source:
            raise ValueError(f"Unbekannte Quelle: {source_name}")
        self.mount_source(source)
        items = self.scan_directory(source)
        if replace:
            self.config.playlist = [item for item in self.config.playlist if item.source != source_name]
        self.config.playlist.extend(items)
        self.config.save()

    def serialize_playlist(self) -> List[dict]:
        return [asdict(item) for item in self.config.playlist]

    def serialize_sources(self) -> List[dict]:
        return [asdict(source) for source in self.config.media_sources]

    def build_splitscreen_playlists(
        self,
        left_source: Optional[str],
        left_path: str,
        right_source: Optional[str],
        right_path: str,
    ) -> tuple[List[PlaylistItem], List[PlaylistItem]]:
        left_items: List[PlaylistItem] = []
        right_items: List[PlaylistItem] = []
        disabled = self._disabled_media_pairs()

        if left_source:
            source = self.config.get_source(left_source)
            if source:
                try:
                    self.mount_source(source)
                except Exception as exc:  # pragma: no cover - defensive
                    LOGGER.warning("Konnte linke Quelle %s nicht mounten: %s", left_source, exc)
                else:
                    base = self._normalize_split_base(source, left_path)
                    left_items = [
                        item
                        for item in self.scan_directory(source, base)
                        if (item.source, item.path) not in disabled
                    ]
            else:
                LOGGER.warning("Linke Quelle %s unbekannt", left_source)

        if right_source:
            source = self.config.get_source(right_source)
            if source:
                try:
                    self.mount_source(source)
                except Exception as exc:  # pragma: no cover - defensive
                    LOGGER.warning("Konnte rechte Quelle %s nicht mounten: %s", right_source, exc)
                else:
                    base = self._normalize_split_base(source, right_path)
                    right_items = [
                        item
                        for item in self.scan_directory(source, base)
                        if (item.source, item.path) not in disabled
                    ]
            else:
                LOGGER.warning("Rechte Quelle %s unbekannt", right_source)

        return left_items, right_items
