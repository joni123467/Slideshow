"""Utilities für Netzwerk- und Hostname-Konfiguration."""
from __future__ import annotations

import json
import logging
import pathlib
import subprocess
from typing import Dict, List

from .config import AppConfig

LOGGER = logging.getLogger(__name__)


class NetworkManager:
    def __init__(self, config: AppConfig):
        self.config = config

    def set_hostname(self, hostname: str) -> None:
        LOGGER.info("Set hostname to %s", hostname)
        subprocess.run(["hostnamectl", "set-hostname", hostname], check=False)
        self.config.network.hostname = hostname
        self.config.save()

    def configure_static(self, interface: str, address: str, router: str, dns: str) -> None:
        LOGGER.info("Configure static IP on %s", interface)
        config_lines = [
            f"interface {interface}",
            f"static ip_address={address}",
            f"static routers={router}",
            f"static domain_name_servers={dns}",
        ]
        try:
            with open("/etc/dhcpcd.conf", "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            lines = []
        filtered = [line for line in lines if not line.startswith("interface ")]
        with open("/etc/dhcpcd.conf", "w", encoding="utf-8") as fh:
            fh.write("".join(filtered))
            fh.write("\n" + "\n".join(config_lines) + "\n")
        subprocess.run(["systemctl", "restart", "dhcpcd"], check=False)
        self.config.network.mode = "static"
        self.config.network.interface = interface
        self.config.network.static = {
            "address": address,
            "router": router,
            "dns": dns.split(","),
        }
        self.config.save()

    def configure_dhcp(self, interface: str) -> None:
        LOGGER.info("Configure DHCP on %s", interface)
        try:
            with open("/etc/dhcpcd.conf", "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            lines = []
        filtered = [line for line in lines if not line.startswith("interface ")]
        with open("/etc/dhcpcd.conf", "w", encoding="utf-8") as fh:
            fh.write("".join(filtered))
        subprocess.run(["systemctl", "restart", "dhcpcd"], check=False)
        self.config.network.mode = "dhcp"
        self.config.network.interface = interface
        self.config.save()

    def serialize(self) -> Dict:
        return {
            "hostname": self.config.network.hostname,
            "mode": self.config.network.mode,
            "interface": self.config.network.interface,
            "static": self.config.network.static,
        }

    def current_settings(self) -> Dict[str, object]:
        interface = self.config.network.interface or "eth0"
        info = {
            "hostname": None,
            "mode": self.config.network.mode,
            "interface": interface,
            "address": None,
            "router": None,
            "dns": [],
        }

        # Hostname ermitteln
        try:
            result = subprocess.run(
                ["hostnamectl", "--static"],
                capture_output=True,
                text=True,
                check=False,
            )
            hostname = (result.stdout or "").strip()
            if hostname:
                info["hostname"] = hostname
        except OSError:
            LOGGER.debug("hostnamectl nicht verfügbar")

        # IP-Adresse auslesen
        try:
            result = subprocess.run(
                ["ip", "-j", "addr", "show", interface],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.stdout:
                data = json.loads(result.stdout)
                if data:
                    addr_info = data[0].get("addr_info", [])
                    for entry in addr_info:
                        if entry.get("family") == "inet" and entry.get("scope") == "global":
                            info["address"] = entry.get("local") + "/" + str(entry.get("prefixlen"))
                            break
        except (OSError, json.JSONDecodeError, IndexError, AttributeError):
            LOGGER.debug("Konnte IP-Informationen nicht ermitteln")

        # Standardroute lesen
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default", "dev", interface],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in (result.stdout or "").splitlines():
                parts = line.split()
                if "via" in parts:
                    idx = parts.index("via")
                    if idx + 1 < len(parts):
                        info["router"] = parts[idx + 1]
                        break
        except OSError:
            LOGGER.debug("Konnte Standardroute nicht lesen")

        # DNS-Server sammeln
        resolv = pathlib.Path("/etc/resolv.conf")
        dns_servers: List[str] = []
        try:
            for line in resolv.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        dns_servers.append(parts[1])
        except OSError:
            LOGGER.debug("Konnte /etc/resolv.conf nicht lesen")
        if dns_servers:
            info["dns"] = dns_servers

        return info
