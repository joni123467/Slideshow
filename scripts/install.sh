diff --git a/scripts/install.sh b/scripts/install.sh
index a18bfab8262eeb222b15315ff7a8ba72be72ab09..02a8f3cef65411a7b83ecc09d0aa5e598f5ca5dd 100755
--- a/scripts/install.sh
+++ b/scripts/install.sh
@@ -1,107 +1,79 @@
 #!/usr/bin/env bash
 set -euo pipefail
 
 # REPO_SLUG: joni123467/Slideshow
 
 usage() {
   cat <<'EOF'
-Verwendung: install.sh [--drm] [--video-backend NAME] [--desktop-user NAME] [--service-user NAME]
+Verwendung: install.sh [--desktop-user NAME]
 
 Optionen:
-  --drm                Aktiviert die Framebuffer-/DRM-Ausgabe (kein Desktop erforderlich).
-  --video-backend NAME Setzt das Backend explizit auf "x11" oder "drm".
   --desktop-user NAME  Legt das Benutzerkonto fest, unter dem Dienst und Desktop laufen.
   --help               Zeigt diese Hilfe an.
 EOF
 }
 
-VIDEO_BACKEND="${SLIDESHOW_VIDEO_BACKEND:-x11}"
 DESKTOP_USER_ARG=""
-SERVICE_USER_ARG=""
 
 while [[ $# -gt 0 ]]; do
   case "$1" in
-    --drm)
-      VIDEO_BACKEND="drm"
-      shift
-      ;;
-    --video-backend)
-      VIDEO_BACKEND="${2:-}"
-      shift 2 || { echo "--video-backend benötigt einen Wert" >&2; exit 1; }
-      ;;
     --desktop-user)
       DESKTOP_USER_ARG="${2:-}"
       shift 2 || { echo "--desktop-user benötigt einen Wert" >&2; exit 1; }
       ;;
-    --service-user)
-      SERVICE_USER_ARG="${2:-}"
-      shift 2 || { echo "--service-user benötigt einen Wert" >&2; exit 1; }
-      ;;
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
 
-VIDEO_BACKEND="${VIDEO_BACKEND,,}"
-if [[ "$VIDEO_BACKEND" != "drm" && "$VIDEO_BACKEND" != "x11" ]]; then
-  echo "Unbekanntes Backend '$VIDEO_BACKEND', verwende x11." >&2
-  VIDEO_BACKEND="x11"
-fi
-
 APP_DIR="/opt/slideshow"
 VENV_DIR="$APP_DIR/.venv"
 SERVICE_FILE="/etc/systemd/system/slideshow.service"
 
 if [[ $EUID -ne 0 ]]; then
   echo "Dieses Skript muss als root ausgeführt werden." >&2
   exit 1
 fi
 
-echo "Installationsmodus: Backend=$VIDEO_BACKEND"
+echo "Installationsmodus: Desktop (X11)"
 
 REPO_SLUG=$(grep -m1 '^# REPO_SLUG:' "$0" | awk -F':' '{print $2}' | xargs)
 REPO_SLUG="${REPO_SLUG:-${SLIDESHOW_REPO_SLUG:-joni123467/Slideshow}}"
 REPO_URL="https://github.com/${REPO_SLUG}.git"
 
 export DEBIAN_FRONTEND=noninteractive
 apt-get update
-COMMON_PACKAGES=(git python3 python3-venv python3-pip rsync cifs-utils ffmpeg mpv feh curl ca-certificates)
-EXTRA_PACKAGES=()
-if [[ "$VIDEO_BACKEND" == "x11" ]]; then
-  EXTRA_PACKAGES+=(x11-xserver-utils)
-else
-  EXTRA_PACKAGES+=(mesa-utils libdrm2 libgbm1)
-fi
-apt-get install -y "${COMMON_PACKAGES[@]}" "${EXTRA_PACKAGES[@]}"
+COMMON_PACKAGES=(git python3 python3-venv python3-pip rsync cifs-utils ffmpeg mpv feh curl ca-certificates x11-xserver-utils)
+apt-get install -y "${COMMON_PACKAGES[@]}"
 
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
diff --git a/scripts/install.sh b/scripts/install.sh
index a18bfab8262eeb222b15315ff7a8ba72be72ab09..02a8f3cef65411a7b83ecc09d0aa5e598f5ca5dd 100755
--- a/scripts/install.sh
+++ b/scripts/install.sh
@@ -118,192 +90,152 @@ BRANCH="${SLIDESHOW_BRANCH:-$(determine_latest_branch "$REPO_URL")}"
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
 
-DESKTOP_USER=""
-if [[ "$VIDEO_BACKEND" == "x11" ]]; then
-  DESKTOP_USER="$USER_NAME"
-fi
-if [[ "$VIDEO_BACKEND" == "drm" ]]; then
-  echo "DRM-Modus: Desktop-Integration optional, Dienst läuft trotzdem als $USER_NAME."
-fi
-
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
 
 cat <<BRANCH > "$APP_DIR/.install_branch"
 $BRANCH
 BRANCH
 
-chmod +x "$APP_DIR/scripts/update.sh" "$APP_DIR/scripts/mount_smb.sh" "$APP_DIR/scripts/prestart.sh" 2>/dev/null || true
+chmod +x "$APP_DIR/scripts/update.sh" "$APP_DIR/scripts/mount_smb.sh" 2>/dev/null || true
 
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
 
-DESKTOP_HOME=""
-XAUTHORITY_PATH=""
-XAUTHORITY_SOURCE=""
-XAUTHORITY_WARNING=0
-if [[ -n "$DESKTOP_USER" ]]; then
-  XAUTHORITY_PATH="$SERVICE_HOME/.Xauthority"
-  DESKTOP_HOME="$(getent passwd "$DESKTOP_USER" | cut -d: -f6)"
-  if [[ -z "$DESKTOP_HOME" ]]; then
-    echo "Hinweis: Desktop-Benutzer $DESKTOP_USER wurde nicht gefunden."
-    DESKTOP_USER=""
-    XAUTHORITY_PATH=""
-  elif [[ -f "$DESKTOP_HOME/.Xauthority" ]]; then
-    XAUTHORITY_SOURCE="$DESKTOP_HOME/.Xauthority"
-    echo "Xauthority von $DESKTOP_USER wird beim Dienststart synchronisiert."
-  else
-    echo "WARNUNG: Keine .Xauthority bei $DESKTOP_USER gefunden."
-    XAUTHORITY_WARNING=1
-  fi
-fi
-
-if [[ -z "$XAUTHORITY_SOURCE" && -n "$DESKTOP_USER" ]]; then
-  XAUTHORITY_WARNING=1
-fi
-
 RUNTIME_NAME="slideshow-$USER_UID"
 RUNTIME_DIR="/run/$RUNTIME_NAME"
 
-UNIT_AFTER="After=network-online.target"
+XAUTHORITY_PATH="$SERVICE_HOME/.Xauthority"
+if [[ ! -f "$XAUTHORITY_PATH" ]]; then
+  echo "WARNUNG: Erwartete Xauthority-Datei $XAUTHORITY_PATH wurde nicht gefunden."
+fi
+
+UNIT_AFTER="After=display-manager.service graphical.target network-online.target"
+UNIT_REQUIRES="Requires=display-manager.service"
 UNIT_WANTS=("Wants=network-online.target")
-UNIT_INSTALL="WantedBy=multi-user.target"
+UNIT_INSTALL="WantedBy=graphical.target"
 SERVICE_ENV=(
   "Environment=PYTHONUNBUFFERED=1"
   "Environment=XDG_RUNTIME_DIR=$RUNTIME_DIR"
-  "Environment=SLIDESHOW_SERVICE_USER=$USER_NAME"
-  "Environment=SLIDESHOW_VIDEO_BACKEND=$VIDEO_BACKEND"
-  "Environment=SLIDESHOW_IMAGE_BACKEND=$VIDEO_BACKEND"
+  "Environment=DISPLAY=:0"
+  "Environment=XAUTHORITY=$XAUTHORITY_PATH"
+  "Environment=HOME=$SERVICE_HOME"
 )
-if [[ -n "$XAUTHORITY_SOURCE" ]]; then
-  SERVICE_ENV+=("Environment=SLIDESHOW_XAUTHORITY_SOURCE=$XAUTHORITY_SOURCE")
-fi
-if [[ -n "$DESKTOP_USER" ]]; then
-  UNIT_AFTER+=" graphical.target"
-  UNIT_WANTS+=("Wants=graphical.target")
-  UNIT_INSTALL="WantedBy=graphical.target"
-  SERVICE_ENV+=("Environment=DISPLAY=:0" "Environment=XAUTHORITY=$XAUTHORITY_PATH")
-fi
 
 {
   echo "[Unit]"
   echo "Description=Slideshow Service"
   echo "$UNIT_AFTER"
+  echo "$UNIT_REQUIRES"
   for want in "${UNIT_WANTS[@]}"; do
     echo "$want"
   done
   echo ""
   echo "[Service]"
   echo "Type=simple"
   echo "User=$USER_NAME"
   echo "WorkingDirectory=$APP_DIR"
   echo "RuntimeDirectory=$RUNTIME_NAME"
-  echo "PermissionsStartOnly=yes"
+  echo "RuntimeDirectoryMode=0700"
   for env in "${SERVICE_ENV[@]}"; do
     echo "$env"
   done
-  echo "ExecStartPre=$APP_DIR/scripts/prestart.sh"
+  echo "ExecStartPre=/bin/sh -c 'DISPLAY=:0 XAUTHORITY=$XAUTHORITY_PATH xset q >/dev/null 2>&1 || true'"
   echo "ExecStart=$VENV_DIR/bin/python manage.py run --host 0.0.0.0 --port 8080"
-  echo "ExecStartPost=/bin/sh -c 'if [ -n \"\$DISPLAY\" ]; then echo \"Slideshow mit DISPLAY=\$DISPLAY gestartet (Backend: \$SLIDESHOW_VIDEO_BACKEND)\" | systemd-cat -t slideshow; else echo \"Slideshow im Headless-Modus gestartet\" | systemd-cat -t slideshow; fi'"
+  echo "ExecStartPost=/bin/sh -c 'echo \"Slideshow mit DISPLAY=\$DISPLAY gestartet\" | systemd-cat -t slideshow'"
   echo "Restart=on-failure"
   echo "RestartSec=5"
   echo ""
   echo "[Install]"
   echo "$UNIT_INSTALL"
 } > "$SERVICE_FILE"
 
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
 
-if [[ "$XAUTHORITY_WARNING" -eq 1 ]]; then
-  echo "WARNUNG: Keine gültige Xauthority-Datei gefunden. Stellen Sie sicher, dass $USER_NAME Zugriff auf die grafische Sitzung hat (DISPLAY=:0)."
-fi
-
 cat <<INFO
 Installation abgeschlossen.
 Repository: $REPO_URL
 Branch: $BRANCH
 Dienst-/Desktop-Benutzer: $USER_NAME
-Video-Backend: $VIDEO_BACKEND
-Desktop-Anzeige: ${DESKTOP_USER:-keine}
 $GROUP_SUMMARY
 ${GROUP_MISSING_NOTICE:-}
 INFO
