"""Hilfsmodul zur Steuerung einer dauerhaften mpv-Instanz."""
from __future__ import annotations

import json
import logging
import os
import pathlib
import socket
import subprocess
import tempfile
import threading
import time
from typing import Iterable, Optional

LOGGER = logging.getLogger(__name__)


class MpvController:
    """Kapselt die Kommunikation mit einer persistenten mpv-Instanz."""

    def __init__(
        self,
        *,
        geometry: Optional[str] = None,
        extra_args: Optional[Iterable[str]] = None,
        binary: str = "mpv",
    ) -> None:
        self.geometry = geometry
        self.binary = binary
        self._extra_args = list(extra_args or [])
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._socket_dir: Optional[pathlib.Path] = None
        self._socket_path: Optional[pathlib.Path] = None
        self._lock = threading.Lock()

    # Lebenszyklus -----------------------------------------------------
    def start(self) -> bool:
        """Startet mpv, sofern noch nicht aktiv."""
        with self._lock:
            if self._process and self._process.poll() is None:
                return True
            self._cleanup_socket()
            try:
                self._socket_dir = pathlib.Path(
                    tempfile.mkdtemp(prefix="slideshow-mpv-")
                )
                self._socket_path = self._socket_dir / "socket"
            except OSError as exc:
                LOGGER.error("Konnte IPC-Socket nicht erstellen: %s", exc)
                return False

            cmd = [
                self.binary,
                "--no-terminal",
                "--quiet",
                "--idle=yes",
                "--force-window=yes",
                "--keep-open=yes",
                f"--input-ipc-server={self._socket_path}",
            ]
            if self.geometry:
                cmd.append(f"--geometry={self.geometry}")
            else:
                cmd.append("--fullscreen")
            cmd.extend(self._extra_args)
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
            except (FileNotFoundError, OSError) as exc:
                LOGGER.error("Konnte mpv nicht starten: %s", exc)
                self._process = None
                self._cleanup_socket()
                return False

        # Warten bis der Socket bereitsteht
        return self._wait_for_socket()

    def ensure_running(self) -> bool:
        if self._process and self._process.poll() is None:
            return True
        return self.start()

    def stop(self) -> None:
        with self._lock:
            if not self._process:
                self._cleanup_socket()
                return
            if self._process.poll() is None:
                try:
                    self._command_no_lock(["quit"])
                except Exception:
                    # Ignorieren und hart stoppen
                    pass
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                        self._process.wait(timeout=3)
            self._process = None
            self._cleanup_socket()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # Befehle ----------------------------------------------------------
    def load_file(self, path: pathlib.Path) -> bool:
        if not self.ensure_running():
            return False
        response = self._command(["loadfile", str(path), "replace"])
        if isinstance(response, dict) and response.get("error") == "success":
            # Nach einem erfolgreichen Load sicherstellen, dass die Instanz
            # nicht im Pausenmodus verharrt.
            self._command(["set_property", "pause", False])
            return True
        return False

    def stop_playback(self) -> None:
        self._command(["stop"])

    def set_property(self, name: str, value: object) -> None:
        self._command(["set_property", name, value])

    def is_idle(self) -> bool:
        response = self._command(["get_property", "idle-active"])
        if isinstance(response, dict):
            return response.get("error") == "success" and bool(response.get("data"))
        return False

    def wait_until_idle(self, should_abort) -> bool:
        """Wartet bis mpv in den Idle-Zustand zurückkehrt.

        :param should_abort: Callable ohne Argumente, das bei Abbruch True liefert.
        :returns: True falls die Wiedergabe normal beendet wurde, sonst False.
        """
        while True:
            if should_abort():
                return False
            if not self.is_running():
                return True
            if self.is_idle():
                return True
            if self._get_property_bool("eof-reached"):
                # EOF erreicht – Wiedergabe stoppen, um den Zustand zurückzusetzen.
                self.stop_playback()
                return True
            if self._get_property_bool("pause"):
                # Bei aktivem keep-open signalisiert pause=True einen Abschluss.
                return True
            time.sleep(0.2)

    # Interne Helfer ---------------------------------------------------
    def _command(self, payload) -> Optional[dict]:
        with self._lock:
            return self._command_no_lock(payload)

    def _command_no_lock(self, payload) -> Optional[dict]:
        if not self._socket_path:
            return None
        if not self._socket_path.exists():
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.connect(os.fspath(self._socket_path))
                message = json.dumps({"command": payload}).encode("utf-8") + b"\n"
                conn.sendall(message)
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
        except OSError as exc:
            LOGGER.debug("Fehler bei mpv-Kommunikation: %s", exc)
            return None
        if not data:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            LOGGER.debug("Ungültige mpv-Antwort: %s", data)
            return None

    def _get_property_bool(self, name: str) -> bool:
        response = self._command(["get_property", name])
        if isinstance(response, dict) and response.get("error") == "success":
            return bool(response.get("data"))
        return False

    def _wait_for_socket(self) -> bool:
        timeout = time.time() + 5
        while time.time() < timeout:
            if self._socket_path and self._socket_path.exists():
                return True
            if self._process and self._process.poll() is not None:
                return False
            time.sleep(0.1)
        LOGGER.error("mpv-IPC-Socket wurde nicht erstellt")
        return False

    def _cleanup_socket(self) -> None:
        if self._socket_path and self._socket_path.exists():
            try:
                self._socket_path.unlink()
            except OSError:
                pass
        if self._socket_dir and self._socket_dir.exists():
            try:
                self._socket_dir.rmdir()
            except OSError:
                # Verzeichnis evtl. nicht leer
                try:
                    for child in self._socket_dir.iterdir():
                        child.unlink()
                    self._socket_dir.rmdir()
                except OSError:
                    pass
        self._socket_path = None
        self._socket_dir = None
