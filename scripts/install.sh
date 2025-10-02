#!/usr/bin/env bash
set -euo pipefail

# REPO_SLUG: SlideshowProject/Slideshow

APP_DIR="/opt/slideshow"
VENV_DIR="$APP_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/slideshow.service"

if [[ $EUID -ne 0 ]]; then
  echo "Dieses Skript muss als root ausgeführt werden." >&2
  exit 1
fi

REPO_SLUG=$(grep -m1 '^# REPO_SLUG:' "$0" | awk -F':' '{print $2}' | xargs)
REPO_SLUG="${REPO_SLUG:-${SLIDESHOW_REPO_SLUG:-SlideshowProject/Slideshow}}"
REPO_URL="https://github.com/${REPO_SLUG}.git"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3 python3-venv python3-pip rsync cifs-utils ffmpeg mpv feh curl ca-certificates

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
