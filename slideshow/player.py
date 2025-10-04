"""Hintergrunddienst für die Medienwiedergabe."""
from __future__ import annotations

import itertools
import logging
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple

from PIL import Image

from .config import AppConfig, PlaylistItem
from .info import InfoScreen
from .media import MediaManager
from .state import set_state
from .system import resolve_hostname, resolve_ip_addresses
from .mpv_controller import MpvController

LOGGER = logging.getLogger(__name__)


class PlayerService:
    """Steuert die Wiedergabe von Bildern und Videos inklusive Splitscreen."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.manager = MediaManager(config)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._reload = threading.Event()
        self._info_manual = threading.Event()
        self._info_screen = InfoScreen()
        self._split_threads: Dict[str, PlayerService._SplitWorker] = {}
        self._previous_images: Dict[str, Optional[pathlib.Path]] = {
            "primary": None,
            "secondary": None,
        }
        self._temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="slideshow-display-"))
        self._controllers: Dict[str, MpvController] = {}
        self._controller_lock = threading.Lock()
        self._mpv_args = self._collect_mpv_args()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._reload.clear()
        self._thread = threading.Thread(target=self._run, name="PlayerService", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._reload.set()
        self._stop_splitscreen_threads()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self._stop_all_controllers()
        self._cleanup_tempdir()
        info_manual = self._info_manual.is_set()
        set_state(
            None,
            "stopped",
            info_screen=False,
            info_manual=info_manual,
            source=None,
            media_path=None,
            media_type=None,
            preview_path=None,
        )
        set_state(
            None,
            "stopped",
            side="secondary",
            info_screen=False,
            info_manual=info_manual,
            source=None,
            media_path=None,
            media_type=None,
            preview_path=None,
        )

    def reload(self) -> None:
        self._mpv_args = self._collect_mpv_args()
        self._reload.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

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

            if self.config.playback.splitscreen_enabled:
                if manual_info:
                    self._stop_splitscreen_threads()
                    self._stop_controller("secondary")
                    if self.config.playback.info_screen_enabled:
                        self._display_info_screen(manual=True)
                    else:
                        set_state(
                            None,
                            "idle",
                            info_screen=False,
                            info_manual=True,
                            source=None,
                            media_path=None,
                            media_type=None,
                            preview_path=None,
                        )
                        set_state(
                            None,
                            "stopped",
                            side="secondary",
                            info_screen=False,
                            info_manual=True,
                            source=None,
                            media_path=None,
                            media_type=None,
                            preview_path=None,
                        )
                        time.sleep(refresh_interval)
                    continue

                has_content = self._ensure_splitscreen_running()
                if not has_content:
                    if self.config.playback.info_screen_enabled:
                        self._display_info_screen(manual=False)
                    else:
                        set_state(
                            None,
                            "idle",
                            info_screen=False,
                            info_manual=False,
                            source=None,
                            media_path=None,
                            media_type=None,
                            preview_path=None,
                        )
                        set_state(
                            None,
                            "stopped",
                            side="secondary",
                            info_screen=False,
                            info_manual=False,
                            source=None,
                            media_path=None,
                            media_type=None,
                            preview_path=None,
                        )
                        time.sleep(refresh_interval)
                    self._reload.clear()
                    continue

                # Warte auf Reload/Stop, prüfe regelmäßig auf Info-Screen
                if self._reload.wait(timeout=1):
                    self._reload.clear()
                    self._stop_splitscreen_threads()
                continue

            # Einzelbildschirmmodus -------------------------------------
            self._stop_splitscreen_threads()
            self._controller_for_side("primary", None)
            self._stop_controller("secondary")
            playlist = self.manager.build_playlist()
            if manual_info or not playlist:
                if self.config.playback.info_screen_enabled:
                    self._display_info_screen(manual=manual_info)
                else:
                    set_state(
                        None,
                        "idle",
                        info_screen=False,
                        info_manual=manual_info,
                        source=None,
                        media_path=None,
                        media_type=None,
                        preview_path=None,
                    )
                    set_state(
                        None,
                        "stopped",
                        side="secondary",
                        info_screen=False,
                        info_manual=manual_info,
                        source=None,
                        media_path=None,
                        media_type=None,
                        preview_path=None,
                    )
                    time.sleep(refresh_interval)
                if not manual_info:
                    self._reload.clear()
                continue

            for item in playlist:
                if self._stop.is_set() or self._reload.is_set():
                    break
                if self._info_manual.is_set():
                    break
                self._play_item(item)
            self._reload.clear()

        self._stop_splitscreen_threads()
        self._stop_all_controllers()
        self._cleanup_tempdir()
        LOGGER.info("Player thread stopped")

    # Splitscreen ---------------------------------------------------------
    class _SplitWorker(threading.Thread):
        def __init__(
            self,
            service: "PlayerService",
            side: str,
            items: List[PlaylistItem],
            geometry: Optional[str],
        ) -> None:
            super().__init__(daemon=True, name=f"SplitWorker-{side}")
            self.service = service
            self.side = side
            self.geometry = geometry
            self.items = list(items)
            self._stop = threading.Event()

        def stop(self) -> None:
            self._stop.set()

        def run(self) -> None:  # pragma: no cover - Hintergrundthread
            if not self.items:
                state_side = self.service._state_side(self.side)
                set_state(
                    None,
                    "idle",
                    side=state_side,
                    info_screen=False,
                    info_manual=self.service._info_manual.is_set(),
                    source=None,
                    media_path=None,
                    media_type=None,
                    preview_path=None,
                )
                return

            cycle = itertools.cycle(self.items)
            state_side = self.service._state_side(self.side)
            for item in cycle:
                if (
                    self._stop.is_set()
                    or self.service._stop.is_set()
                    or self.service._reload.is_set()
                    or self.service._info_manual.is_set()
                ):
                    break
                self.service._play_item(
                    item,
                    side=state_side,
                    geometry=self.geometry,
                )

            set_state(
                None,
                "idle",
                side=state_side,
                info_screen=False,
                info_manual=self.service._info_manual.is_set(),
                source=None,
                media_path=None,
                media_type=None,
                preview_path=None,
            )

    def _ensure_splitscreen_running(self) -> bool:
        left_items, right_items = self.manager.build_splitscreen_playlists(
            self.config.playback.splitscreen_left_source,
            self.config.playback.splitscreen_left_path,
            self.config.playback.splitscreen_right_source,
            self.config.playback.splitscreen_right_path,
        )
        if not left_items and not right_items:
            self._stop_splitscreen_threads()
            self._stop_controller("primary")
            self._stop_controller("secondary")
            return False

        restart_needed = self._reload.is_set() or any(
            not worker.is_alive() for worker in self._split_threads.values()
        )
        if restart_needed:
            self._stop_splitscreen_threads()

        if not self._split_threads:
            if left_items:
                self._controller_for_side("primary", self._geometry_for_side("left"))
            else:
                self._stop_controller("primary")
            if right_items:
                self._controller_for_side("secondary", self._geometry_for_side("right"))
            else:
                self._stop_controller("secondary")
            if left_items:
                worker = self._SplitWorker(
                    self,
                    "left",
                    left_items,
                    self._geometry_for_side("left"),
                )
                self._split_threads["left"] = worker
                worker.start()
            if right_items:
                worker = self._SplitWorker(
                    self,
                    "right",
                    right_items,
                    self._geometry_for_side("right"),
                )
                self._split_threads["right"] = worker
                worker.start()
            if not left_items:
                set_state(
                    None,
                    "idle",
                    side="primary",
                    info_screen=False,
                    info_manual=self._info_manual.is_set(),
                    source=None,
                    media_path=None,
                    media_type=None,
                    preview_path=None,
                )
            if not right_items:
                set_state(
                    None,
                    "idle",
                    side="secondary",
                    info_screen=False,
                    info_manual=self._info_manual.is_set(),
                    source=None,
                    media_path=None,
                    media_type=None,
                    preview_path=None,
                )
        return True

    def _stop_splitscreen_threads(self) -> None:
        if not self._split_threads:
            return

        for worker in self._split_threads.values():
            worker.stop()
        for worker in self._split_threads.values():
            worker.join(timeout=2)
        LOGGER.debug("Splitscreen-Threads gestoppt")
        self._split_threads.clear()
        self._previous_images["primary"] = None
        self._previous_images["secondary"] = None

    def _uses_mpv(self) -> bool:
        return (
            self.config.playback.video_player == "mpv"
            or self.config.playback.image_viewer == "mpv"
        )

    def _controller_for_side(
        self, side: str, geometry: Optional[str]
    ) -> Optional[MpvController]:
        if not self._uses_mpv():
            return None
        to_stop: Optional[MpvController] = None
        created = False
        with self._controller_lock:
            controller = self._controllers.get(side)
            if controller and controller.geometry != geometry:
                to_stop = controller
                self._controllers.pop(side, None)
                controller = None
                if side in self._previous_images:
                    self._previous_images[side] = None
            if controller is None:
                controller = MpvController(geometry=geometry, extra_args=self._mpv_args)
                self._controllers[side] = controller
                created = True
        if to_stop:
            to_stop.stop()
        if created:
            if not controller.start():
                LOGGER.error("Konnte mpv-Controller für %s nicht starten", side)
                with self._controller_lock:
                    stored = self._controllers.get(side)
                    if stored is controller:
                        self._controllers.pop(side, None)
                return None
        else:
            controller.ensure_running()
        return controller

    def _stop_controller(self, side: str) -> None:
        with self._controller_lock:
            controller = self._controllers.pop(side, None)
        if controller:
            controller.stop()
        if side in self._previous_images:
            self._previous_images[side] = None

    def _stop_all_controllers(self) -> None:
        with self._controller_lock:
            controllers = list(self._controllers.values())
            self._controllers.clear()
        for controller in controllers:
            controller.stop()
        self._previous_images["primary"] = None
        self._previous_images["secondary"] = None

    def _state_side(self, side: str) -> str:
        return "primary" if side == "left" else "secondary"

    def _geometry_for_side(self, side: str) -> Optional[str]:
        width, height = self._parse_resolution()
        if side not in {"left", "right"}:
            return None
        ratio = int(self.config.playback.splitscreen_ratio or 50)
        ratio = max(10, min(90, ratio))
        left_width = max(1, (width * ratio) // 100)
        right_width = max(1, width - left_width)
        if side == "left":
            return f"{left_width}x{height}+0+0"
        return f"{right_width}x{height}+{left_width}+0"

    # Wiedergabe ----------------------------------------------------------
    def _play_item(
        self,
        item: PlaylistItem,
        *,
        side: str = "primary",
        geometry: Optional[str] = None,
    ) -> None:
        source = self.config.get_source(item.source)
        if not source:
            LOGGER.warning("Quelle %s nicht gefunden", item.source)
            return
        try:
            full_path = self.manager.resolve_media_path(item.source, item.path)
        except (FileNotFoundError, PermissionError, ValueError) as exc:
            LOGGER.warning("Datei %s/%s nicht verfügbar: %s", item.source, item.path, exc)
            return
        display_label = f"{item.source}/{item.path}"
        if item.type == "video":
            self._play_video(
                full_path,
                side=side,
                geometry=geometry,
                source=item.source,
                media_path=item.path,
                display_label=display_label,
            )
        else:
            duration = item.duration or self.config.playback.image_duration
            self._show_image(
                full_path,
                duration,
                side=side,
                geometry=geometry,
                source=item.source,
                media_path=item.path,
                display_label=display_label,
                media_type=item.type,
            )

    def _play_video(
        self,
        path: pathlib.Path,
        *,
        side: str = "primary",
        geometry: Optional[str] = None,
        source: Optional[str] = None,
        media_path: Optional[str] = None,
        display_label: Optional[str] = None,
    ) -> None:
        player = self.config.playback.video_player
        LOGGER.info("Play video %s via %s", path, player)
        clear_secondary = side == "primary" and not self.config.playback.splitscreen_enabled
        label = display_label or str(path)
        set_state(
            label,
            "playing",
            side=side,
            info_screen=False,
            info_manual=self._info_manual.is_set(),
            source=source,
            media_path=media_path,
            media_type="video",
            preview_path=str(path),
        )
        if clear_secondary:
            set_state(
                None,
                "stopped",
                side="secondary",
                info_screen=False,
                info_manual=self._info_manual.is_set(),
                source=None,
                media_path=None,
                media_type=None,
                preview_path=None,
            )
        if player == "mpv":
            controller = self._controller_for_side(side, geometry)
            if not controller:
                LOGGER.error("mpv-Controller für %s nicht verfügbar", side)
            else:
                if controller.load_file(path):
                    finished = controller.wait_until_idle(self._should_interrupt)
                    if not finished and self._should_interrupt():
                        controller.stop_playback()
        elif player == "omxplayer":
            args = ["omxplayer", "--no-keys", str(path)]
            subprocess.run(args, check=False)
        else:
            subprocess.run([player, str(path)], check=False)
        set_state(
            label,
            "completed",
            side=side,
            info_screen=False,
            info_manual=self._info_manual.is_set(),
            source=source,
            media_path=media_path,
            media_type="video",
            preview_path=str(path),
        )

    def _show_image(
        self,
        path: pathlib.Path,
        duration: int,
        *,
        side: str = "primary",
        geometry: Optional[str] = None,
        end_status: str = "completed",
        source: Optional[str] = None,
        media_path: Optional[str] = None,
        display_label: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> None:
        requested_duration = max(1.0, float(duration))
        processed_path, _ = self._prepare_image(path, side)

        previous = self._previous_images.get(side)
        transition_duration, transition_file = self._play_transition(
            previous, processed_path, side=side, geometry=geometry
        )
        display_duration = requested_duration
        if transition_duration > 0:
            display_duration = max(1.0, requested_duration - transition_duration)
        if previous and previous != processed_path and self._is_temp_file(previous):
            self._safe_remove(previous)

        clear_secondary = side == "primary" and not self.config.playback.splitscreen_enabled
        label = display_label or str(path)
        media_kind = media_type or ("info" if end_status == "info" else "image")
        set_state(
            label,
            "playing",
            side=side,
            info_screen=False,
            info_manual=self._info_manual.is_set(),
            source=source,
            media_path=media_path,
            media_type=media_kind,
            preview_path=str(processed_path),
        )
        if clear_secondary:
            set_state(
                None,
                "stopped",
                side="secondary",
                info_screen=False,
                info_manual=self._info_manual.is_set(),
                source=None,
                media_path=None,
                media_type=None,
                preview_path=None,
            )

        viewer = self.config.playback.image_viewer
        if viewer == "mpv":
            controller = self._controller_for_side(side, geometry)
            if not controller:
                LOGGER.error("mpv-Controller für %s nicht verfügbar", side)
            else:
                controller.set_property("image-display-duration", display_duration)
                hold_for_info = media_kind == "info"
                manual_interrupts_allowed = not hold_for_info
                if controller.load_file(processed_path):
                    if transition_file:
                        self._safe_remove(transition_file)
                    end_time = time.time() + display_duration
                    interrupted = False
                    while time.time() < end_time:
                        if (
                            self._stop.is_set()
                            or self._reload.is_set()
                            or (
                                manual_interrupts_allowed
                                and self._info_manual.is_set()
                            )
                        ):
                            controller.stop_playback()
                            interrupted = True
                            break
                        time.sleep(0.2)
                    if hold_for_info and not interrupted:
                        try:
                            controller.set_property("pause", True)
                        except Exception:
                            LOGGER.debug("Konnte mpv nicht pausieren, um Infobildschirm zu halten")
                elif transition_file:
                    self._safe_remove(transition_file)
        elif viewer == "feh":
            cmd = [
                viewer,
                "--hide-pointer",
                "--fullscreen",
                "--auto-zoom",
                "--slideshow-delay",
                str(display_duration),
                "--cycle-once",
                str(processed_path),
            ]
            subprocess.run(cmd, check=False)
            if transition_file:
                self._safe_remove(transition_file)
        else:
            subprocess.run([viewer, str(processed_path)], check=False)
            if transition_file:
                self._safe_remove(transition_file)
        set_state(
            label,
            end_status,
            side=side,
            info_screen=end_status == "info",
            info_manual=self._info_manual.is_set(),
            source=source,
            media_path=media_path,
            media_type=media_kind,
            preview_path=str(processed_path),
        )

        if processed_path.exists() and self._is_temp_file(processed_path):
            self._previous_images[side] = processed_path
        else:
            self._previous_images[side] = path

    def _play_transition(
        self,
        previous: Optional[pathlib.Path],
        current: pathlib.Path,
        *,
        side: str,
        geometry: Optional[str],
    ) -> Tuple[float, Optional[pathlib.Path]]:
        transition_type = (self.config.playback.transition_type or "none").lower()
        if transition_type == "none" or not previous or not previous.exists():
            return 0.0, None
        duration = max(0.2, float(self.config.playback.transition_duration))
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            LOGGER.warning("Übergang %s übersprungen, ffmpeg nicht gefunden", transition_type)
            return 0.0, None

        transition_map = {
            "fade": "fade",
            "fadeblack": "fadeblack",
            "fadewhite": "fadewhite",
            "wipeleft": "wipeleft",
            "wiperight": "wiperight",
            "wipeup": "wipeup",
            "wipedown": "wipedown",
            "slideleft": "slideleft",
            "slideright": "slideright",
            "slideup": "slideup",
            "slidedown": "slidedown",
        }
        transition = transition_map.get(transition_type)
        if not transition:
            LOGGER.warning("Unbekannter Übergangstyp: %s", transition_type)
            return 0.0, None

        output = self._temp_dir / f"transition-{side}.mp4"
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-t",
            f"{duration}",
            "-i",
            str(previous),
            "-loop",
            "1",
            "-t",
            f"{duration}",
            "-i",
            str(current),
            "-filter_complex",
            f"xfade=transition={transition}:duration={duration}:offset=0",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0 or not output.exists():
            LOGGER.warning("ffmpeg konnte Übergang nicht erzeugen")
            return 0.0, None

        controller = None
        if self._uses_mpv():
            controller = self._controller_for_side(side, geometry)
        if controller and controller.load_file(output):
            finished = controller.wait_until_idle(self._should_interrupt)
            if not finished and self._should_interrupt():
                controller.stop_playback()
                self._safe_remove(output)
                return 0.0, None
            return duration, output
        else:
            viewer = self.config.playback.video_player
            cmd = [
                "mpv" if viewer != "mpv" else viewer,
                "--no-terminal",
                "--quiet",
                "--loop-file=no",
                "--force-window=yes",
                "--keep-open=no",
            ]
            cmd.extend(self._mpv_args)
            cmd.extend(self._mpv_geometry_args(geometry))
            cmd.append(str(output))
            result = subprocess.run(cmd, check=False)
        self._safe_remove(output)
        return (duration, None) if result.returncode == 0 else (0.0, None)

    # Hilfsfunktionen ----------------------------------------------------
    def _prepare_image(self, path: pathlib.Path, side: str) -> Tuple[pathlib.Path, bool]:
        fit_mode = (self.config.playback.image_fit or "contain").lower()
        rotation = int(self.config.playback.image_rotation) % 360
        target_width, target_height = self._target_size(side)

        self._temp_dir.mkdir(parents=True, exist_ok=True)
        needs_processing = rotation != 0 or fit_mode in {"contain", "stretch"}
        image_path = path
        if not needs_processing and fit_mode == "original":
            return path, False

        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                if rotation:
                    img = img.rotate(-rotation, expand=True)
                if fit_mode == "stretch":
                    img = img.resize((target_width, target_height), Image.LANCZOS)
                elif fit_mode == "contain":
                    background = Image.new("RGB", (target_width, target_height), color="black")
                    img.thumbnail((target_width, target_height), Image.LANCZOS)
                    offset = (
                        max(0, (target_width - img.width) // 2),
                        max(0, (target_height - img.height) // 2),
                    )
                    background.paste(img, offset)
                    img = background
                # original mit Rotation -> keine weitere Anpassung
                output = self._temp_dir / f"frame-{side}-{int(time.time()*1000)}.jpg"
                img.save(output, format="JPEG", quality=90)
                image_path = output
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Konnte Bild %s nicht vorbereiten: %s", path, exc)
            return path, False

        return image_path, True

    def _target_size(self, side: str) -> Tuple[int, int]:
        width, height = self._parse_resolution()
        if self.config.playback.splitscreen_enabled and side in {"primary", "secondary"}:
            ratio = int(self.config.playback.splitscreen_ratio or 50)
            ratio = max(10, min(90, ratio))
            left_width = max(1, (width * ratio) // 100)
            right_width = max(1, width - left_width)
            if side == "primary":
                return left_width, height
            return right_width, height
        return width, height

    def _parse_resolution(self) -> Tuple[int, int]:
        value = self.config.playback.display_resolution or "1920x1080"
        try:
            width_str, height_str = value.lower().split("x", 1)
            width = int(width_str)
            height = int(height_str)
        except Exception:
            width, height = 1920, 1080
        return max(320, width), max(240, height)

    def _is_temp_file(self, path: pathlib.Path) -> bool:
        try:
            return self._temp_dir in path.parents or path == self._temp_dir
        except Exception:
            return False

    def _safe_remove(self, path: pathlib.Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            LOGGER.debug("Konnte temporäre Datei %s nicht löschen", path)

    def _cleanup_tempdir(self) -> None:
        if self._temp_dir.exists():
            try:
                shutil.rmtree(self._temp_dir)
            except Exception:
                LOGGER.debug("Konnte temporäres Verzeichnis nicht entfernen")

    def _mpv_geometry_args(self, geometry: Optional[str]) -> List[str]:
        args: List[str] = ["--force-window=yes"]
        if geometry:
            args.append(f"--geometry={geometry}")
        else:
            args.append("--fullscreen")
        return args

    def _collect_mpv_args(self) -> List[str]:
        unique_args: List[str] = []
        seen = set()
        for arg in itertools.chain(
            self.config.playback.video_player_args,
            self.config.playback.image_viewer_args,
        ):
            if arg not in seen:
                seen.add(arg)
                unique_args.append(arg)
        return unique_args

    def _should_interrupt(self) -> bool:
        return (
            self._stop.is_set()
            or self._reload.is_set()
            or self._info_manual.is_set()
        )

    def _display_info_screen(self, manual: bool) -> None:
        hostname = resolve_hostname()
        addresses = resolve_ip_addresses()
        network = self.config.network
        playback = self.config.playback
        details = []
        if network.interface:
            details.append(f"Netzwerkinterface: {network.interface}")
        mode = (network.mode or "dhcp").lower()
        if mode == "static":
            address = (network.static or {}).get("address") if network.static else None
            router = (network.static or {}).get("router") if network.static else None
            details.append(
                "Netzwerkmodus: Statisch" + (f" ({address})" if address else "")
            )
            if router:
                details.append(f"Gateway: {router}")
        else:
            details.append("Netzwerkmodus: DHCP")
        details.append(f"Medienverzeichnis: {self.config.media_root}")
        details.append(
            f"Automatischer Start: {'Ja' if playback.auto_start else 'Nein'}"
        )
        details.append(f"Displayauflösung: {playback.display_resolution}")
        info_path = self._info_screen.render(
            hostname=hostname,
            addresses=addresses,
            manual=manual,
            details=details,
        )
        info_manual_flag = manual or self._info_manual.is_set()
        label = f"system/{info_path.name}"
        set_state(
            label,
            "info",
            side="primary",
            info_screen=True,
            info_manual=info_manual_flag,
            source="system",
            media_path=info_path.name,
            media_type="info",
            preview_path=str(info_path),
        )
        set_state(
            None,
            "stopped",
            side="secondary",
            info_screen=True,
            info_manual=info_manual_flag,
            source=None,
            media_path=None,
            media_type=None,
            preview_path=None,
        )
        self._show_image(
            info_path,
            max(5, self.config.playback.refresh_interval),
            side="primary",
            geometry=None,
            end_status="info",
            source="system",
            media_path=info_path.name,
            display_label=label,
            media_type="info",
        )
