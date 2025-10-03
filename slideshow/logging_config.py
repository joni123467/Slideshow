"""Zentrale Logging-Konfiguration."""
from __future__ import annotations

import logging
import logging.config
import logging.handlers
import pathlib
import warnings
from typing import Dict

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
    return result

