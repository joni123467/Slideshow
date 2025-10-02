#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/slideshow"
VENV_DIR="$APP_DIR/.venv"
BRANCH_FILE="$APP_DIR/.install_branch"
BRANCH="${1:-}"

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

echo "Aktualisiere Branch $BRANCH"

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "Kein Git-Repository in $APP_DIR gefunden." >&2
  exit 1
fi

(cd "$APP_DIR" && git fetch --all)
(cd "$APP_DIR" && git checkout "$BRANCH")
(cd "$APP_DIR" && git pull --ff-only origin "$BRANCH")

echo "$BRANCH" > "$BRANCH_FILE"

if [[ -f "$APP_DIR/pyproject.toml" ]]; then
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install poetry
  (cd "$APP_DIR" && "$VENV_DIR/bin/poetry" install --no-root)
elif [[ -f "$APP_DIR/requirements.txt" ]]; then
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
fi

systemctl daemon-reload || true
systemctl restart slideshow.service || true

echo "Update abgeschlossen."
