"""Utilities to control desktop appearance for kiosk mode."""
from __future__ import annotations

import logging
import os
import pathlib
import re
import shutil
import subprocess
import threading
from functools import lru_cache
from typing import Callable, Iterable, Optional

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

    global _LAST_WALLPAPER
    with _WALLPAPER_LOCK:
        try:
            if _LAST_WALLPAPER and resolved.samefile(_LAST_WALLPAPER):
                return
        except FileNotFoundError:
            pass

        for handler in _wallpaper_handlers():
            if handler(resolved):
                _LAST_WALLPAPER = resolved
                return

        LOGGER.debug("Kein passender Hintergrund-Handler gefunden")


def hide_taskbar() -> None:
    """Attempt to hide any detected taskbar or dock windows."""

    global _TASKBAR_HIDDEN
    with _TASKBAR_LOCK:
        if _TASKBAR_HIDDEN:
            return

        if _hide_taskbar_desktop_specific():
            _TASKBAR_HIDDEN = True
            return

        if _hide_taskbar_via_wmctrl():
            _TASKBAR_HIDDEN = True
            return

        LOGGER.debug("Kein Taskleisten-Handler erfolgreich")


def _wallpaper_handlers() -> Iterable[Callable[[pathlib.Path], bool]]:
    desktops = _current_desktops()
    handlers: list[Callable[[pathlib.Path], bool]] = []

    if _matches_desktop(desktops, {"gnome", "unity", "budgie", "pantheon"}):
        handlers.append(_set_wallpaper_gnome)
    if _matches_desktop(desktops, {"cinnamon"}):
        handlers.append(_set_wallpaper_cinnamon)
    if _matches_desktop(desktops, {"mate"}):
        handlers.append(_set_wallpaper_mate)
    if _matches_desktop(desktops, {"xfce"}):
        handlers.append(_set_wallpaper_xfce)
    if _matches_desktop(desktops, {"kde", "plasma"}):
        handlers.append(_set_wallpaper_plasma)
    if _matches_desktop(desktops, {"lxqt", "lxde"}):
        handlers.append(_set_wallpaper_pcmanfm)
    if _is_wayland_sway():
        handlers.append(_set_wallpaper_sway)

    handlers.append(_set_wallpaper_feh)
    handlers.append(_set_wallpaper_xwallpaper)

    return handlers


def _hide_taskbar_desktop_specific() -> bool:
    desktops = _current_desktops()
    if _matches_desktop(desktops, {"gnome", "unity", "budgie", "pantheon"}):
        if _hide_taskbar_gnome():
            return True
    if _matches_desktop(desktops, {"kde", "plasma"}):
        if _hide_taskbar_plasma():
            return True
    if _matches_desktop(desktops, {"xfce"}):
        if _hide_taskbar_xfce():
            return True
    return False


def _hide_taskbar_via_wmctrl() -> bool:
    wmctrl = shutil.which("wmctrl")
    if not wmctrl:
        LOGGER.debug("wmctrl nicht gefunden, kann Taskleiste nicht ausblenden")
        return False

    try:
        output = subprocess.check_output(
            [wmctrl, "-lG"], text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as exc:
        LOGGER.debug("wmctrl -lG fehlgeschlagen: %s", exc)
        return False

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
        return False

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

    if not hidden_any:
        LOGGER.debug("Ausblenden der Taskleiste per wmctrl fehlgeschlagen")
        return False

    return True


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


def _set_wallpaper_gnome(path: pathlib.Path) -> bool:
    if not shutil.which("gsettings"):
        return False

    uri = path.resolve().as_uri()
    success = False
    for schema in ("org.gnome.desktop.background", "org.gnome.desktop.screensaver"):
        for key in ("picture-uri", "picture-uri-dark"):
            if _gsettings_set(schema, key, uri):
                success = True
    return success


def _set_wallpaper_cinnamon(path: pathlib.Path) -> bool:
    if not shutil.which("gsettings"):
        return False

    uri = path.resolve().as_uri()
    success = False
    for key in ("picture-uri", "picture-uri-dark"):
        if _gsettings_set("org.cinnamon.desktop.background", key, uri):
            success = True
    return success


def _set_wallpaper_mate(path: pathlib.Path) -> bool:
    if not shutil.which("gsettings"):
        return False

    success = _gsettings_set(
        "org.mate.background",
        "picture-filename",
        str(path.resolve()),
    )
    success = (
        _gsettings_set("org.mate.background", "picture-options", "scaled")
        or success
    )
    return success


def _set_wallpaper_xfce(path: pathlib.Path) -> bool:
    xfconf = shutil.which("xfconf-query")
    if not xfconf:
        return False

    try:
        listing = subprocess.check_output(
            [xfconf, "-c", "xfce4-desktop", "-l"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return False

    monitors = {
        line.strip()
        for line in listing.splitlines()
        if "/last-image" in line or line.strip().endswith("/image-path")
    }
    if not monitors:
        return False

    success = False
    for prop in monitors:
        result = subprocess.run(
            [xfconf, "-c", "xfce4-desktop", "-p", prop, "-s", str(path.resolve())],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            success = True
    return success


def _set_wallpaper_plasma(path: pathlib.Path) -> bool:
    plasma_apply = shutil.which("plasma-apply-wallpaperimage")
    if plasma_apply:
        result = subprocess.run(
            [plasma_apply, str(path.resolve())],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return True

    qdbus = shutil.which("qdbus") or shutil.which("qdbus6")
    if not qdbus:
        return False

    uri = path.resolve().as_uri().replace("\"", "\\\"")
    script = """
var allDesktops = desktops();
for (var i = 0; i < allDesktops.length; i++) {
    var d = allDesktops[i];
    var config = d.wallpaperPlugin;
    d.wallpaperPlugin = "org.kde.image";
    d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    d.writeConfig("Image", "%s");
}
""" % uri
    result = subprocess.run(
        [qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _set_wallpaper_pcmanfm(path: pathlib.Path) -> bool:
    pcmanfm = shutil.which("pcmanfm") or shutil.which("pcmanfm-qt")
    if not pcmanfm:
        return False

    result = subprocess.run(
        [pcmanfm, "--set-wallpaper", str(path.resolve())],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _set_wallpaper_sway(path: pathlib.Path) -> bool:
    swaymsg = shutil.which("swaymsg")
    if not swaymsg:
        return False

    result = subprocess.run(
        [swaymsg, "output", "*", "bg", str(path.resolve()), "fill"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _set_wallpaper_feh(path: pathlib.Path) -> bool:
    feh = shutil.which("feh")
    if not feh:
        return False

    result = subprocess.run(
        [feh, "--bg-fill", str(path.resolve())],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        LOGGER.warning(
            "Setzen des Hintergrundbilds für %s fehlgeschlagen (Code %s)",
            path,
            result.returncode,
        )
        return False
    return True


def _set_wallpaper_xwallpaper(path: pathlib.Path) -> bool:
    xwallpaper = shutil.which("xwallpaper")
    if not xwallpaper:
        return False

    result = subprocess.run(
        [xwallpaper, "--zoom", str(path.resolve())],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _hide_taskbar_gnome() -> bool:
    if not shutil.which("gsettings"):
        return False

    changed = False
    for schema, key, value in (
        ("org.gnome.shell.extensions.dash-to-dock", "dock-fixed", "false"),
        ("org.gnome.shell.extensions.dash-to-dock", "autohide", "true"),
        ("org.gnome.shell.extensions.dash-to-dock", "intellihide", "true"),
    ):
        if _gsettings_set(schema, key, value):
            changed = True

    return changed


def _hide_taskbar_plasma() -> bool:
    qdbus = shutil.which("qdbus") or shutil.which("qdbus6")
    if not qdbus:
        return False

    script = """
var allDesktops = desktops();
for (var i = 0; i < allDesktops.length; i++) {
    var panels = allDesktops[i].panels();
    for (var j = 0; j < panels.length; j++) {
        panels[j].hiding = "autohide";
    }
}
"""
    result = subprocess.run(
        [
            qdbus,
            "org.kde.plasmashell",
            "/PlasmaShell",
            "org.kde.PlasmaShell.evaluateScript",
            script,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _hide_taskbar_xfce() -> bool:
    xfconf = shutil.which("xfconf-query")
    if not xfconf:
        return False

    try:
        output = subprocess.check_output(
            [xfconf, "-c", "xfce4-panel", "-l"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return False

    panel_ids = {
        match.group(1)
        for line in output.splitlines()
        if (match := re.search(r"/panels/panel-(\d+)$", line.strip()))
    }
    if not panel_ids:
        return False

    success = False
    for panel_id in panel_ids:
        for prop, value in (
            (f"/panels/panel-{panel_id}/autohide", "1"),
            (f"/panels/panel-{panel_id}/autohide-behavior", "2"),
        ):
            result = subprocess.run(
                [xfconf, "-c", "xfce4-panel", "-p", prop, "-s", value],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                success = True
    return success


def _gsettings_set(schema: str, key: str, value: str) -> bool:
    gsettings = shutil.which("gsettings")
    if not gsettings:
        return False

    result = subprocess.run(
        [gsettings, "set", schema, key, value],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        LOGGER.debug(
            "gsettings set %s %s fehlgeschlagen (%s)", schema, key, result.returncode
        )
        return False
    return True


@lru_cache(maxsize=1)
def _current_desktops() -> tuple[str, ...]:
    desktops: list[str] = []
    for env in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "GDMSESSION"):
        raw = os.environ.get(env)
        if not raw:
            continue
        for part in raw.split(":"):
            token = part.strip().lower()
            if token and token not in desktops:
                desktops.append(token)
    return tuple(desktops)


def _matches_desktop(desktops: Iterable[str], candidates: set[str]) -> bool:
    return any(desktop in candidates for desktop in desktops)


def _is_wayland_sway() -> bool:
    return bool(os.environ.get("SWAYSOCK"))
