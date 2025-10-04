#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/slideshow"
VENV_DIR="$APP_DIR/.venv"
BRANCH_FILE="$APP_DIR/.install_branch"
REPO_FILE="$APP_DIR/.install_repo"
RUN_USER_FILE="$APP_DIR/.run_user"
SERVICE_FILE="/etc/systemd/system/slideshow.service"
BRANCH="${1:-}"

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
    echo "LightDM-Autologin für $user aktualisiert."
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

determine_run_user() {
  local user=""
  if [[ -f "$RUN_USER_FILE" ]]; then
    user=$(tr -d '\n' < "$RUN_USER_FILE")
  fi
  if [[ -z "$user" && -f "$SERVICE_FILE" ]]; then
    user=$(awk -F'=' '/^User=/ {print $2}' "$SERVICE_FILE" | tail -n1)
  fi
  printf '%s' "$user"
}

render_systemd_unit() {
  local user="$1"
  if [[ -z "$user" ]]; then
    echo "Warnung: Kein Benutzername für die Service-Unit übergeben." >&2
    return 1
  fi
  if ! id -u "$user" >/dev/null 2>&1; then
    echo "Warnung: Benutzer $user existiert nicht mehr." >&2
    return 1
  fi
  local uid
  uid=$(id -u "$user")
  local home
  home=$(getent passwd "$user" | cut -d: -f6)
  if [[ -z "$home" ]]; then
    echo "Warnung: Konnte Home-Verzeichnis für $user nicht bestimmen." >&2
    return 1
  fi
  local runtime_name="slideshow-$uid"
  local runtime_dir="/run/$runtime_name"
  local xauthority_path="$home/.Xauthority"
  local service_env=(
    "Environment=PYTHONUNBUFFERED=1"
    "Environment=XDG_RUNTIME_DIR=$runtime_dir"
    "Environment=DISPLAY=:0"
    "Environment=XAUTHORITY=$xauthority_path"
    "Environment=HOME=$home"
  )
  local unit_after="After=display-manager.service graphical.target network-online.target"
  local unit_requires="Requires=display-manager.service"
  local unit_wants=("Wants=network-online.target")
  local unit_install="WantedBy=graphical.target"
  {
    echo "[Unit]"
    echo "Description=Slideshow Service"
    echo "$unit_after"
    echo "$unit_requires"
    for want in "${unit_wants[@]}"; do
      echo "$want"
    done
    echo ""
    echo "[Service]"
    echo "Type=simple"
    echo "User=$user"
    echo "WorkingDirectory=$APP_DIR"
    echo "RuntimeDirectory=$runtime_name"
    echo "RuntimeDirectoryMode=0700"
    for env in "${service_env[@]}"; do
      echo "$env"
    done
    echo "ExecStartPre=/bin/sh -c 'DISPLAY=:0 XAUTHORITY=$xauthority_path xset q >/dev/null 2>&1 || true'"
    echo "ExecStart=$VENV_DIR/bin/python manage.py run --host 0.0.0.0 --port 8080"
    echo "ExecStartPost=/bin/sh -c 'echo \"Slideshow mit DISPLAY=\$DISPLAY gestartet\" | systemd-cat -t slideshow'"
    echo "Restart=always"
    echo "RestartSec=5"
    echo ""
    echo "[Install]"
    echo "$unit_install"
  } > "$SERVICE_FILE"
}

if [[ $EUID -ne 0 ]]; then
  echo "Dieses Skript muss als root ausgeführt werden." >&2
  exit 1
fi

if [[ -z "$BRANCH" && -f "$BRANCH_FILE" ]]; then
  BRANCH=$(cat "$BRANCH_FILE")
fi

if [[ -z "$BRANCH" ]]; then
  echo "Es muss ein Branch angegeben werden." >&2
  exit 1
fi

if [[ -f "$REPO_FILE" ]]; then
  REPO_SLUG=$(cat "$REPO_FILE")
fi
REPO_SLUG="${REPO_SLUG:-${SLIDESHOW_REPO_SLUG:-joni123467/Slideshow}}"

ARCHIVE_URL="https://codeload.github.com/${REPO_SLUG}/tar.gz/refs/heads/${BRANCH}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ARCHIVE_PATH="$TMP_DIR/source.tar.gz"

echo "Lade ${ARCHIVE_URL}"
if ! curl -fsSL "$ARCHIVE_URL" -o "$ARCHIVE_PATH"; then
  echo "Konnte Quellarchiv nicht herunterladen." >&2
  exit 1
fi

tar -xzf "$ARCHIVE_PATH" -C "$TMP_DIR"
SRC_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n1)"
if [[ -z "$SRC_DIR" || ! -d "$SRC_DIR" ]]; then
  echo "Entpacktes Archiv nicht gefunden." >&2
  exit 1
fi

rsync -a --delete \
  --exclude='.venv' \
  --exclude='.install_branch' \
  --exclude='.install_repo' \
  --exclude='.run_user' \
  "$SRC_DIR"/ "$APP_DIR"/

echo "$BRANCH" > "$BRANCH_FILE"
echo "$REPO_SLUG" > "$REPO_FILE"

if [[ -f "$APP_DIR/scripts/mount_smb.sh" ]]; then
  chmod +x "$APP_DIR/scripts/mount_smb.sh"
fi
if [[ -f "$APP_DIR/scripts/update.sh" ]]; then
  chmod +x "$APP_DIR/scripts/update.sh"
fi

if [[ -f "$APP_DIR/pyproject.toml" ]]; then
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install poetry
  (cd "$APP_DIR" && "$VENV_DIR/bin/poetry" install --no-root)
elif [[ -f "$APP_DIR/requirements.txt" ]]; then
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
fi

RUN_USER="$(determine_run_user)"
if [[ -n "$RUN_USER" ]]; then
  if [[ ! -f "$RUN_USER_FILE" ]]; then
    printf '%s\n' "$RUN_USER" > "$RUN_USER_FILE"
  fi
  configure_lightdm_autologin "$RUN_USER"
  enable_user_linger "$RUN_USER"
  if ! render_systemd_unit "$RUN_USER"; then
    echo "Warnung: Systemd-Unit konnte nicht aktualisiert werden." >&2
  fi
fi

systemctl daemon-reload || true
systemctl restart slideshow.service || true

echo "Update abgeschlossen."
