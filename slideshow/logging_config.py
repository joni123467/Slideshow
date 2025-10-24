"""Zentrale Logging-Konfiguration."""
from __future__ import annotations

import logging
import logging.config
import logging.handlers
import pathlib
import warnings
from typing import Dict, Tuple

from .config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"

LOG_GROUPS = {
    "app": {
        "filename": "app.log",
        "label": "Weboberfläche",
        "loggers": ["slideshow.app"],
    },
    "player": {
        "filename": "player.log",
        "label": "Player-Dienst",
        "loggers": ["slideshow.player"],
    },
    "media": {
        "filename": "media.log",
        "label": "Medienverwaltung",
        "loggers": ["slideshow.media", "slideshow.info"],
    },
    "network": {
        "filename": "network.log",
        "label": "Netzwerk",
        "loggers": ["slideshow.network"],
    },
    "system": {
        "filename": "system.log",
        "label": "Systemaktionen",
        "loggers": ["slideshow.system"],
    },
}

_configured = False

LOG_LEVEL_CHOICES: Tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def configure_logging() -> None:
    """Initialisiert die Logging-Struktur der Anwendung."""

    global _configured
    if _configured:
        return

    global LOG_DIR

    log_dir = LOG_DIR
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback_dir = pathlib.Path.home() / ".slideshow" / "logs"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        warnings.warn(
            f"Konnte Logverzeichnis {log_dir} nicht erzeugen, verwende {fallback_dir}.",
            RuntimeWarning,
            stacklevel=2,
        )
        log_dir = fallback_dir
        LOG_DIR = log_dir

    handlers: Dict[str, dict] = {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        }
    }
    loggers: Dict[str, dict] = {}

    for key, definition in LOG_GROUPS.items():
        log_path = log_dir / definition["filename"]
        handlers[f"{key}_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": str(log_path),
            "maxBytes": 2_000_000,
            "backupCount": 3,
            "encoding": "utf-8",
        }
        for logger_name in definition["loggers"]:
            loggers[logger_name] = {
                "handlers": [f"{key}_file", "console"],
                "level": "INFO",
                "propagate": False,
            }

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                }
            },
            "handlers": handlers,
            "loggers": loggers,
            "root": {
                "handlers": ["console"],
                "level": "INFO",
            },
        }
    )

    _configured = True


def available_logs() -> Dict[str, dict]:
    """Liefert die verfügbaren Logdateien und Metadaten."""

    result: Dict[str, dict] = {}
    for key, definition in LOG_GROUPS.items():
        result[key] = {
            "label": definition["label"],
            "path": LOG_DIR / definition["filename"],
        }
    result["update"] = {
        "label": "Update-Protokoll",
        "path": LOG_DIR / "update.log",
    }
    result["diagnostics"] = {
        "label": "Systemdiagnose",
        "path": LOG_DIR / "diagnostics.log",
    }
    return result


def apply_log_level(level: str) -> str:
    """Aktualisiert das Log-Level für alle bekannten Logger."""

    normalized = (level or "INFO").strip().upper()
    if normalized not in LOG_LEVEL_CHOICES:
        raise ValueError(f"Unbekanntes Log-Level: {level}")

    numeric = getattr(logging, normalized, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric)
    for handler in root_logger.handlers:
        handler.setLevel(numeric)

    for group in LOG_GROUPS.values():
        for logger_name in group["loggers"]:
            logger = logging.getLogger(logger_name)
            logger.setLevel(numeric)
            for handler in logger.handlers:
                handler.setLevel(numeric)

    return normalized


def current_log_level() -> str:
    """Gibt das effektive Log-Level der Anwendung zurück."""

    root_logger = logging.getLogger()
    return logging.getLevelName(root_logger.getEffectiveLevel())

