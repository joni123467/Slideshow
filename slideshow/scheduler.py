"""Verwaltung geplanter Neustarts über Cron."""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Iterable, List, Optional, Sequence

LOGGER = logging.getLogger(__name__)

CRON_MARKER = "# SLIDESHOW-AUTO-RESTART"
DEFAULT_COMMAND = "/sbin/shutdown -r now"


class RestartScheduler:
    """Pflegt Cron-Jobs für automatische Neustarts."""

    def __init__(
        self,
        player: Optional[object] = None,
        times: Optional[Iterable[str]] = None,
        *,
        cron_user: str = "root",
        command: str = DEFAULT_COMMAND,
    ) -> None:
        self._player = player  # für Abwärtskompatibilität, wird nicht mehr genutzt
        self._times: List[str] = []
        self._cron_user = cron_user
        self._command = command
        self._marker = CRON_MARKER
        if times:
            self.update_schedule(times)

    # Kompatibilitäts-Methoden -------------------------------------------
    def set_player(self, player: object) -> None:  # pragma: no cover - Kompatibilität
        self._player = player

    def stop(self) -> None:  # pragma: no cover - keine Threads mehr notwendig
        return

    # Öffentliche API ----------------------------------------------------
    def scheduled_times(self) -> List[str]:
        return list(self._times)

    def update_schedule(self, times: Iterable[str]) -> bool:
        minutes = self._normalize_times(times)
        formatted = [f"{value // 60:02d}:{value % 60:02d}" for value in minutes]
        if formatted == self._times and self._cron_contains(formatted):
            return True
        try:
            self._apply_crontab(minutes)
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("Konnte Cron-Einträge für Neustarts nicht aktualisieren")
            self._times = formatted
            return False
        else:
            self._times = formatted
            if formatted:
                LOGGER.info("Geplante Systemneustarts über Cron: %s", ", ".join(formatted))
            else:
                LOGGER.info("Geplante Systemneustarts deaktiviert")
            return True

    # Interne Helfer -----------------------------------------------------
    def _cron_contains(self, formatted: Sequence[str]) -> bool:
        existing = self._read_crontab()
        scheduled = sorted(self._extract_times(existing))
        return scheduled == sorted(formatted)

    def _apply_crontab(self, minutes: Sequence[int]) -> None:
        existing = self._read_crontab()
        retained = [line for line in existing if self._marker not in line]
        entries = list(retained)
        for value in sorted(set(minutes)):
            hour, minute = divmod(value, 60)
            line = f"{minute} {hour} * * * {self._command} {self._marker}"
            entries.append(line)
        data = "\n".join(entries).rstrip()
        if data:
            data += "\n"
        self._write_crontab(data)

    def _extract_times(self, lines: Sequence[str]) -> List[str]:
        times: List[str] = []
        for line in lines:
            if self._marker not in line:
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            minute, hour = parts[0], parts[1]
            try:
                hour_int = int(hour)
                minute_int = int(minute)
            except ValueError:
                continue
            if 0 <= hour_int < 24 and 0 <= minute_int < 60:
                times.append(f"{hour_int:02d}:{minute_int:02d}")
        return times

    def _normalize_times(self, times: Iterable[str]) -> List[int]:
        values: List[int] = []
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
                LOGGER.warning("Ungültige Neustartzeit in Cron-Planer ignoriert: %s", text)
                continue
            if not (0 <= hour < 24 and 0 <= minute < 60):
                LOGGER.warning("Neustartzeit außerhalb des zulässigen Bereichs: %s", text)
                continue
            value = hour * 60 + minute
            if value in seen:
                continue
            seen.add(value)
            values.append(value)
        values.sort()
        return values

    def _read_crontab(self) -> List[str]:
        cmd = self._cron_command(["-l"])
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            LOGGER.warning("crontab-Kommando nicht gefunden – geplante Neustarts können nicht eingerichtet werden")
            return []
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "no crontab for" in stderr.lower():
                return []
            LOGGER.warning("Konnte Cron-Tabelle nicht lesen: %s", stderr)
            return []
        return [line for line in result.stdout.splitlines()]

    def _write_crontab(self, data: str) -> None:
        cmd = self._cron_command(["-"])
        try:
            subprocess.run(cmd, input=data, text=True, check=True)
        except FileNotFoundError:
            LOGGER.warning("crontab-Kommando nicht gefunden – geplante Neustarts können nicht gespeichert werden")
        except subprocess.CalledProcessError as exc:
            LOGGER.warning("Fehler beim Schreiben der Cron-Tabelle: %s", exc)

    def _cron_command(self, args: Sequence[str]) -> List[str]:
        base = ["crontab"]
        if self._cron_user:
            base.extend(["-u", self._cron_user])
        base.extend(args)
        sudo = shutil.which("sudo")
        if sudo and self._needs_privileges():
            return [sudo] + base
        return base

    def _needs_privileges(self) -> bool:
        try:
            import getpass
            return self._cron_user and getpass.getuser() != self._cron_user
        except Exception:
            return bool(self._cron_user)

