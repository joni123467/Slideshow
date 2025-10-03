"""Utilities für Netzwerk- und Hostname-Konfiguration."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import asdict
from typing import Dict

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
