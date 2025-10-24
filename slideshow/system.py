"""Hilfsfunktionen für System- und Deployment-Aufgaben."""
from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import re
import shlex
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
try:
    from .config import DATA_DIR
except ImportError:  # pragma: no cover - Fallback für frühe Initialisierung
    DATA_DIR = pathlib.Path.home() / ".slideshow"

UPDATE_LOG = DATA_DIR / "logs" / "update.log"
DIAGNOSTICS_LOG = DATA_DIR / "logs" / "diagnostics.log"


def resolve_hostname() -> str:
    """Ermittelt den aktuellen Hostnamen."""
    return socket.gethostname()


def resolve_ip_addresses() -> List[str]:
    """Liefert bekannte IP-Adressen (IPv4) des Systems."""
    try:
        output = subprocess.check_output(["hostname", "-I"], text=True).strip()
        addresses = [addr for addr in output.split() if addr]
        if addresses:
            return addresses
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.debug("hostname -I fehlgeschlagen: %s", exc)
    # Fallback über Netzwerkinterfaces
    addresses: List[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addr = info[4][0]
            if ":" not in addr:
                addresses.append(addr)
    except socket.gaierror:  # pragma: no cover - defensive
        pass
    return sorted(set(addresses))


class SystemManager:
    """Kapselt Update-, Service- und Reboot-Operationen."""

    def __init__(
        self,
        repo_dir: pathlib.Path = BASE_DIR,
        scripts_dir: pathlib.Path = SCRIPTS_DIR,
        fallback_repo: Optional[str] = "joni123467/Slideshow",
    ):
        self.repo_dir = pathlib.Path(repo_dir)
        self.scripts_dir = pathlib.Path(scripts_dir)
        self.install_branch_file = self.repo_dir / ".install_branch"
        self.install_repo_file = self.repo_dir / ".install_repo"
        self.fallback_repo = fallback_repo
        self.update_log_path = UPDATE_LOG
        self.diagnostics_log_path = DIAGNOSTICS_LOG
        detected_repo = self._read_install_file(self.install_repo_file)
        if detected_repo:
            self.fallback_repo = detected_repo

    # Git/Deployment --------------------------------------------------
    def current_branch(self) -> Optional[str]:
        if not self._has_git_repo():
            branch = self._read_install_file(self.install_branch_file)
            if branch:
                return branch
            LOGGER.debug("Kein Git-Repository vorhanden, aktueller Branch unbekannt")
            return None
        try:
            result = subprocess.check_output(
                ["git", "-C", str(self.repo_dir), "rev-parse", "--abbrev-ref", "HEAD"],
                text=True,
            )
            return result.strip() or None
        except subprocess.CalledProcessError as exc:
            LOGGER.debug("Konnte aktuellen Branch nicht ermitteln: %s", exc)
            return None

    def list_branches(self, remote: str = "origin") -> List[str]:
        if self._has_git_repo():
            try:
                result = subprocess.check_output(
                    ["git", "-C", str(self.repo_dir), "ls-remote", "--heads", remote], text=True
                )
            except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
                LOGGER.warning("Konnte Branches nicht abrufen: %s", exc)
                return []
            branches = []
            for line in result.strip().splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].startswith("refs/heads/"):
                    branches.append(parts[1].split("/", 2)[-1])
        else:
            branches = self._fetch_remote_branches()

        if not branches:
            return []

        unique_branches = sorted(set(branches))

        def sort_key(name: str):
            normalized = name.replace(" ", "-").replace("_", "-")
            if normalized.lower().startswith("version") and "-" in normalized:
                version_part = normalized.split("-", 1)[-1]
                try:
                    numbers = tuple(int(part) for part in version_part.split("."))
                    return (0, tuple(-part for part in numbers), name)
                except ValueError:
                    pass
            return (1, (name,), name)

        ordered = sorted((sort_key(branch) for branch in unique_branches))
        return [entry[-1] for entry in ordered]

    def update(self, branch: str) -> subprocess.Popen:
        if not branch:
            raise ValueError("Branch darf nicht leer sein")
        script = self.scripts_dir / "update.sh"
        if script.exists():
            cmd = ["bash", str(script), branch]
        else:
            if not self._has_git_repo():
                raise RuntimeError("Keine Git-Installation vorhanden, Update nicht möglich")
            repo_path = shlex.quote(str(self.repo_dir))
            remote_branch = shlex.quote(branch)
            cmd = [
                "bash",
                "-lc",
                (
                    "set -euo pipefail; "
                    f"cd {repo_path}; "
                    f"git fetch origin {remote_branch}; "
                    f"git checkout {remote_branch}; "
                    f"git reset --hard origin/{remote_branch}; "
                    f"echo {shlex.quote(branch)} > {shlex.quote(str(self.install_branch_file))}"
                ),
            ]
        process = self._spawn_with_log(cmd, use_sudo=True, branch=branch)
        if not isinstance(process, subprocess.Popen):
            raise RuntimeError("Update konnte nicht gestartet werden")
        return process

    def detect_display_resolution(self) -> Optional[str]:
        detectors = (
            self._detect_resolution_from_xrandr,
            self._detect_resolution_from_fbset,
            self._detect_resolution_from_sysfs,
        )
        for detector in detectors:
            try:
                value = detector()
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.debug("%s fehlgeschlagen: %s", detector.__name__, exc)
                continue
            if value:
                return value
        return None

    # Service-Steuerung -----------------------------------------------
    def service_status(self, service: str = "slideshow.service") -> str:
        cmd = ["systemctl", "is-active", service]
        result = self._run(cmd, use_sudo=True, check=False, capture=True)
        if isinstance(result, subprocess.CompletedProcess):
            return result.stdout.strip() or str(result.returncode)
        return "unknown"

    def control_service(self, action: str, service: str = "slideshow.service") -> subprocess.CompletedProcess:
        if action not in {"start", "stop", "restart"}:
            raise ValueError("Ungültige Aktion")
        cmd = ["systemctl", action, service]
        return self._run(cmd, use_sudo=True)

    def reboot(self) -> subprocess.CompletedProcess:
        return self._run(["reboot"], use_sudo=True)

    def shutdown(self) -> subprocess.CompletedProcess:
        return self._run(["poweroff"], use_sudo=True)

    # Systemübersicht ------------------------------------------------
    def system_overview(self) -> Dict[str, Any]:
        overview: Dict[str, Any] = {
            "hostname": resolve_hostname(),
            "ip_addresses": resolve_ip_addresses(),
            "uptime_seconds": None,
            "uptime_human": None,
            "cpu_count": os.cpu_count() or 1,
            "load_avg": None,
            "memory": {},
            "swap": {},
            "disk_usage": [],
        }

        uptime_seconds = self._read_uptime_seconds()
        if uptime_seconds is not None:
            overview["uptime_seconds"] = uptime_seconds
            overview["uptime_human"] = self._format_duration(uptime_seconds)

        try:
            load_one, load_five, load_fifteen = os.getloadavg()
            cpu_count = overview["cpu_count"] or 1
            overview["load_avg"] = {
                "1": load_one,
                "5": load_five,
                "15": load_fifteen,
                "per_cpu": {
                    "1": load_one / cpu_count,
                    "5": load_five / cpu_count,
                    "15": load_fifteen / cpu_count,
                },
            }
        except (OSError, AttributeError):
            overview["load_avg"] = None

        meminfo = self._read_meminfo()
        mem_total = meminfo.get("MemTotal")
        mem_available = meminfo.get("MemAvailable")
        mem_free = meminfo.get("MemFree")
        if mem_total:
            used = mem_total - (mem_available or 0)
            overview["memory"] = {
                "total": mem_total,
                "available": mem_available,
                "free": mem_free,
                "used": used,
                "percent": self._percentage(used, mem_total),
            }
        swap_total = meminfo.get("SwapTotal")
        if swap_total:
            swap_free = meminfo.get("SwapFree", 0)
            swap_used = swap_total - swap_free
            overview["swap"] = {
                "total": swap_total,
                "free": swap_free,
                "used": swap_used,
                "percent": self._percentage(swap_used, swap_total),
            }

        disk_targets = [
            (pathlib.Path("/"), "Root-Dateisystem"),
            (DATA_DIR, "Datenverzeichnis"),
        ]
        seen: Dict[str, bool] = {}
        for target_path, label in disk_targets:
            try:
                usage = shutil.disk_usage(str(target_path))
            except OSError as exc:
                LOGGER.debug("Konnte Belegung für %s nicht ermitteln: %s", target_path, exc)
                continue
            real_path = str(target_path)
            try:
                real_path = str(pathlib.Path(target_path).resolve())
            except OSError:
                real_path = str(target_path)
            if real_path in seen:
                continue
            seen[real_path] = True
            used = usage.total - usage.free
            overview["disk_usage"].append(
                {
                    "label": label,
                    "path": str(target_path),
                    "total": usage.total,
                    "used": used,
                    "free": usage.free,
                    "percent": self._percentage(used, usage.total),
                }
            )

        return overview

    def storage_devices(self) -> Dict[str, Any]:
        devices_info: Dict[str, Any] = {
            "devices": [],
            "smartctl_available": shutil.which("smartctl") is not None,
            "errors": [],
        }
        entries = self._lsblk_devices()
        if not entries:
            return devices_info

        for entry in entries:
            device_type = str(entry.get("type") or "")
            if device_type.lower() != "disk":
                continue
            name = entry.get("name") or entry.get("kname")
            if not name:
                continue
            device_path = entry.get("kname") or entry.get("name") or ""
            device_path = f"/dev/{device_path}"
            try:
                size = int(entry.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            mountpoints = self._collect_mountpoints(entry)
            device_info: Dict[str, Any] = {
                "name": name,
                "path": device_path,
                "size": size,
                "model": (entry.get("model") or "").strip() or None,
                "serial": (entry.get("serial") or "").strip() or None,
                "mountpoints": mountpoints,
                "smart": {
                    "available": devices_info["smartctl_available"],
                    "supported": False,
                    "health": None,
                    "temperature": None,
                    "message": None,
                    "details": None,
                    "indicator": "neutral",
                },
            }
            if devices_info["smartctl_available"]:
                smart_info = self._smartctl_info(device_path)
                for key, value in smart_info.items():
                    if key in device_info["smart"]:
                        device_info["smart"][key] = value
                error_message = smart_info.get("error")
                if error_message:
                    devices_info["errors"].append(error_message)
            devices_info["devices"].append(device_info)

        devices_info["devices"].sort(key=lambda item: item.get("path") or "")
        return devices_info

    def run_diagnostics(self, mode: str = "check") -> subprocess.Popen:
        normalized = (mode or "check").strip().lower()
        if normalized not in {"check", "repair"}:
            raise ValueError("Ungültiger Diagnosemodus")
        script = self.scripts_dir / "system_diagnostics.sh"
        if not script.exists():
            raise FileNotFoundError(f"Diagnoseskript {script} wurde nicht gefunden")
        command = ["bash", str(script), normalized]
        header = f"Systemdiagnose gestartet (Modus: {normalized})"
        env = os.environ.copy()
        env.setdefault("SLIDESHOW_DATA_DIR", str(DATA_DIR))
        description = f"Systemdiagnose gestartet ({normalized})"
        return self._spawn_to_log(
            command,
            log_path=self.diagnostics_log_path,
            header=header,
            use_sudo=True,
            env=env,
            log_description=description,
        )

    def diagnostics_summary(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "path": self.diagnostics_log_path,
            "exists": False,
            "last_run": None,
        }
        path = self.diagnostics_log_path
        if path.exists():
            info["exists"] = True
            try:
                info["last_run"] = path.stat().st_mtime
            except OSError:
                info["last_run"] = None
        return info

    # Logging ---------------------------------------------------------
    def available_logs(self) -> Dict[str, pathlib.Path]:
        from .logging_config import available_logs as logging_available

        sources = {}
        for key, info in logging_available().items():
            sources[key] = pathlib.Path(info["path"])
        return sources

    def read_log(self, name: str, lines: int = 200) -> str:
        logs = self.available_logs()
        path = logs.get(name)
        if not path:
            raise ValueError("Unbekanntes Log")
        if not path.exists():
            return ""
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            content = handle.readlines()
        if lines <= 0:
            return "".join(content)
        return "".join(content[-lines:])

    def delete_log(self, name: str) -> None:
        logs = self.available_logs()
        path = logs.get(name)
        if not path:
            raise ValueError("Unbekanntes Log")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8"):
            pass

    # Helpers ---------------------------------------------------------
    def _read_uptime_seconds(self) -> Optional[float]:
        path = pathlib.Path("/proc/uptime")
        try:
            data = path.read_text(encoding="utf-8").split()
        except OSError:
            return None
        if not data:
            return None
        try:
            return float(data[0])
        except (ValueError, IndexError):
            return None

    def _read_meminfo(self) -> Dict[str, int]:
        info: Dict[str, int] = {}
        path = pathlib.Path("/proc/meminfo")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return info
        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            parts = value.strip().split()
            if not parts:
                continue
            number_text = parts[0]
            unit = parts[1] if len(parts) > 1 else ""
            try:
                number = float(number_text)
            except ValueError:
                continue
            multiplier = 1
            unit_lower = unit.lower()
            if unit_lower.startswith("kb"):
                multiplier = 1024
            elif unit_lower.startswith("mb"):
                multiplier = 1024 ** 2
            elif unit_lower.startswith("gb"):
                multiplier = 1024 ** 3
            info[key.strip()] = int(number * multiplier)
        return info

    def _collect_mountpoints(self, entry: Dict[str, Any]) -> List[str]:
        mountpoints: List[str] = []
        current = entry.get("mountpoints")
        if isinstance(current, list):
            for item in current:
                if item:
                    mountpoints.append(str(item))
        elif isinstance(current, str):
            if current:
                mountpoints.append(current)
        for child in entry.get("children") or []:
            mountpoints.extend(self._collect_mountpoints(child))
        if not mountpoints:
            return []
        seen: Dict[str, bool] = {}
        result: List[str] = []
        for mountpoint in mountpoints:
            if mountpoint in seen:
                continue
            seen[mountpoint] = True
            result.append(mountpoint)
        return result

    def _lsblk_devices(self) -> List[Dict[str, Any]]:
        lsblk = shutil.which("lsblk")
        if not lsblk:
            LOGGER.debug("lsblk ist nicht im PATH verfügbar")
            return []
        columns = ["NAME", "KNAME", "TYPE", "SIZE", "MODEL", "SERIAL", "MOUNTPOINTS", "FSTYPE"]
        cmd = [lsblk, "-J", "-b", "-o", ",".join(columns)]
        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            LOGGER.warning("lsblk fehlgeschlagen: %s", exc.stderr or exc)
            return []
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            LOGGER.warning("Konnte lsblk-Ausgabe nicht als JSON lesen: %s", exc)
            return []
        devices = payload.get("blockdevices")
        if not isinstance(devices, list):
            return []
        return devices

    def _smartctl_info(self, device_path: str) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "available": True,
            "supported": False,
            "health": None,
            "temperature": None,
            "message": None,
            "details": None,
            "indicator": "neutral",
        }
        command = ["smartctl", "-H", "-i", "-A", device_path]
        try:
            result = self._run(command, use_sudo=True, check=False, capture=True)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.debug("smartctl für %s fehlgeschlagen: %s", device_path, exc)
            info["message"] = str(exc)
            info["indicator"] = "info"
            info["error"] = f"{device_path}: {exc}"
            return info
        if not isinstance(result, subprocess.CompletedProcess):
            info["message"] = "smartctl lieferte kein Ergebnis"
            info["indicator"] = "info"
            info["error"] = f"{device_path}: smartctl konnte nicht ausgeführt werden"
            return info
        output_parts: List[str] = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(result.stderr)
        output = "\n".join(part for part in output_parts if part).strip()
        if len(output) > 8000:
            info["details"] = output[-8000:]
        else:
            info["details"] = output
        lower_output = output.lower()
        if "permission denied" in lower_output:
            info["message"] = "Zugriff verweigert (sudo-Berechtigung erforderlich)"
        supports_smart = False
        health: Optional[str] = None
        for line in output.splitlines():
            normalized = line.strip()
            if not normalized:
                continue
            if "smart support is" in normalized.lower():
                text = normalized.split(":", 1)[-1].strip()
                supports_smart = not any(keyword in text.lower() for keyword in ("unavailable", "disabled", "not available"))
                if not supports_smart:
                    info["message"] = text
            if "smart overall-health" in normalized.lower() or "smart health status" in normalized.lower():
                parts = normalized.split(":", 1)
                if len(parts) == 2:
                    health = parts[1].strip()
                else:
                    health = normalized
            elif "overall-health self-assessment" in normalized.lower():
                parts = normalized.split(":", 1)
                if len(parts) == 2:
                    health = parts[1].strip()
        if "nvme log" in lower_output and "health information" in lower_output:
            supports_smart = True
        if "does not support smart" in lower_output:
            supports_smart = False
        info["supported"] = supports_smart
        if health:
            info["health"] = health
            lowered = health.lower()
            if any(token in lowered for token in ("pass", "ok", "good")):
                info["indicator"] = "ok"
            elif any(token in lowered for token in ("fail", "bad", "critical", "error")):
                info["indicator"] = "down"
            else:
                info["indicator"] = "info"
        elif not supports_smart:
            info["indicator"] = "info"
        temperature = self._extract_temperature(output)
        if temperature:
            info["temperature"] = temperature
        if result.returncode not in (0, 2):
            info.setdefault("message", f"smartctl meldete Status {result.returncode}")
            info["indicator"] = "info" if info["indicator"] == "ok" else info["indicator"]
            info["error"] = f"smartctl Status {result.returncode} für {device_path}"
        return info

    def _extract_temperature(self, output: str) -> Optional[str]:
        if not output:
            return None
        for pattern in (
            r"Temperature(?:_Celsius)?[^:]*:\s*([-+]?\d+)\s*(?:C|Celsius)",
            r"Current Temperature:\s*([-+]?\d+)\s*(?:C|Celsius)",
        ):
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return f"{match.group(1)} °C"
        for line in output.splitlines():
            if "Temperature" not in line:
                continue
            match = re.search(r"([-+]?\d+)\s*(?:C|Celsius)", line)
            if match:
                return f"{match.group(1)} °C"
        return None

    def _format_duration(self, seconds: float) -> str:
        if seconds is None:
            return ""
        total_seconds = int(seconds)
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        parts: List[str] = []
        if days:
            parts.append(f"{days} Tag{'e' if days != 1 else ''}")
        if hours:
            parts.append(f"{hours} Std")
        if minutes:
            parts.append(f"{minutes} Min")
        if not parts:
            parts.append(f"{secs} Sek")
        return " ".join(parts)

    def _percentage(self, value: Optional[float], total: Optional[float]) -> Optional[float]:
        try:
            if value is None or total in (None, 0):
                return None
            return (float(value) / float(total)) * 100.0
        except (TypeError, ZeroDivisionError, ValueError):
            return None

    def _spawn_to_log(
        self,
        command: List[str],
        *,
        log_path: pathlib.Path,
        header: Optional[str] = None,
        use_sudo: bool = False,
        env: Optional[Dict[str, str]] = None,
        log_description: Optional[str] = None,
    ) -> subprocess.Popen:
        if use_sudo and os.geteuid() != 0:
            sudo = shutil.which("sudo")
            if not sudo:
                raise RuntimeError("sudo ist nicht verfügbar, benötigte Rechte können nicht angefordert werden")
            command = [sudo, "-n"] + command
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - defensive
            LOGGER.warning("Konnte Log-Verzeichnis %s nicht erstellen: %s", log_path.parent, exc)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        command_repr = " ".join(shlex.quote(part) for part in command)
        header_text = header or "Prozess gestartet"
        try:
            with log_path.open("a", encoding="utf-8") as log_handle:
                if log_handle.tell() > 0:
                    log_handle.write("\n")
                log_handle.write(f"[{timestamp}] {header_text}\n")
                log_handle.write(f"Befehl: {command_repr}\n")
        except OSError as exc:
            LOGGER.warning("Konnte Logdatei %s nicht beschreiben: %s", log_path, exc)
        try:
            log_file = log_path.open("a", encoding="utf-8")
        except OSError as exc:
            LOGGER.error("Logdatei %s kann nicht geöffnet werden: %s", log_path, exc)
            raise RuntimeError("Logdatei konnte nicht geöffnet werden") from exc
        try:
            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
        except Exception:
            log_file.close()
            raise
        log_file.close()
        description = log_description or header_text
        LOGGER.info("%s (PID %s)", description, getattr(process, "pid", "?"))
        return process

    def _detect_resolution_from_xrandr(self) -> Optional[str]:
        try:
            output = subprocess.check_output(
                ["xrandr", "--current"], text=True, stderr=subprocess.STDOUT
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            LOGGER.debug("xrandr-Erkennung fehlgeschlagen: %s", exc)
            return None
        pattern = re.compile(r"(\d{3,5})x(\d{3,5})")
        for line in output.splitlines():
            if "*" not in line:
                continue
            match = pattern.search(line)
            if match:
                return f"{match.group(1)}x{match.group(2)}"
        for line in output.splitlines():
            if "connected" not in line:
                continue
            match = pattern.search(line)
            if match:
                return f"{match.group(1)}x{match.group(2)}"
        return None

    def _detect_resolution_from_fbset(self) -> Optional[str]:
        try:
            output = subprocess.check_output(
                ["fbset", "-s"], text=True, stderr=subprocess.STDOUT
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            LOGGER.debug("fbset-Erkennung fehlgeschlagen: %s", exc)
            return None
        match = re.search(r"geometry\s+(\d{3,5})\s+(\d{3,5})", output)
        if match:
            return f"{match.group(1)}x{match.group(2)}"
        return None

    def _detect_resolution_from_sysfs(self) -> Optional[str]:
        path = pathlib.Path("/sys/class/graphics/fb0/virtual_size")
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            LOGGER.debug("Konnte Auflösung aus %s nicht lesen: %s", path, exc)
            return None
        if not raw:
            return None
        if "," in raw:
            width, height = raw.split(",", 1)
        else:
            parts = raw.split()
            if len(parts) >= 2:
                width, height = parts[:2]
            else:
                return None
        try:
            width_val = int(width)
            height_val = int(height)
        except ValueError:
            return None
        if width_val <= 0 or height_val <= 0:
            return None
        return f"{width_val}x{height_val}"

    def _run(
        self,
        command: List[str],
        *,
        use_sudo: bool = False,
        check: bool = True,
        capture: bool = False,
    ) -> subprocess.CompletedProcess:
        if use_sudo and os.geteuid() != 0:
            sudo = shutil.which("sudo")
            if not sudo:
                raise RuntimeError("sudo ist nicht verfügbar, benötigte Rechte können nicht angefordert werden")
            command = [sudo, "-n"] + command
        LOGGER.info("Starte Befehl: %s", " ".join(command))
        run_kwargs = {"check": check, "text": True}
        if capture:
            run_kwargs["capture_output"] = True
        try:
            return subprocess.run(command, **run_kwargs)
        except subprocess.CalledProcessError as exc:
            if use_sudo:
                stderr = (exc.stderr or "").strip() if hasattr(exc, "stderr") else ""
                if "password" in stderr.lower():
                    LOGGER.error("sudo verweigerte den Zugriff: %s", stderr)
                else:
                    LOGGER.error("Befehl %s schlug fehl: %s", command, stderr or exc)
            raise

    def _spawn_with_log(
        self,
        command: List[str],
        *,
        use_sudo: bool = False,
        branch: Optional[str] = None,
    ) -> subprocess.Popen:
        header = "Update gestartet"
        if branch:
            header = f"{header} - Branch: {branch}"
        description = "Update-Prozess gestartet"
        if branch:
            description = f"{description} (Branch {branch})"
        return self._spawn_to_log(
            command,
            log_path=self.update_log_path,
            header=header,
            use_sudo=use_sudo,
            log_description=description,
        )

    def _has_git_repo(self) -> bool:
        git_dir = self.repo_dir / ".git"
        if not git_dir.exists():
            return False
        if shutil.which("git") is None:
            LOGGER.debug("git ist nicht installiert oder nicht im PATH")
            return False
        return True

    def _fetch_remote_branches(self) -> List[str]:
        if not self.fallback_repo:
            return []
        api_url = f"https://api.github.com/repos/{self.fallback_repo}/branches?per_page=100"
        try:
            with urllib.request.urlopen(api_url, timeout=10) as response:
                if response.status != 200:
                    LOGGER.debug("GitHub-Antwort %s für %s", response.status, api_url)
                    return []
                data = response.read()
        except urllib.error.URLError as exc:  # pragma: no cover - Netzwerkfehler
            LOGGER.warning("Konnte Branch-Liste nicht von GitHub laden: %s", exc)
            return []
        try:
            import json

            branches = [entry.get("name") for entry in json.loads(data) if isinstance(entry, dict)]
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            LOGGER.warning("Ungültige Antwort von GitHub: %s", exc)
            return []
        return [branch for branch in branches if branch]

    def _read_install_file(self, path: pathlib.Path) -> Optional[str]:
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return content or None
