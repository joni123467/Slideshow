#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/slideshow"
VENV_DIR="$APP_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/slideshow.service"
REPO_URL_DEFAULT="${REPO_URL:-$(git config --get remote.origin.url 2>/dev/null || echo "https://github.com/example/slideshow.git")}"
BRANCH_DEFAULT="${BRANCH:-main}"

if [[ $EUID -ne 0 ]]; then
  echo "Dieses Skript muss als root ausgeführt werden." >&2
  exit 1
fi

read -rp "Git-Repository-URL [$REPO_URL_DEFAULT]: " REPO_URL_INPUT
REPO_URL="${REPO_URL_INPUT:-$REPO_URL_DEFAULT}"

default_branch() {
  local url="$1"
  if command -v git >/dev/null 2>&1; then
    git ls-remote --symref "$url" HEAD 2>/dev/null | awk '/^ref:/ {print $2}' | sed 's#refs/heads/##'
  fi
}

DEFAULT_BRANCH_REMOTE=$(default_branch "$REPO_URL")
if [[ -n "$DEFAULT_BRANCH_REMOTE" ]]; then
  BRANCH_DEFAULT="$DEFAULT_BRANCH_REMOTE"
fi

read -rp "Branch [$BRANCH_DEFAULT]: " BRANCH_INPUT
BRANCH="${BRANCH_INPUT:-$BRANCH_DEFAULT}"

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

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3 python3-venv python3-pip rsync cifs-utils feh mpv

if id -u "$USER_NAME" >/dev/null 2>&1; then
  echo "Benutzer $USER_NAME existiert bereits."
else
  useradd --create-home --system "$USER_NAME"
fi

echo "$USER_NAME:$USER_PASSWORD" | chpasswd

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"

git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"

cat <<BRANCH > "$APP_DIR/.install_branch"
$BRANCH
BRANCH

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
if [[ -f "$APP_DIR/pyproject.toml" ]]; then
  "$VENV_DIR/bin/pip" install poetry
  (cd "$APP_DIR" && "$VENV_DIR/bin/poetry" install --no-root)
elif [[ -f "$APP_DIR/requirements.txt" ]]; then
  "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
fi

cat <<SERVICE > "$SERVICE_FILE"
[Unit]
Description=Slideshow Service
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_DIR/bin/python manage.py run --host 0.0.0.0 --port 8080
Restart=on-failure

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now slideshow.service

chown -R "$USER_NAME":"$USER_NAME" "$APP_DIR"

cat <<INFO
Installation abgeschlossen.
Repository: $REPO_URL
Branch: $BRANCH
Dienstbenutzer: $USER_NAME
INFO
