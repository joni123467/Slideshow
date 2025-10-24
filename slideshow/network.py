"""Utilities für Netzwerk- und Hostname-Konfiguration."""
from __future__ import annotations

import dataclasses
import json
import logging
import pathlib
import subprocess
from typing import Dict, List, Optional

from .config import AppConfig, StaticIPConfig

LOGGER = logging.getLogger(__name__)


class NetworkManager:
    def __init__(self, config: AppConfig):
        self.config = config

    def set_hostname(self, hostname: str) -> None:
        LOGGER.info("Set hostname to %s", hostname)
        subprocess.run(["hostnamectl", "set-hostname", hostname], check=False)
        self.config.network.hostname = hostname
        self.config.save()

    def configure_interface(
        self,
        interface: str,
        *,
        ipv4_mode: str,
        ipv4: StaticIPConfig,
        ipv6_mode: str,
        ipv6: StaticIPConfig,
    ) -> None:
        normalized_ipv4_mode = self._normalize_mode(ipv4_mode)
        normalized_ipv6_mode = self._normalize_mode(ipv6_mode, allow_disabled=True)
        LOGGER.info(
            "Konfiguriere %s (IPv4: %s, IPv6: %s)",
            interface,
            normalized_ipv4_mode,
            normalized_ipv6_mode,
        )

        config_lines: List[str] = []
        dns_entries: List[str] = []

        if normalized_ipv4_mode == "static":
            if ipv4.address:
                config_lines.append(f"static ip_address={ipv4.address}")
            if ipv4.router:
                config_lines.append(f"static routers={ipv4.router}")
            dns_entries.extend(ipv4.dns)

        if normalized_ipv6_mode == "static":
            if ipv6.address:
                config_lines.append(f"static ip6_address={ipv6.address}")
            if ipv6.router:
                config_lines.append(f"static ip6_gateway={ipv6.router}")
            dns_entries.extend(ipv6.dns)

        combined_dns: List[str] = []
        seen_dns = set()
        for entry in dns_entries:
            cleaned = entry.strip()
            if not cleaned or cleaned in seen_dns:
                continue
            seen_dns.add(cleaned)
            combined_dns.append(cleaned)
        if combined_dns:
            config_lines.append(f"static domain_name_servers={' '.join(combined_dns)}")

        try:
            with open("/etc/dhcpcd.conf", "r", encoding="utf-8") as fh:
                existing_lines = fh.readlines()
        except FileNotFoundError:
            existing_lines = []

        filtered = self._remove_interface_block(interface, existing_lines)

        new_block: List[str] = []
        if config_lines:
            new_block.append(f"interface {interface}")
            indented = [f"    {line}" for line in config_lines]
            new_block.extend(indented)

        with open("/etc/dhcpcd.conf", "w", encoding="utf-8") as fh:
            preserved = "".join(filtered).rstrip("\n")
            if preserved:
                fh.write(preserved + "\n")
            if preserved and new_block:
                fh.write("\n")
            if new_block:
                fh.write("\n".join(new_block) + "\n")

        subprocess.run(["systemctl", "restart", "dhcpcd"], check=False)

        self.config.network.interface = interface
        self.config.network.ipv4.mode = normalized_ipv4_mode
        self.config.network.ipv4.static.address = ipv4.address
        self.config.network.ipv4.static.router = ipv4.router
        self.config.network.ipv4.static.dns = list(ipv4.dns)
        self.config.network.ipv6.mode = normalized_ipv6_mode
        self.config.network.ipv6.static.address = ipv6.address
        self.config.network.ipv6.static.router = ipv6.router
        self.config.network.ipv6.static.dns = list(ipv6.dns)
        self.config.save()

    def serialize(self) -> Dict:
        return {
            "hostname": self.config.network.hostname,
            "interface": self.config.network.interface,
            "ipv4": dataclasses.asdict(self.config.network.ipv4),
            "ipv6": dataclasses.asdict(self.config.network.ipv6),
        }

    def current_settings(self) -> Dict[str, object]:
        interface = self.config.network.interface or "eth0"
        info = {
            "hostname": None,
            "interface": interface,
            "ipv4": {
                "mode": self.config.network.ipv4.mode,
                "address": None,
                "router": None,
                "dns": [],
            },
            "ipv6": {
                "mode": self.config.network.ipv6.mode,
                "address": None,
                "router": None,
                "dns": [],
            },
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

        # IP-Adressen auslesen
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
                            info["ipv4"]["address"] = entry.get("local") + "/" + str(entry.get("prefixlen"))
                        elif entry.get("family") == "inet6":
                            scope = (entry.get("scope") or "").lower()
                            if scope not in {"link", "host"} and not info["ipv6"]["address"]:
                                info["ipv6"]["address"] = (
                                    entry.get("local") + "/" + str(entry.get("prefixlen"))
                                )
        except (OSError, json.JSONDecodeError, IndexError, AttributeError):
            LOGGER.debug("Konnte IP-Informationen nicht ermitteln")

        # Standardrouten lesen
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
                        info["ipv4"]["router"] = parts[idx + 1]
                        break
        except OSError:
            LOGGER.debug("Konnte Standardroute nicht lesen")

        try:
            result = subprocess.run(
                ["ip", "-6", "route", "show", "default", "dev", interface],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in (result.stdout or "").splitlines():
                parts = line.split()
                if "via" in parts:
                    idx = parts.index("via")
                    if idx + 1 < len(parts):
                        info["ipv6"]["router"] = parts[idx + 1]
                        break
        except OSError:
            LOGGER.debug("Konnte IPv6-Standardroute nicht lesen")

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
            for server in dns_servers:
                if ":" in server:
                    info["ipv6"]["dns"].append(server)
                else:
                    info["ipv4"]["dns"].append(server)

        return info

    def _remove_interface_block(self, interface: str, lines: List[str]) -> List[str]:
        filtered: List[str] = []
        skip = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("interface "):
                current_iface = stripped.split(None, 1)[1]
                skip = current_iface == interface
                if skip:
                    continue
            if skip:
                continue
            filtered.append(line)
        return filtered

    def _normalize_mode(self, value: Optional[str], allow_disabled: bool = False) -> str:
        normalized = (value or "dhcp").strip().lower()
        if allow_disabled and normalized in {"disabled", "off"}:
            return "disabled"
        if normalized in {"static", "dhcp"}:
            return normalized
        if normalized in {"auto", "automatic", "slaac"}:
            return "dhcp"
        return "dhcp"
