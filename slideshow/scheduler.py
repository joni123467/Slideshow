"""Hintergrundzeitplaner für geplante Neustarts."""
from __future__ import annotations

import datetime
import logging
import threading
from typing import Iterable, List, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - nur für Typprüfung
    from .player import PlayerService

LOGGER = logging.getLogger(__name__)


class RestartScheduler:
    """Verwaltet tägliche Neustarts des Player-Dienstes."""

    def __init__(self, player: Optional["PlayerService"] = None, times: Optional[Iterable[str]] = None) -> None:
        self._lock = threading.Lock()
        self._times: List[int] = []
        self._player: Optional["PlayerService"] = player
        self._stop = threading.Event()
        self._wakeup = threading.Event()
        self._thread = threading.Thread(target=self._run, name="RestartScheduler", daemon=True)
        if times:
            self.update_schedule(times)
        self._thread.start()

    def set_player(self, player: "PlayerService") -> None:
        """Aktualisiert den Player, der neugestartet werden soll."""

        with self._lock:
            self._player = player
        self._wakeup.set()

    def stop(self) -> None:
        """Beendet den Scheduler-Thread."""

        self._stop.set()
        self._wakeup.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def update_schedule(self, times: Iterable[str]) -> None:
        """Setzt die täglichen Neustartzeiten."""

        minutes = self._normalize_times(times)
        with self._lock:
            self._times = minutes
        self._wakeup.set()
        if minutes:
            LOGGER.info("Geplante Neustarts aktualisiert: %s", ", ".join(self._format_times(minutes)))
        else:
            LOGGER.info("Geplante Neustarts deaktiviert")

    def _format_times(self, minutes: List[int]) -> List[str]:
        return [f"{minute // 60:02d}:{minute % 60:02d}" for minute in minutes]

    def _normalize_times(self, times: Iterable[str]) -> List[int]:
        normalized: List[int] = []
        seen = set()
        for raw in times:
            if raw is None:
                continue
            text = str(raw).strip()
            if not text:
                continue
            if ":" in text:
                hour_part, minute_part = text.split(":", 1)
            else:
                hour_part, minute_part = text, "0"
            try:
                hour = int(hour_part)
                minute = int(minute_part)
            except ValueError:
                LOGGER.warning("Überspringe ungültige Neustartzeit '%s'", text)
                continue
            if not (0 <= hour < 24 and 0 <= minute < 60):
                LOGGER.warning("Überspringe Neustartzeit außerhalb des Bereichs: '%s'", text)
                continue
            value = hour * 60 + minute
            if value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        normalized.sort()
        return normalized

    def _run(self) -> None:  # pragma: no cover - Hintergrundthread
        while not self._stop.is_set():
            next_wakeup = self._next_occurrence()
            if next_wakeup is None:
                self._wakeup.wait(timeout=86400)
                self._wakeup.clear()
                continue

            now = datetime.datetime.now()
            delay = (next_wakeup - now).total_seconds()
            if delay > 0:
                awakened = self._wakeup.wait(timeout=delay)
                if awakened:
                    self._wakeup.clear()
                    continue
            if self._stop.is_set():
                break
            self._perform_restart()
            self._wakeup.wait(timeout=60)
            self._wakeup.clear()

    def _next_occurrence(self) -> Optional[datetime.datetime]:
        with self._lock:
            entries = list(self._times)
        if not entries:
            return None
        now = datetime.datetime.now()
        candidates: List[datetime.datetime] = []
        for minutes in entries:
            hour, minute = divmod(minutes, 60)
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += datetime.timedelta(days=1)
            candidates.append(candidate)
        return min(candidates)

    def _perform_restart(self) -> None:
        with self._lock:
            player = self._player
        if player is None:
            LOGGER.debug("Kein Player für geplanten Neustart verfügbar")
            return
        LOGGER.info("Führe geplanten Neustart der Slideshow aus")
        try:
            player.restart()
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("Geplanter Neustart fehlgeschlagen")

    def scheduled_times(self) -> List[str]:
        """Gibt die konfigurierten Zeiten als Zeichenketten zurück."""

        with self._lock:
            minutes = list(self._times)
        return self._format_times(minutes)
