"""Hilfsfunktionen für System- und Deployment-Aufgaben."""
from __future__ import annotations

import datetime
import logging
import os
import pathlib
import shlex
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Dict, List, Optional

LOGGER = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
try:
    from .config import DATA_DIR
except ImportError:  # pragma: no cover - Fallback für frühe Initialisierung
    DATA_DIR = pathlib.Path.home() / ".slideshow"

UPDATE_LOG = DATA_DIR / "logs" / "update.log"


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

    def _spawn_with_log(
        self,
        command: List[str],
        *,
        use_sudo: bool = False,
        branch: Optional[str] = None,
    ) -> subprocess.Popen:
        if use_sudo and os.geteuid() != 0:
            sudo = shutil.which("sudo")
            if not sudo:
                raise RuntimeError("sudo ist nicht verfügbar, benötigte Rechte können nicht angefordert werden")
            command = [sudo, "-n"] + command
        log_path = self.update_log_path
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - defensive
            LOGGER.warning("Konnte Update-Log-Verzeichnis nicht erstellen: %s", exc)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header_parts = [f"[{timestamp}] Update gestartet"]
        if branch:
            header_parts.append(f"Branch: {branch}")
        header = " - ".join(header_parts)
        command_repr = " ".join(shlex.quote(part) for part in command)
        try:
            with log_path.open("a", encoding="utf-8") as log_handle:
                if log_handle.tell() > 0:
                    log_handle.write("\n")
                log_handle.write(f"{header}\n")
                log_handle.write(f"Befehl: {command_repr}\n")
        except OSError as exc:
            LOGGER.warning("Konnte Update-Log nicht schreiben: %s", exc)
        try:
            log_file = log_path.open("a", encoding="utf-8")
        except OSError as exc:
            LOGGER.error("Update-Logdatei %s kann nicht geöffnet werden: %s", log_path, exc)
            raise RuntimeError("Update-Log konnte nicht geöffnet werden") from exc
        try:
            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except Exception:
            log_file.close()
            raise
        log_file.close()
        LOGGER.info("Update-Prozess gestartet (PID %s) für Branch %s", getattr(process, "pid", "?"), branch)
        return process

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
