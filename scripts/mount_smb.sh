#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Dieses Skript muss als root ausgeführt werden." >&2
  exit 1
fi

ACTION=${1:-}
case "$ACTION" in
  mount)
    SHARE=${2:-}
    TARGET=${3:-}
    OPTIONS=${4:-}
    if [[ -z "$SHARE" || -z "$TARGET" ]]; then
      echo "Verwendung: $0 mount //<server>/<share> <mountpoint> [options]" >&2
      exit 1
    fi
    /bin/mount -t cifs "$SHARE" "$TARGET" -o "$OPTIONS"
    ;;
  umount|unmount)
    TARGET=${2:-}
    if [[ -z "$TARGET" ]]; then
      echo "Verwendung: $0 umount <mountpoint>" >&2
      exit 1
    fi
    /bin/umount "$TARGET"
    ;;
  *)
    echo "Unbekannte Aktion: $ACTION" >&2
    echo "Verwendung: $0 mount|umount ..." >&2
    exit 1
    ;;
esac
