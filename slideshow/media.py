"""Verwaltung von Medienquellen und Playlists."""
from __future__ import annotations

import logging
import mimetypes
import os
import pathlib
import re
import shlex
import shutil
import subprocess
from dataclasses import asdict
from typing import List, Optional

from .config import (
    AppConfig,
    DATA_DIR,
    MediaSource,
    PlaylistItem,
    delete_secret,
    load_secret,
    save_secret,
)

LOGGER = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_MOUNT_HELPER = BASE_DIR / "scripts" / "mount_smb.sh"
MOUNT_ROOT = (DATA_DIR / "mounts").resolve()


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
        self._migrate_mount_points()
        self._ensure_local_directories()

    # Initialisierungs-Helfer --------------------------------------------
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

    def _run_mount_helper(self, *args: str) -> subprocess.CompletedProcess:
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
        self.config.media_sources = [src for src in self.config.media_sources if src.name != name]
        delete_secret(f"smb:{name}")
        self.config.save()

    def mount_source(self, source: MediaSource) -> None:
        if source.type != "smb":
            return
        password = load_secret(f"smb:{source.name}")
        mount_point = pathlib.Path(source.path)
        mount_point.mkdir(parents=True, exist_ok=True)
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
            self._run_mount_helper("mount", share, str(mount_point), options)
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
        self.config.playlist.append(item)
        self.config.save()

    def remove_from_playlist(self, index: int) -> None:
        if 0 <= index < len(self.config.playlist):
            del self.config.playlist[index]
            self.config.save()

    def detect_item_type(self, path: str) -> str:
        ext = pathlib.Path(path).suffix.lower()
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
        return "image"

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
        for file in sorted(base.rglob("*")):
            if file.is_dir():
                continue
            item_type = self.detect_item_type(file.name)
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
        manual_items = list(self.config.playlist)
        auto_items: List[PlaylistItem] = []
        seen = {(item.source, item.path) for item in manual_items}
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

        if left_source:
            source = self.config.get_source(left_source)
            if source:
                try:
                    self.mount_source(source)
                except Exception as exc:  # pragma: no cover - defensive
                    LOGGER.warning("Konnte linke Quelle %s nicht mounten: %s", left_source, exc)
                else:
                    base = left_path or None
                    if base and source.subpath:
                        base = "/".join(
                            part
                            for part in (
                                _normalize_subpath(source.subpath),
                                _normalize_subpath(base),
                            )
                            if part
                        )
                    left_items = self.scan_directory(source, base)
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
                    base = right_path or None
                    if base and source.subpath:
                        base = "/".join(
                            part
                            for part in (
                                _normalize_subpath(source.subpath),
                                _normalize_subpath(base),
                            )
                            if part
                        )
                    right_items = self.scan_directory(source, base)
            else:
                LOGGER.warning("Rechte Quelle %s unbekannt", right_source)

        return left_items, right_items
