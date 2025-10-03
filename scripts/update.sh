#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/slideshow"
VENV_DIR="$APP_DIR/.venv"
BRANCH_FILE="$APP_DIR/.install_branch"
REPO_FILE="$APP_DIR/.install_repo"
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

systemctl daemon-reload || true
systemctl restart slideshow.service || true

echo "Update abgeschlossen."
