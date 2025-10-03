#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[slideshow-prestart] $*" >&2
}

SERVICE_USER="${SLIDESHOW_SERVICE_USER:-}"
if [[ -z "$SERVICE_USER" ]]; then
  SERVICE_USER="$(id -un)"
fi

if [[ -n "${SLIDESHOW_XAUTHORITY_SOURCE:-}" && -n "${XAUTHORITY:-}" ]]; then
  if [[ -f "$SLIDESHOW_XAUTHORITY_SOURCE" ]]; then
    install -m 600 -o "$SERVICE_USER" -g "$SERVICE_USER" "$SLIDESHOW_XAUTHORITY_SOURCE" "$XAUTHORITY"
    log "Xauthority von $SLIDESHOW_XAUTHORITY_SOURCE nach $XAUTHORITY synchronisiert."
  else
    log "Warnung: Xauthority-Quelle $SLIDESHOW_XAUTHORITY_SOURCE wurde nicht gefunden."
  fi
fi

if [[ -z "${DISPLAY:-}" ]]; then
  log "Kein DISPLAY gesetzt – headless Start."
  exit 0
fi

if ! command -v xset >/dev/null 2>&1; then
  log "xset nicht verfügbar – überspringe Anzeigeprüfung."
  exit 0
fi

CHECK_OK=0
for _ in $(seq 1 15); do
  if command -v runuser >/dev/null 2>&1; then
    if runuser -u "$SERVICE_USER" -- env DISPLAY="$DISPLAY" XAUTHORITY="${XAUTHORITY:-}" xset q >/dev/null 2>&1; then
      CHECK_OK=1
      break
    fi
  elif command -v su >/dev/null 2>&1; then
    if su -s /bin/sh "$SERVICE_USER" -c "DISPLAY='$DISPLAY' XAUTHORITY='${XAUTHORITY:-}' xset q" >/dev/null 2>&1; then
      CHECK_OK=1
      break
    fi
  else
    log "Weder runuser noch su verfügbar – überspringe Anzeigeprüfung."
    CHECK_OK=1
    break
  fi
  sleep 2
done

if [[ "$CHECK_OK" -eq 1 ]]; then
  log "Display $DISPLAY ist erreichbar."
else
  log "Display $DISPLAY blieb unerreichbar; Dienst startet dennoch."
fi

exit 0
