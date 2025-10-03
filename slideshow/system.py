"""Hilfsfunktionen für System- und Deployment-Aufgaben."""
from __future__ import annotations

import logging
import os
import pathlib
import shutil
import socket
import subprocess
from typing import Dict, List

LOGGER = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"


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

    def __init__(self, repo_dir: pathlib.Path = BASE_DIR, scripts_dir: pathlib.Path = SCRIPTS_DIR):
        self.repo_dir = pathlib.Path(repo_dir)
        self.scripts_dir = pathlib.Path(scripts_dir)

    # Git/Deployment --------------------------------------------------
    def current_branch(self) -> str:
        try:
            result = subprocess.check_output(["git", "-C", str(self.repo_dir), "rev-parse", "--abbrev-ref", "HEAD"], text=True)
            return result.strip()
        except subprocess.CalledProcessError:
            return ""

    def list_branches(self, remote: str = "origin") -> List[str]:
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

    def update(self, branch: str) -> subprocess.CompletedProcess:
        if not branch:
            raise ValueError("Branch darf nicht leer sein")
        script = self.scripts_dir / "update.sh"
        if script.exists():
            cmd = ["bash", str(script), branch]
        else:
            cmd = ["git", "-C", str(self.repo_dir), "pull", "origin", branch]
        return self._run(cmd, use_sudo=True)

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

    # Helpers ---------------------------------------------------------
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
