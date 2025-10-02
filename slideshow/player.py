"""Hintergrunddienst für die Medienwiedergabe."""
from __future__ import annotations

import logging
import pathlib
import subprocess
import threading
import time
from typing import Optional

from .config import AppConfig, PlaylistItem
from .media import MediaManager
from .state import set_state
from .system import resolve_hostname, resolve_ip_addresses
from .info import InfoScreen

LOGGER = logging.getLogger(__name__)


class PlayerService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.manager = MediaManager(config)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._reload = threading.Event()
        self._info_manual = threading.Event()
        self._info_screen = InfoScreen()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._reload.clear()
        self._thread = threading.Thread(target=self._run, name="PlayerService", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        set_state(None, "stopped", info_screen=False, info_manual=self._info_manual.is_set())

    def reload(self) -> None:
        self._reload.set()

    def show_info_screen(self, enabled: bool) -> None:
        if enabled:
            self._info_manual.set()
        else:
            self._info_manual.clear()
        self.reload()

    def _run(self) -> None:
        LOGGER.info("Player thread started")
        refresh_interval = max(5, int(self.config.playback.refresh_interval))
        while not self._stop.is_set():
            manual_info = self._info_manual.is_set()
            playlist = self.manager.build_playlist()
            if manual_info or not playlist:
                if self.config.playback.info_screen_enabled:
                    self._display_info_screen(manual=manual_info)
                else:
                    set_state(None, "idle", info_screen=False, info_manual=manual_info)
                    time.sleep(refresh_interval)
                if not manual_info:
                    self._reload.clear()
                continue
            for item in playlist:
                if self._stop.is_set():
                    break
                self._play_item(item)
                if self._reload.is_set():
                    self._reload.clear()
                    break
                if self._info_manual.is_set():
                    break
        LOGGER.info("Player thread stopped")

    def _play_item(self, item: PlaylistItem) -> None:
        source = self.config.get_source(item.source)
        if not source:
            LOGGER.warning("Quelle %s nicht gefunden", item.source)
            return
        base = pathlib.Path(source.path)
        full_path = base / item.path
        if not full_path.exists():
            LOGGER.warning("Datei %s nicht gefunden", full_path)
            return
        set_state(str(full_path), "playing", info_screen=False, info_manual=self._info_manual.is_set())
        if item.type == "video":
            self._play_video(full_path)
        else:
            self._show_image(full_path, duration=item.duration or self.config.playback.image_duration)

    def _play_video(self, path: pathlib.Path) -> None:
        player = self.config.playback.video_player
        LOGGER.info("Play video %s via %s", path, player)
        if player == "omxplayer":
            subprocess.run(["omxplayer", "--no-keys", "--loop", str(path)], check=False)
        else:
            subprocess.run([player, "--fullscreen", "--no-terminal", str(path)], check=False)
        set_state(str(path), "completed", info_screen=False, info_manual=self._info_manual.is_set())

    def _show_image(self, path: pathlib.Path, duration: int, *, update_state: bool = True, end_status: str = "completed") -> None:
        viewer = self.config.playback.image_viewer
        LOGGER.info("Show image %s for %s seconds", path, duration)
        if update_state:
            set_state(str(path), "playing", info_screen=False, info_manual=self._info_manual.is_set())
        if viewer == "feh":
            subprocess.run(
                [viewer, "--fullscreen", "--hide-pointer", "--auto-zoom", "--slideshow-delay", str(duration), str(path)],
                check=False,
            )
        else:
            subprocess.run([viewer, str(path)], check=False)
        time.sleep(duration)
        set_state(str(path), end_status, info_screen=end_status == "info", info_manual=self._info_manual.is_set())

    def _display_info_screen(self, manual: bool) -> None:
        hostname = resolve_hostname()
        addresses = resolve_ip_addresses()
        info_path = self._info_screen.render(hostname=hostname, addresses=addresses, manual=manual)
        set_state(str(info_path), "info", info_screen=True, info_manual=manual or self._info_manual.is_set())
        self._show_image(info_path, max(5, self.config.playback.refresh_interval), update_state=False, end_status="info")
