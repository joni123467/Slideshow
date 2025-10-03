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
    SRC_CANON="$(realpath -m "$SLIDESHOW_XAUTHORITY_SOURCE")"
    DEST_CANON="$(realpath -m "$XAUTHORITY")"
    if [[ "$SRC_CANON" == "$DEST_CANON" ]]; then
      log "Xauthority-Quelle ($SRC_CANON) entspricht dem Ziel – keine Synchronisation erforderlich."
    else
      install -m 600 -o "$SERVICE_USER" -g "$SERVICE_USER" "$SLIDESHOW_XAUTHORITY_SOURCE" "$XAUTHORITY"
      log "Xauthority von $SLIDESHOW_XAUTHORITY_SOURCE nach $XAUTHORITY synchronisiert."
    fi
  else
    log "Warnung: Xauthority-Quelle $SLIDESHOW_XAUTHORITY_SOURCE wurde nicht gefunden."
  fi
fi

if [[ -z "${DISPLAY:-}" ]]; then
  log "Fehler: DISPLAY ist nicht gesetzt. Der Desktop muss aktiv sein."
  exit 1
fi

if ! command -v xset >/dev/null 2>&1; then
  log "Fehler: xset ist nicht verfügbar. Bitte Desktop-Paket x11-xserver-utils installieren."
  exit 1
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
  exit 0
fi

log "Fehler: Display $DISPLAY war nicht erreichbar."
exit 1
