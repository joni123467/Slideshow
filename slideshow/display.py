"""Hilfsfunktionen zur Erkennung des Anzeigestatus."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from typing import Callable, Optional


LOGGER = logging.getLogger(__name__)


class DisplayPowerMonitor:
    """Überwacht den Stromzustand der Hauptanzeige."""

    def __init__(
        self,
        *,
        display: Optional[str] = None,
        poll_interval: float = 5.0,
    ) -> None:
        self.display = display or os.environ.get("DISPLAY", ":0")
        self.poll_interval = max(1.0, float(poll_interval))
        self._callbacks: list[Callable[[bool], None]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state: bool = True
        self._lock = threading.Lock()

    def start(self, callback: Optional[Callable[[bool], None]] = None) -> bool:
        """Startet den Hintergrund-Thread und liefert den aktuellen Zustand."""

        if callback:
            with self._lock:
                if callback not in self._callbacks:
                    self._callbacks.append(callback)

        with self._lock:
            if self._thread and self._thread.is_alive():
                state = self._probe_state()
                if state is not None and state != self._state:
                    self._state = state
                    self._notify(state, force=True)
                return self._state

            self._stop.clear()
            initial_state = self._probe_state()
            if initial_state is None:
                initial_state = True
            self._state = initial_state
            self._thread = threading.Thread(
                target=self._run,
                name="DisplayPowerMonitor",
                daemon=True,
            )
            self._thread.start()

        self._notify(self._state, force=True)
        return self._state

    def stop(self) -> None:
        """Beendet die Überwachung."""

        self._stop.set()
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread:
            thread.join(timeout=self.poll_interval * 2)

    # Intern ---------------------------------------------------------
    def _run(self) -> None:
        """Hintergrundschleife, die den Status zyklisch überprüft."""

        while not self._stop.wait(self.poll_interval):
            state = self._probe_state()
            if state is None:
                continue
            if state != self._state:
                LOGGER.info("Erkannter Anzeigestatus geändert: %s", "ein" if state else "aus")
                self._state = state
                self._notify(state)

    def _notify(self, state: bool, *, force: bool = False) -> None:
        callbacks: list[Callable[[bool], None]]
        with self._lock:
            callbacks = list(self._callbacks)
        if not callbacks and not force:
            return
        for callback in callbacks:
            try:
                callback(state)
            except Exception:  # pragma: no cover - defensive logging
                LOGGER.exception("DisplayPower-Callback schlug fehl")

    def _probe_state(self) -> Optional[bool]:
        """Ermittelt den aktuellen Status der Anzeige."""

        detectors = (
            self._probe_vcgencmd,
            self._probe_tvservice,
            self._probe_xset,
        )
        for detector in detectors:
            try:
                result = detector()
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.debug("%s fehlgeschlagen: %s", detector.__name__, exc)
                continue
            if result is not None:
                return result
        return None

    def _probe_vcgencmd(self) -> Optional[bool]:
        binary = shutil.which("vcgencmd")
        if not binary:
            return None
        output = subprocess.check_output([binary, "display_power"], text=True).strip().lower()
        matches = re.findall(r"\b([01])\b", output)
        if matches:
            return any(match == "1" for match in matches)
        if "=1" in output or "on" in output:
            return True
        if "=0" in output or "off" in output:
            return False
        return None

    def _probe_tvservice(self) -> Optional[bool]:
        binary = shutil.which("tvservice")
        if not binary:
            return None
        output = subprocess.check_output([binary, "-s"], text=True).strip().lower()
        if "is off" in output or "power off" in output:
            return False
        if output:
            return True
        return None

    def _probe_xset(self) -> Optional[bool]:
        binary = shutil.which("xset")
        if not binary:
            return None
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        output = subprocess.check_output(
            [binary, "q"], text=True, stderr=subprocess.DEVNULL, env=env
        ).lower()
        if "monitor is off" in output:
            return False
        if "monitor is on" in output or "dpms is disabled" in output:
            return True
        return None

