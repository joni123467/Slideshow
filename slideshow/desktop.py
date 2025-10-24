"""Utilities to control desktop appearance for kiosk mode."""
from __future__ import annotations

import logging
import pathlib
import shutil
import subprocess
import threading
from typing import Optional

LOGGER = logging.getLogger(__name__)

_WALLPAPER_LOCK = threading.Lock()
_LAST_WALLPAPER: Optional[pathlib.Path] = None
_TASKBAR_LOCK = threading.Lock()
_TASKBAR_HIDDEN = False
_TASKBAR_KEYWORDS = (
    "panel",
    "taskbar",
    "dock",
    "leiste",
    "taskleiste",
    "tint2",
    "polybar",
    "plank",
)


def set_wallpaper(path: pathlib.Path) -> None:
    """Set the desktop wallpaper to the provided image if possible."""

    if not path:
        return
    resolved = pathlib.Path(path)
    if not resolved.exists():
        LOGGER.debug("Hintergrunddatei %s existiert nicht", resolved)
        return

    feh = shutil.which("feh")
    if not feh:
        LOGGER.debug("feh nicht gefunden, kann Hintergrund nicht setzen")
        return

    global _LAST_WALLPAPER
    with _WALLPAPER_LOCK:
        try:
            if _LAST_WALLPAPER and resolved.samefile(_LAST_WALLPAPER):
                return
        except FileNotFoundError:
            pass

        result = subprocess.run(
            [feh, "--bg-fill", str(resolved)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            LOGGER.warning(
                "Setzen des Hintergrundbilds für %s fehlgeschlagen (Code %s)",
                resolved,
                result.returncode,
            )
            return
        _LAST_WALLPAPER = resolved


def hide_taskbar() -> None:
    """Attempt to hide any detected taskbar or dock windows."""

    wmctrl = shutil.which("wmctrl")
    if not wmctrl:
        LOGGER.debug("wmctrl nicht gefunden, kann Taskleiste nicht ausblenden")
        return

    global _TASKBAR_HIDDEN
    with _TASKBAR_LOCK:
        if _TASKBAR_HIDDEN:
            return
        try:
            output = subprocess.check_output(
                [wmctrl, "-lG"], text=True, stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError as exc:
            LOGGER.debug("wmctrl -lG fehlgeschlagen: %s", exc)
            return

        window_ids = []
        for line in output.splitlines():
            parts = line.split(None, 6)
            if len(parts) < 7:
                continue
            window_id = parts[0]
            title = parts[6]
            if _is_taskbar_window(window_id, title):
                window_ids.append(window_id)

        if not window_ids:
            LOGGER.debug("Keine Taskleistenfenster gefunden")
            _TASKBAR_HIDDEN = True
            return

        hidden_any = False
        for window_id in window_ids:
            result = subprocess.run(
                [wmctrl, "-i", "-r", window_id, "-b", "add,hidden"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                hidden_any = True

        if hidden_any:
            _TASKBAR_HIDDEN = True
        else:
            LOGGER.debug("Ausblenden der Taskleiste fehlgeschlagen")


def _is_taskbar_window(window_id: str, title: str) -> bool:
    lower_title = (title or "").lower()
    if any(keyword in lower_title for keyword in _TASKBAR_KEYWORDS):
        return True

    xprop = shutil.which("xprop")
    if not xprop:
        return False

    try:
        info = subprocess.check_output(
            [xprop, "-id", window_id, "_NET_WM_WINDOW_TYPE"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return False

    lowered = info.lower()
    return "_net_wm_window_type_dock" in lowered or "_net_wm_window_type_toolbar" in lowered
