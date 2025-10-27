#!/usr/bin/env bash
set -euo pipefail

# REPO_SLUG: joni123467/Slideshow

usage() {
  cat <<'EOF'
Verwendung: install.sh [--desktop-user NAME]

Optionen:
  --desktop-user NAME  Legt das Benutzerkonto fest, unter dem Dienst und Desktop laufen.
  --help               Zeigt diese Hilfe an.
EOF
}

DESKTOP_USER_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
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

APP_DIR="/opt/slideshow"
VENV_DIR="$APP_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/slideshow.service"
RUN_USER_FILE="$APP_DIR/.run_user"
LIGHTDM_AUTLOGIN_CONF="/etc/lightdm/lightdm.conf.d/50-slideshow-autologin.conf"

configure_lightdm_autologin() {
  local user="$1"
  if [[ -d /etc/lightdm ]]; then
    local conf_dir="$(dirname "$LIGHTDM_AUTLOGIN_CONF")"
    mkdir -p "$conf_dir"
    cat <<CONF > "$LIGHTDM_AUTLOGIN_CONF"
[Seat:*]
autologin-user=$user
autologin-user-timeout=0
autologin-session=lightdm-autologin
CONF
    echo "LightDM-Autologin für $user konfiguriert."
  else
    echo "Hinweis: LightDM wurde nicht gefunden, Autologin konnte nicht gesetzt werden." >&2
  fi
}

enable_user_linger() {
  local user="$1"
  if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "$user" || echo "Warnung: Konnte loginctl enable-linger für $user nicht setzen." >&2
  else
    echo "Hinweis: loginctl nicht gefunden, Linger konnte nicht gesetzt werden." >&2
  fi
}

ensure_virtualenv() {
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    python3 -m venv "$VENV_DIR"
  fi
}

install_python_dependencies() {
  ensure_virtualenv
  local python_bin="$VENV_DIR/bin/python"
  local pip_bin="$VENV_DIR/bin/pip"
  if [[ ! -x "$pip_bin" && -x "$python_bin" ]]; then
    "$python_bin" -m ensurepip --upgrade
    pip_bin="$VENV_DIR/bin/pip"
  fi
  if [[ ! -x "$pip_bin" ]]; then
    echo "Konnte pip im virtuellen Environment nicht finden." >&2
    return 1
  fi
  "$pip_bin" install --upgrade pip setuptools wheel
  if [[ -f "$APP_DIR/pyproject.toml" ]]; then
    "$pip_bin" install poetry
    (cd "$APP_DIR" && "$VENV_DIR/bin/poetry" install --no-root)
  elif [[ -f "$APP_DIR/requirements.txt" ]]; then
    "$pip_bin" install -r "$APP_DIR/requirements.txt"
  fi
}

if [[ $EUID -ne 0 ]]; then
  echo "Dieses Skript muss als root ausgeführt werden." >&2
  exit 1
fi

echo "Installationsmodus: Desktop (X11)"

REPO_SLUG=$(grep -m1 '^# REPO_SLUG:' "$0" | awk -F':' '{print $2}' | xargs)
REPO_SLUG="${REPO_SLUG:-${SLIDESHOW_REPO_SLUG:-joni123467/Slideshow}}"
REPO_URL="https://github.com/${REPO_SLUG}.git"

export DEBIAN_FRONTEND=noninteractive
apt-get update
COMMON_PACKAGES=(
  git
  python3
  python3-venv
  python3-pip
  rsync
  cifs-utils
  ffmpeg
  mpv
  feh
  curl
  ca-certificates
  x11-xserver-utils
  fonts-dejavu-core
  smartmontools
  nvme-cli
)
apt-get install -y "${COMMON_PACKAGES[@]}"

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

DEFAULT_RUN_USER="${SLIDESHOW_DESKTOP_USER:-${SUDO_USER:-}}"
if [[ -n "$DESKTOP_USER_ARG" ]]; then
  USER_NAME="$DESKTOP_USER_ARG"
else
  if [[ -n "$DEFAULT_RUN_USER" ]]; then
    read -rp "Benutzerkonto für Dienststart [$DEFAULT_RUN_USER]: " USER_NAME_INPUT
    USER_NAME="${USER_NAME_INPUT:-$DEFAULT_RUN_USER}"
  else
    read -rp "Benutzerkonto für Dienststart: " USER_NAME_INPUT
    USER_NAME="${USER_NAME_INPUT:-}"
  fi
fi

if [[ -z "$USER_NAME" ]]; then
  echo "Es muss ein Benutzerkonto angegeben werden." >&2
  exit 1
fi

if ! id -u "$USER_NAME" >/dev/null 2>&1; then
  echo "Benutzer $USER_NAME wurde nicht gefunden. Bitte vorab anlegen und für die Desktop-Sitzung verwenden." >&2
  exit 1
fi

echo "Verwende bestehenden Benutzer $USER_NAME für Dienst und Desktop-Integration."

GROUP_ADDED=()
GROUP_MISSING=()
for supplemental_group in video render input; do
  if getent group "$supplemental_group" >/dev/null 2>&1; then
    if id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx "$supplemental_group"; then
      continue
    fi
    usermod -aG "$supplemental_group" "$USER_NAME"
    GROUP_ADDED+=("$supplemental_group")
  else
    GROUP_MISSING+=("$supplemental_group")
  fi
done

USER_UID="$(id -u "$USER_NAME")"
SERVICE_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
if [[ -z "$SERVICE_HOME" ]]; then
  echo "Konnte Home-Verzeichnis für $USER_NAME nicht bestimmen." >&2
  exit 1
fi

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"

git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"

printf '%s\n' "$USER_NAME" > "$RUN_USER_FILE"

cat <<BRANCH > "$APP_DIR/.install_branch"
$BRANCH
BRANCH

cat <<REPO > "$APP_DIR/.install_repo"
$REPO_SLUG
REPO

for helper_script in update.sh mount_smb.sh system_diagnostics.sh; do
  chmod +x "$APP_DIR/scripts/$helper_script" 2>/dev/null || true
done

SUDOERS_FILE="/etc/sudoers.d/slideshow"
SYSTEMCTL_BIN="$(command -v systemctl || echo /bin/systemctl)"
REBOOT_BIN="$(command -v reboot || echo /sbin/reboot)"
POWEROFF_BIN="$(command -v poweroff || echo /sbin/poweroff)"
SMARTCTL_BIN="$(command -v smartctl || echo /usr/sbin/smartctl)"
SYSTEM_DIAG_SCRIPT="$APP_DIR/scripts/system_diagnostics.sh"
cat <<SUDOERS > "$SUDOERS_FILE"
$USER_NAME ALL=(root) NOPASSWD: $APP_DIR/scripts/update.sh *
$USER_NAME ALL=(root) NOPASSWD: $APP_DIR/scripts/mount_smb.sh *
$USER_NAME ALL=(root) NOPASSWD: $SYSTEM_DIAG_SCRIPT *
$USER_NAME ALL=(root) NOPASSWD: $SYSTEMCTL_BIN is-active slideshow.service
$USER_NAME ALL=(root) NOPASSWD: $SYSTEMCTL_BIN start slideshow.service
$USER_NAME ALL=(root) NOPASSWD: $SYSTEMCTL_BIN stop slideshow.service
$USER_NAME ALL=(root) NOPASSWD: $SYSTEMCTL_BIN restart slideshow.service
$USER_NAME ALL=(root) NOPASSWD: $REBOOT_BIN
$USER_NAME ALL=(root) NOPASSWD: $POWEROFF_BIN
$USER_NAME ALL=(root) NOPASSWD: $SMARTCTL_BIN *
SUDOERS
chmod 440 "$SUDOERS_FILE"

install_python_dependencies

RUNTIME_NAME="slideshow-$USER_UID"
RUNTIME_DIR="/run/$RUNTIME_NAME"

XAUTHORITY_PATH="$SERVICE_HOME/.Xauthority"
if [[ ! -f "$XAUTHORITY_PATH" ]]; then
  echo "WARNUNG: Erwartete Xauthority-Datei $XAUTHORITY_PATH wurde nicht gefunden."
fi

UNIT_AFTER="After=display-manager.service graphical.target network-online.target"
UNIT_REQUIRES="Requires=display-manager.service"
UNIT_WANTS=("Wants=network-online.target")
UNIT_INSTALL="WantedBy=graphical.target"
SERVICE_ENV=(
  "Environment=PYTHONUNBUFFERED=1"
  "Environment=XDG_RUNTIME_DIR=$RUNTIME_DIR"
  "Environment=DISPLAY=:0"
  "Environment=XAUTHORITY=$XAUTHORITY_PATH"
  "Environment=HOME=$SERVICE_HOME"
)

{
  echo "[Unit]"
  echo "Description=Slideshow Service"
  echo "$UNIT_AFTER"
  echo "$UNIT_REQUIRES"
  for want in "${UNIT_WANTS[@]}"; do
    echo "$want"
  done
  echo ""
  echo "[Service]"
  echo "Type=simple"
  echo "User=$USER_NAME"
  echo "WorkingDirectory=$APP_DIR"
  echo "RuntimeDirectory=$RUNTIME_NAME"
  echo "RuntimeDirectoryMode=0700"
  for env in "${SERVICE_ENV[@]}"; do
    echo "$env"
  done
  echo "ExecStartPre=/bin/sh -c 'DISPLAY=:0 XAUTHORITY=$XAUTHORITY_PATH xset q >/dev/null 2>&1 || true'"
  echo "ExecStart=$VENV_DIR/bin/python manage.py run --host 0.0.0.0 --port 8080"
  echo "ExecStartPost=/bin/sh -c 'echo \"Slideshow mit DISPLAY=\$DISPLAY gestartet\" | systemd-cat -t slideshow'"
  echo "Restart=always"
  echo "RestartSec=5"
  echo ""
  echo "[Install]"
  echo "$UNIT_INSTALL"
} > "$SERVICE_FILE"

configure_lightdm_autologin "$USER_NAME"
enable_user_linger "$USER_NAME"

systemctl daemon-reload
systemctl enable --now slideshow.service

chown -R "$USER_NAME":"$USER_NAME" "$APP_DIR"

GROUP_SUMMARY="Keine zusätzlichen Gruppen ergänzt."
if [[ ${#GROUP_ADDED[@]} -gt 0 ]]; then
  GROUP_SUMMARY="Benutzerkonto zu folgenden Geräte-Gruppen hinzugefügt: ${GROUP_ADDED[*]}"
fi
GROUP_MISSING_NOTICE=""
if [[ ${#GROUP_MISSING[@]} -gt 0 ]]; then
  GROUP_MISSING_NOTICE="Fehlende Systemgruppen bitte manuell prüfen: ${GROUP_MISSING[*]}"
fi

cat <<INFO
Installation abgeschlossen.
Repository: $REPO_URL
Branch: $BRANCH
Dienst-/Desktop-Benutzer: $USER_NAME
$GROUP_SUMMARY
${GROUP_MISSING_NOTICE:-}
INFO
