"""Verwaltung von Medienquellen und Playlists."""
from __future__ import annotations

import logging
import mimetypes
import os
import pathlib
import subprocess
from dataclasses import asdict
from typing import Iterable, List, Optional

from .config import AppConfig, MediaSource, PlaylistItem, load_secret, save_secret

LOGGER = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


class MediaManager:
    def __init__(self, config: AppConfig):
        self.config = config

    # Quellenverwaltung -------------------------------------------------
    def list_sources(self) -> List[MediaSource]:
        return self.config.media_sources

    def add_smb_source(
        self,
        name: str,
        server: str,
        share: str,
        mount_point: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        auto_scan: bool = True,
    ) -> MediaSource:
        mount_point = mount_point or f"/mnt/slideshow/{name}"
        source = MediaSource(
            name=name,
            type="smb",
            path=mount_point,
            options={
                "server": server,
                "share": share,
                "username": username,
            },
            auto_scan=auto_scan,
        )
        if password:
            save_secret(f"smb:{name}", password)
        self.config.media_sources.append(source)
        self.config.save()
        return source

    def mount_source(self, source: MediaSource) -> None:
        if source.type != "smb":
            return
        password = load_secret(f"smb:{source.name}")
        mount_point = pathlib.Path(source.path)
        mount_point.mkdir(parents=True, exist_ok=True)
        uid = os.getuid()
        gid = os.getgid()
        vers = source.options.get("vers", "3.0")
        vers_option = vers if isinstance(vers, str) and vers.startswith("vers=") else f"vers={vers}"
        cmd = [
            "mount", "-t", "cifs",
            f"//{source.options['server']}/{source.options['share']}",
            str(mount_point),
            "-o",
            ",".join(filter(None, [
                f"username={source.options.get('username', '')}",
                f"password={password or ''}",
                "rw",
                f"uid={uid}",
                f"gid={gid}",
                "file_mode=0775",
                "dir_mode=0775",
                vers_option,
            ]))
        ]
        LOGGER.info("Mount SMB share: %s", " ".join(cmd))
        subprocess.run(cmd, check=False)

    def unmount_source(self, source: MediaSource) -> None:
        if source.type != "smb":
            return
        subprocess.run(["umount", source.path], check=False)

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
        base = source_root / base_path if base_path else source_root
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
                    left_items = self.scan_directory(source, left_path or None)
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
                    right_items = self.scan_directory(source, right_path or None)
            else:
                LOGGER.warning("Rechte Quelle %s unbekannt", right_source)

        return left_items, right_items
