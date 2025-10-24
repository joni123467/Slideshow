#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-check}"
if [[ "$MODE" != "check" && "$MODE" != "repair" ]]; then
  echo "Ungültiger Modus: $MODE" >&2
  exit 2
fi

APP_DIR="/opt/slideshow"
DATA_DIR="${SLIDESHOW_DATA_DIR:-}"
if [[ -z "$DATA_DIR" ]]; then
  if [[ -f "$APP_DIR/.run_user" ]]; then
    RUN_USER="$(tr -d '\n' < "$APP_DIR/.run_user" 2>/dev/null || true)"
    if [[ -n "$RUN_USER" ]]; then
      USER_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
      if [[ -n "$USER_HOME" ]]; then
        DATA_DIR="$USER_HOME/.slideshow"
      fi
    fi
  fi
fi

if [[ -z "$DATA_DIR" ]]; then
  DATA_DIR="$HOME/.slideshow"
fi

LOG_DIR="$DATA_DIR/logs"
LOG_FILE="$LOG_DIR/diagnostics.log"
mkdir -p "$LOG_DIR"

TIMESTAMP="$(date --iso-8601=seconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
{
  echo "===== Systemdiagnose gestartet: $TIMESTAMP (Modus: $MODE) ====="
  echo "Host: $(hostname)"
  echo "Kernel: $(uname -sr)"
  echo "Uptime: $(uptime -p 2>/dev/null || uptime || true)"
  echo
  echo "Systemressourcen:"
  free -h || true
  echo
  echo "Datenträgerübersicht:"
  lsblk -o NAME,FSTYPE,SIZE,MOUNTPOINTS || true
  echo
  echo "Speicherbelegung:"
  df -h || true
  echo
  if command -v smartctl >/dev/null 2>&1; then
    echo "SMART-Überblick:"
    smartctl --scan-open || smartctl --scan || true
    mapfile -t SMART_DEVICES < <(smartctl --scan-open 2>/dev/null | awk '{print $1}')
    if [[ ${#SMART_DEVICES[@]} -eq 0 ]]; then
      mapfile -t SMART_DEVICES < <(smartctl --scan 2>/dev/null | awk '{print $1}')
    fi
    for device in "${SMART_DEVICES[@]}"; do
      [[ -z "$device" ]] && continue
      echo
      echo "### SMART-Daten für $device ###"
      smartctl -H -i -A "$device" || true
      smartctl -l selftest "$device" || true
      if [[ "$MODE" == "repair" ]]; then
        echo
        echo "Starte kurzen SMART-Selbsttest für $device"
        smartctl -t short "$device" || true
      fi
    done
  else
    echo "smartctl nicht gefunden. Bitte smartmontools installieren."
  fi
  echo
  if command -v fsck >/dev/null 2>&1; then
    if [[ "$MODE" == "repair" ]]; then
      echo "Starte Dateisystemprüfung mit Reparaturversuch (fsck -Af -y)"
      fsck -Af -y || true
    else
      echo "Starte Dateisystemprüfung im Lesemodus (fsck -AN)"
      fsck -AN || true
    fi
  else
    echo "fsck nicht gefunden."
  fi
  echo
  echo "Letzte Kernel-Meldungen:"
  dmesg | tail -n 200 || true
  echo
  echo "===== Systemdiagnose beendet: $(date --iso-8601=seconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S') ====="
  echo
} >> "$LOG_FILE" 2>&1
