"""Slideshow Package."""
from .logging_config import configure_logging

configure_logging()

__version__ = "0.0.1"

from .app import create_app

__all__ = ["create_app", "__version__"]
