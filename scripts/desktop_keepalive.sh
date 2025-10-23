#!/usr/bin/env bash
set -euo pipefail

# Sorgt dafür, dass der Desktop nicht automatisch gesperrt oder gedimmt wird.

DISPLAY_VALUE="${DISPLAY:-:0}"
export DISPLAY="$DISPLAY_VALUE"

if [[ -z "${XAUTHORITY:-}" ]]; then
  if [[ -n "${HOME:-}" && -f "$HOME/.Xauthority" ]]; then
    export XAUTHORITY="$HOME/.Xauthority"
  fi
fi

run_if_available() {
  local cmd="$1"
  shift || true
  if command -v "$cmd" >/dev/null 2>&1; then
    "$cmd" "$@" >/dev/null 2>&1 || true
  fi
}

run_if_available xset q
run_if_available xset s off
run_if_available xset s noblank
run_if_available xset -dpms
run_if_available xset s reset

pkill -f light-locker >/dev/null 2>&1 || true
pkill -f xscreensaver >/dev/null 2>&1 || true
pkill -f gnome-screensaver >/dev/null 2>&1 || true
pkill -f mate-screensaver >/dev/null 2>&1 || true
run_if_available xscreensaver-command -exit
run_if_available gsettings set org.gnome.desktop.screensaver lock-enabled false
run_if_available gsettings set org.gnome.desktop.session idle-delay 0
run_if_available gsettings set org.gnome.desktop.lockdown disable-lock-screen true

exit 0
