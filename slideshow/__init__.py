"""Slideshow Package."""
from __future__ import annotations

import pathlib

try:
    from importlib import metadata as importlib_metadata
except ImportError:  # pragma: no cover - fallback für ältere Python-Versionen
    import importlib_metadata  # type: ignore[no-redef]

from .logging_config import configure_logging


def _discover_version() -> str:
    package_name = "slideshow"
    try:
        return importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        project_root = pathlib.Path(__file__).resolve().parent.parent
        pyproject = project_root / "pyproject.toml"
        if pyproject.exists():
            for line in pyproject.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("version"):
                    _, _, value = line.partition("=")
                    return value.strip().strip('"')
        return "0.0.0"


configure_logging()

__version__ = _discover_version()

from .app import create_app

__all__ = ["create_app", "__version__"]
