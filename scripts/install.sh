#!/usr/bin/env bash
set -euo pipefail

# REPO_SLUG: joni123467/Slideshow

usage() {
  cat <<'EOF'
Verwendung: install.sh [--drm] [--video-backend NAME] [--desktop-user NAME]

Optionen:
  --drm                Aktiviert die Framebuffer-/DRM-Ausgabe (kein Desktop erforderlich).
  --video-backend NAME Setzt das Backend explizit auf "x11" oder "drm".
  --desktop-user NAME  Überschreibt den Desktop-Benutzer für die X11-Anbindung.
  --help               Zeigt diese Hilfe an.
EOF
}

VIDEO_BACKEND="${SLIDESHOW_VIDEO_BACKEND:-x11}"
DESKTOP_USER_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --drm)
      VIDEO_BACKEND="drm"
      shift
      ;;
    --video-backend)
      VIDEO_BACKEND="${2:-}"
      shift 2 || { echo "--video-backend benötigt einen Wert" >&2; exit 1; }
      ;;
    --desktop-user)
      DESKTOP_USER_ARG="${2:-}"
      shift 2 || { echo "--desktop-user benötigt einen Wert" >&2; exit 1; }
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unbekannte Option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

VIDEO_BACKEND="${VIDEO_BACKEND,,}"
if [[ "$VIDEO_BACKEND" != "drm" && "$VIDEO_BACKEND" != "x11" ]]; then
  echo "Unbekanntes Backend '$VIDEO_BACKEND', verwende x11." >&2
  VIDEO_BACKEND="x11"
fi

APP_DIR="/opt/slideshow"
VENV_DIR="$APP_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/slideshow.service"

if [[ $EUID -ne 0 ]]; then
  echo "Dieses Skript muss als root ausgeführt werden." >&2
  exit 1
fi

echo "Installationsmodus: Backend=$VIDEO_BACKEND"

REPO_SLUG=$(grep -m1 '^# REPO_SLUG:' "$0" | awk -F':' '{print $2}' | xargs)
REPO_SLUG="${REPO_SLUG:-${SLIDESHOW_REPO_SLUG:-joni123467/Slideshow}}"
REPO_URL="https://github.com/${REPO_SLUG}.git"

export DEBIAN_FRONTEND=noninteractive
apt-get update
COMMON_PACKAGES=(git python3 python3-venv python3-pip rsync cifs-utils ffmpeg mpv feh curl ca-certificates)
EXTRA_PACKAGES=()
if [[ "$VIDEO_BACKEND" == "x11" ]]; then
  EXTRA_PACKAGES+=(x11-xserver-utils)
else
  EXTRA_PACKAGES+=(mesa-utils libdrm2 libgbm1)
fi
apt-get install -y "${COMMON_PACKAGES[@]}" "${EXTRA_PACKAGES[@]}"

determine_latest_branch() {
  local url="$1"
  local latest=""
  if git ls-remote --exit-code "$url" >/dev/null 2>&1; then
    local best_branch=""
    local best_version=""
    while IFS=$'\t' read -r _ ref; do
      local branch="${ref#refs/heads/}"
      if [[ "$branch" =~ ^version[[:space:]-]+([0-9]+(\.[0-9]+){1,3})$ ]]; then
        local candidate="${BASH_REMATCH[1]}"
        if [[ -z "$best_version" ]]; then
          best_version="$candidate"
          best_branch="$branch"
        else
          local newer
          newer=$(printf '%s\n%s\n' "$best_version" "$candidate" | sort -V | tail -n1)
          if [[ "$newer" == "$candidate" ]]; then
            best_version="$candidate"
            best_branch="$branch"
          fi
        fi
      fi
    done < <(git ls-remote --heads "$url")
    if [[ -n "$best_branch" ]]; then
      latest="$best_branch"
    else
      latest=$(git ls-remote --symref "$url" HEAD 2>/dev/null | awk '/^ref:/ {print $2}' | sed 's#refs/heads/##')
    fi
  fi
  echo "${latest:-main}"
}

BRANCH="${SLIDESHOW_BRANCH:-$(determine_latest_branch "$REPO_URL")}" 

read -rp "Dienstbenutzername [slideshow]: " USER_NAME_INPUT
USER_NAME="${USER_NAME_INPUT:-slideshow}"
read -srp "Passwort für $USER_NAME: " USER_PASSWORD
echo ""
read -srp "Passwort bestätigen: " USER_PASSWORD_CONFIRM
echo ""
if [[ "$USER_PASSWORD" != "$USER_PASSWORD_CONFIRM" ]]; then
  echo "Passwörter stimmen nicht überein." >&2
  exit 1
fi

if id -u "$USER_NAME" >/dev/null 2>&1; then
  echo "Benutzer $USER_NAME existiert bereits."
else
  useradd --create-home --system "$USER_NAME"
fi

echo "$USER_NAME:$USER_PASSWORD" | chpasswd

USER_UID="$(id -u "$USER_NAME")"
SERVICE_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
if [[ -z "$SERVICE_HOME" ]]; then
  echo "Konnte Home-Verzeichnis für $USER_NAME nicht bestimmen." >&2
  exit 1
fi

DEFAULT_DESKTOP_USER="${SLIDESHOW_DESKTOP_USER:-${SUDO_USER:-}}"
if [[ -n "$DESKTOP_USER_ARG" ]]; then
  DESKTOP_USER="$DESKTOP_USER_ARG"
else
  if [[ -n "$DEFAULT_DESKTOP_USER" ]]; then
    read -rp "Desktop-Benutzer für Anzeige [$DEFAULT_DESKTOP_USER]: " DESKTOP_USER_INPUT
    DESKTOP_USER="${DESKTOP_USER_INPUT:-$DEFAULT_DESKTOP_USER}"
  else
    if [[ "$VIDEO_BACKEND" == "drm" ]]; then
      read -rp "Desktop-Benutzer für Anzeige (leer lassen für headless): " DESKTOP_USER_INPUT
    else
      read -rp "Desktop-Benutzer für Anzeige (leer = keiner): " DESKTOP_USER_INPUT
    fi
    DESKTOP_USER="${DESKTOP_USER_INPUT:-}"
  fi
fi

if [[ "$VIDEO_BACKEND" == "drm" && -z "$DESKTOP_USER" ]]; then
  echo "DRM-Modus ohne Desktop-Benutzer: X11-Anbindung wird übersprungen."
fi

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"

git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"

cat <<BRANCH > "$APP_DIR/.install_branch"
$BRANCH
BRANCH

chmod +x "$APP_DIR/scripts/update.sh" "$APP_DIR/scripts/mount_smb.sh" 2>/dev/null || true

SUDOERS_FILE="/etc/sudoers.d/slideshow"
SYSTEMCTL_BIN="$(command -v systemctl || echo /bin/systemctl)"
REBOOT_BIN="$(command -v reboot || echo /sbin/reboot)"
POWEROFF_BIN="$(command -v poweroff || echo /sbin/poweroff)"
cat <<SUDOERS > "$SUDOERS_FILE"
$USER_NAME ALL=(root) NOPASSWD: $APP_DIR/scripts/update.sh *
$USER_NAME ALL=(root) NOPASSWD: $APP_DIR/scripts/mount_smb.sh *
$USER_NAME ALL=(root) NOPASSWD: $SYSTEMCTL_BIN is-active slideshow.service
$USER_NAME ALL=(root) NOPASSWD: $SYSTEMCTL_BIN start slideshow.service
$USER_NAME ALL=(root) NOPASSWD: $SYSTEMCTL_BIN stop slideshow.service
$USER_NAME ALL=(root) NOPASSWD: $SYSTEMCTL_BIN restart slideshow.service
$USER_NAME ALL=(root) NOPASSWD: $REBOOT_BIN
$USER_NAME ALL=(root) NOPASSWD: $POWEROFF_BIN
SUDOERS
chmod 440 "$SUDOERS_FILE"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
if [[ -f "$APP_DIR/pyproject.toml" ]]; then
  "$VENV_DIR/bin/pip" install poetry
  (cd "$APP_DIR" && "$VENV_DIR/bin/poetry" install --no-root)
elif [[ -f "$APP_DIR/requirements.txt" ]]; then
  "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
fi

DESKTOP_HOME=""
XAUTHORITY_PATH="$SERVICE_HOME/.Xauthority"
XAUTHORITY_WARNING=0
if [[ -n "$DESKTOP_USER" ]]; then
  DESKTOP_HOME="$(getent passwd "$DESKTOP_USER" | cut -d: -f6)"
  if [[ -z "$DESKTOP_HOME" ]]; then
    echo "Hinweis: Desktop-Benutzer $DESKTOP_USER wurde nicht gefunden."
    DESKTOP_USER=""
  elif [[ -f "$DESKTOP_HOME/.Xauthority" ]]; then
    install -m 600 -o "$USER_NAME" -g "$USER_NAME" "$DESKTOP_HOME/.Xauthority" "$XAUTHORITY_PATH"
    echo "Übernehme Xauthority von $DESKTOP_USER nach $XAUTHORITY_PATH"
  else
    echo "WARNUNG: Keine .Xauthority bei $DESKTOP_USER gefunden."
    XAUTHORITY_WARNING=1
  fi
fi

if [[ ! -f "$XAUTHORITY_PATH" ]]; then
  XAUTHORITY_WARNING=1
fi

RUNTIME_NAME="slideshow-$USER_UID"
RUNTIME_DIR="/run/$RUNTIME_NAME"

UNIT_AFTER="After=network-online.target"
UNIT_WANTS=("Wants=network-online.target")
UNIT_INSTALL="WantedBy=multi-user.target"
SERVICE_ENV=(
  "Environment=PYTHONUNBUFFERED=1"
  "Environment=XDG_RUNTIME_DIR=$RUNTIME_DIR"
  "Environment=SLIDESHOW_VIDEO_BACKEND=$VIDEO_BACKEND"
  "Environment=SLIDESHOW_IMAGE_BACKEND=$VIDEO_BACKEND"
)
if [[ -n "$DESKTOP_USER" ]]; then
  UNIT_AFTER+=" graphical.target"
  UNIT_WANTS+=("Wants=graphical.target")
  UNIT_INSTALL="WantedBy=graphical.target"
  SERVICE_ENV+=("Environment=DISPLAY=:0" "Environment=XAUTHORITY=$XAUTHORITY_PATH")
fi

{
  echo "[Unit]"
  echo "Description=Slideshow Service"
  echo "$UNIT_AFTER"
  for want in "${UNIT_WANTS[@]}"; do
    echo "$want"
  done
  echo ""
  echo "[Service]"
  echo "Type=simple"
  echo "User=$USER_NAME"
  echo "WorkingDirectory=$APP_DIR"
  echo "RuntimeDirectory=$RUNTIME_NAME"
  for env in "${SERVICE_ENV[@]}"; do
    echo "$env"
  done
  echo "ExecStartPre=/bin/sh -c 'if [ -n \"\$DISPLAY\" ]; then for i in \$(seq 1 10); do xset q >/dev/null 2>&1 && exit 0; sleep 2; done; echo \"Display \$DISPLAY nicht erreichbar\" >&2; exit 1; fi'"
  echo "ExecStart=$VENV_DIR/bin/python manage.py run --host 0.0.0.0 --port 8080"
  echo "Restart=on-failure"
  echo "RestartSec=5"
  echo ""
  echo "[Install]"
  echo "$UNIT_INSTALL"
} > "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable --now slideshow.service

chown -R "$USER_NAME":"$USER_NAME" "$APP_DIR"

if [[ "$XAUTHORITY_WARNING" -eq 1 ]]; then
  echo "WARNUNG: Keine gültige Xauthority-Datei gefunden. Stellen Sie sicher, dass $USER_NAME Zugriff auf die grafische Sitzung hat (DISPLAY=:0)."
fi

cat <<INFO
Installation abgeschlossen.
Repository: $REPO_URL
Branch: $BRANCH
Dienstbenutzer: $USER_NAME
Video-Backend: $VIDEO_BACKEND
Desktop-Anzeige: ${DESKTOP_USER:-keine}
INFO
