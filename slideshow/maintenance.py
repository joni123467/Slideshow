"""Helfer zur Planung regelmäßiger Wartungsaufgaben."""
from __future__ import annotations

import datetime
import logging
import threading
from typing import Optional

from .config import MaintenanceConfig, _is_valid_time_string

LOGGER = logging.getLogger(__name__)


def _parse_daily_time(value: str) -> Optional[datetime.time]:
    if not value:
        return None
    if not _is_valid_time_string(value):
        return None
    try:
        hours, minutes = value.strip().split(":", 1)
        return datetime.time(hour=int(hours), minute=int(minutes))
    except ValueError:
        return None


def is_valid_daily_time(value: str) -> bool:
    return _parse_daily_time(value) is not None


class DailyRebootScheduler:
    """Überwacht die Konfiguration und führt tägliche Neustarts aus."""

    def __init__(self, config: MaintenanceConfig, system_manager) -> None:
        self._config = config
        self._system_manager = system_manager
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._next_run: Optional[datetime.datetime] = None
        self._thread = threading.Thread(target=self._run, name="DailyReboot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def update_schedule(self) -> None:
        """Signaliert dem Scheduler, dass sich die Konfiguration geändert hat."""

        self._wake.set()

    def set_config(self, config: MaintenanceConfig) -> None:
        with self._lock:
            self._config = config
            self._next_run = None
        self.update_schedule()

    def next_run(self) -> Optional[datetime.datetime]:
        with self._lock:
            return self._next_run

    def _run(self) -> None:  # pragma: no cover - Hintergrundthread
        while not self._stop.is_set():
            schedule = self._compute_next_run()
            with self._lock:
                self._next_run = schedule

            if schedule is None:
                self._wait_for_event(timeout=3600)
                continue

            now = datetime.datetime.now()
            wait_seconds = max(0.0, (schedule - now).total_seconds())
            if self._wait_for_event(timeout=wait_seconds):
                continue

            if not self._config.auto_reboot_enabled:
                # Deaktiviert, bevor der Timer ausgelöst wurde.
                continue

            LOGGER.info(
                "Starte geplanten täglichen Neustart um %s",
                schedule.strftime("%Y-%m-%d %H:%M"),
            )
            try:
                self._system_manager.reboot()
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.error("Geplanter Neustart fehlgeschlagen: %s", exc)

    def _wait_for_event(self, timeout: float) -> bool:
        triggered = self._wake.wait(timeout=timeout)
        if triggered:
            self._wake.clear()
        return triggered

    def _compute_next_run(self) -> Optional[datetime.datetime]:
        if not self._config.auto_reboot_enabled:
            return None
        reboot_time = _parse_daily_time(self._config.auto_reboot_time)
        if reboot_time is None:
            return None

        now = datetime.datetime.now()
        candidate = now.replace(
            hour=reboot_time.hour,
            minute=reboot_time.minute,
            second=0,
            microsecond=0,
        )
        if candidate <= now + datetime.timedelta(seconds=5):
            candidate += datetime.timedelta(days=1)
        return candidate


__all__ = ["DailyRebootScheduler", "is_valid_daily_time"]
