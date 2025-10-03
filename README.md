# Slideshow für Raspberry Pi

Dieses Projekt stellt eine komplett verwaltete Slideshow-Anwendung für den Raspberry Pi bereit. Die Anwendung zeigt Bilder und Videos im Vollbildmodus an, kann lokale Verzeichnisse oder SMB-Freigaben als Quelle verwenden und bietet eine passwortgeschützte Weboberfläche, über die alle Einstellungen konfiguriert werden können.

## Funktionen

- **Automatisierte Wiedergabe** von Bildern und Videos über `mpv` (optional `feh` bzw. `omxplayer`), inklusive Infobildschirm bei Leerlauf.
- **Flexible Bilddarstellung**: Bilddauer, Skalierung (einpassen, strecken, Originalgröße), Rotation und Übergänge (Fade oder Slide) werden im Webinterface eingestellt.
- **Mehrere Medienquellen**: lokale Ordner oder SMB/CIFS-Freigaben, die automatisch eingehängt und in regelmäßigen Abständen gescannt werden.
- **Komfortable SMB-Einrichtung**: Freigaben lassen sich direkt per UNC-Pfad (z. B. `\\192.168.150.10\Software\RPI-Test\1`) inklusive optionaler Domänen-Anmeldung hinzufügen.
- **Splitscreen-Modus**: Optional lassen sich zwei Quellen parallel darstellen – z. B. Videos links und Bilder rechts – inklusive unabhängiger Wiedergabeschleifen.
- **Automatischer Medienabgleich**: Neue Dateien in überwachten Ordnern werden ohne Neustart erkannt und automatisch in der Wiedergabe berücksichtigt.
- **Weboberfläche** mit Dashboard zur Anzeige der aktuell wiedergegebenen Datei, Verwaltung der Playlist, Netzwerk- und Systemeinstellungen sowie Update- und Service-Steuerung.
- **Login über PAM**: Standardmäßig meldet sich der Benutzer mit seinem Raspberry-Pi-Benutzernamen und -Passwort an (z. B. `pi`).
- **Netzwerkkonfiguration**: Hostname sowie IPv4-Konfiguration (DHCP oder statische Adresse) können aus der Oberfläche angepasst werden.
- **Installations- und Update-Skripte** für einen einfachen Rollout via `systemd`-Dienst (inklusive automatischem Branch-Checkout des neuesten Versions-Branches, Benutzeranlage und Aktivierung von SMB 3.1.1).
- **Infobildschirm**: Solange keine Playlist aktiv ist – oder auf Wunsch manuell – zeigt die Anwendung einen Bildschirm mit Hostnamen und IP-Adressen an.
- **Systemaktionen**: Service-Start/-Stopp, Branch-Updates und Neustarts des Raspberry Pi können direkt im Webinterface ausgelöst werden.
- **Versionsübersicht & Protokolle**: Anzeige der aktuell eingesetzten Version sowie Zugriff auf die wichtigsten Modul-Logs direkt in der Weboberfläche.
- **Erweiterbarer REST-API-Layer**, der zukünftig von einer zentralen Verwaltungsinstanz genutzt werden kann, um mehrere PIs zu orchestrieren.

## Projektstruktur

```text
slideshow/
  app.py             # Flask-Anwendung und REST-API
  auth.py            # PAM-Authentifizierung und Login-Management
  config.py          # Zentrale Konfigurationslogik (Lesen/Schreiben)
  info.py            # Renderer für den Infobildschirm
  media.py           # Verwaltung der Medienquellen und Playlist
  network.py         # Netzwerk-Utilities (Hostname, IP-Konfiguration)
  player.py          # Hintergrund-Player-Thread
  state.py           # Gemeinsamer Speicher für Statusinformationen
  system.py          # System- und Update-Helfer
  templates/         # HTML-Templates für die Oberfläche
  static/            # Statische Assets (CSS, JS)
scripts/
  install.sh         # Installationsskript für Raspberry Pi
  update.sh          # Update-Skript zum Einspielen neuer Versionen
  mount_smb.sh       # Root-Helferskript zum Ein- und Aushängen von SMB-Freigaben
manage.py            # CLI-Helfer (z. B. zum Starten im Entwicklungsmodus)
pyproject.toml       # Python-Abhängigkeiten (Poetry)
```

## Voraussetzungen

- Raspberry Pi OS (Bookworm oder Bullseye) – wahlweise mit Desktop (X11) oder als Lite-Variante. Für headless-Geräte stellt der
  Installer über `--drm` automatisch auf den DRM/Framebuffer-Modus um.
- Internetzugang, damit das Installationsskript Repository und Pakete aus dem Netz beziehen kann.
- Optional: SMB-Freigaben, falls Netzlaufwerke eingebunden werden sollen.

## Installation

1. Installationsskript herunterladen (Beispiel: aktueller Versionsstand aus GitHub):

   ```bash
   wget https://raw.githubusercontent.com/joni123467/Slideshow/refs/heads/main/scripts/install.sh
   chmod +x install.sh
   ```

   Alternativ lässt sich das Skript direkt ausführen:

   ```bash
   curl -sSL https://raw.githubusercontent.com/joni123467/Slideshow/refs/heads/main/scripts/install.sh | sudo bash
   ```

2. Das Skript richtet automatisch alle Abhängigkeiten (inklusive `mpv`, `ffmpeg`, `feh`, `cifs-utils`) ein, ermittelt den neuesten Branch im Format `version-x.y.z`, klont diesen unter `/opt/slideshow` und legt dabei einen dedizierten Dienstbenutzer an. Damit die Hardwarebeschleunigung funktioniert, wird der Account – sofern die Gruppen existieren – direkt `video`, `render` und `input` hinzugefügt. Benutzername und Passwort können während der Installation angepasst werden:

   ```bash
   sudo ./install.sh
   ```

   Für Installationen ohne Desktop (Raspberry Pi OS Lite) empfiehlt sich der DRM-Modus:

   ```bash
   sudo ./install.sh --drm
   ```

   Weitere Optionen:

   - `--video-backend x11|drm` setzt das Backend explizit.
   - `--desktop-user <name>` hinterlegt direkt den Benutzer, dessen X11-Sitzung verwendet werden soll.

3. Nach erfolgreicher Installation läuft der Dienst als `slideshow.service`. Der Code liegt unter `/opt/slideshow`, ein virtuelles Python-Environment befindet sich in `/opt/slideshow/.venv`. Zusätzlich erzeugt der Installer einen Eintrag unter `/etc/sudoers.d/slideshow`, damit der Dienstbenutzer Updates, Dienststeuerung, Neustarts sowie das SMB-Helferskript ohne Passwort ausführen kann.

4. Die Weboberfläche ist standardmäßig unter `http://<IP-des-Pi>:8080` erreichbar.

## Update-Prozess

Updates lassen sich entweder aus dem Webinterface über die Branch-Auswahl oder per Skript anwenden. Branches im Format `version-x.y.z` werden automatisch erkannt und nach Versionsnummer sortiert dargestellt:

- **Im Webinterface**: gewünschten Branch auswählen und Update starten. Das Skript `scripts/update.sh` wird dabei mit Root-Rechten aufgerufen und setzt anschließend den Dienst neu auf.
- **Per Terminal**:

  ```bash
  cd /opt/slideshow
  sudo ./scripts/update.sh <branch>
  ```

  Wird kein Branch übergeben, nutzt das Skript den bei der Installation hinterlegten Branch.

## Protokolle einsehen

Im Dashboard befindet sich ein eigener Bereich für Protokolle. Dort können die wichtigsten Modul-Logs (z. B. Weboberfläche, Player, Medienverwaltung) ausgewählt, gefiltert und direkt im Browser angezeigt werden. So lassen sich Fehler schnell diagnostizieren, ohne den Pi per SSH betreten zu müssen.

## Entwicklung

Für lokale Entwicklung kann der Server manuell gestartet werden:

```bash
python manage.py run
```

Vor dem ersten Start sollten alle Python-Abhängigkeiten installiert werden – entweder über Poetry (`poetry install`) oder klassisch mit `pip install -r requirements.txt`. Dadurch steht unter anderem das Paket `flask-login` bereit, das für die Webanmeldung benötigt wird.

Standardmäßig wird dabei der Flask-Debug-Server auf Port `8080` im lokalen Netzwerk erreichbar.

### Datenablage konfigurieren

Die Anwendung legt Konfigurations- und Statusdateien in einem beschreibbaren Datenverzeichnis ab. Standardmäßig wird dafür `~/.slideshow` verwendet. Über die Umgebungsvariable `SLIDESHOW_DATA_DIR` kann ein alternatives Verzeichnis angegeben werden:

```bash
export SLIDESHOW_DATA_DIR=/var/lib/slideshow
python manage.py run
```

Ist das angegebene Verzeichnis nicht beschreibbar, fällt die Anwendung automatisch auf das Verzeichnis im Benutzerprofil (`~/.slideshow`) zurück.

### Medienquellen und SMB-Mounts

- Der lokale Medienordner (`local`-Quelle) wird beim ersten Start automatisch erzeugt. Im Standarddatenspeicher liegt er unter `<Datenverzeichnis>/media`.
- Für SMB-Freigaben legt die Anwendung einen beschreibbaren Mount-Root unter `<Datenverzeichnis>/mounts` an. Neue Freigaben werden automatisch dort eingeordnet; bestehende Konfigurationen mit dem alten Standardpfad `/mnt/slideshow/<name>` werden beim nächsten Start migriert, falls sie nicht mehr erreichbar oder beschreibbar sind.
- Die Weboberfläche erlaubt nun, automatische Scans pro Quelle ein- oder auszuschalten sowie nicht mehr benötigte SMB-Quellen zu löschen. SMB-Freigaben werden ausschließlich über ihren UNC-Pfad (z. B. `\\\\server\\share\\bilder`) angelegt; optionale Unterordner lassen sich direkt im Pfad angeben.

### Zugriff auf die grafische Oberfläche

- Der systemd-Dienst benötigt Zugriff auf die laufende Desktop-Sitzung (`DISPLAY=:0`). Während der Installation kann optional ein vorhandener Desktop-Benutzer angegeben werden. Dessen `.Xauthority` wird nicht mehr einmalig kopiert, sondern vor jedem Dienststart über `scripts/prestart.sh` synchronisiert, damit neue Login-Tokens automatisch übernommen werden.
- Findet der Installer keine `.Xauthority`, weist er darauf hin. In diesem Fall muss entweder der korrekte Desktop-Benutzer ausgewählt oder die Datei manuell bereitgestellt werden. Alternativ lässt sich die Anwendung ohne Desktop im DRM-Modus betreiben.
- Damit die Wiedergabe auf die Grafikhardware zugreifen kann, nimmt das Installationsskript den Dienstnutzer automatisch in die Gruppen `video`, `render` und `input` auf (sofern vorhanden). Fehlende Gruppen werden am Ende der Installation gemeldet.
- Der systemd-Dienst verwendet `RuntimeDirectory=slideshow-<UID>` und setzt `XDG_RUNTIME_DIR` automatisch auf `/run/slideshow-<UID>`. Dadurch steht der notwendige Socket-Pfad auch nach einem Neustart ohne manuelle Eingriffe bereit.
- Das Pre-Start-Skript wartet in mehreren Versuchen (`xset q`), bis die grafische Sitzung verfügbar ist. Gelingt dies nicht rechtzeitig, wird lediglich eine Warnung protokolliert – der Dienst startet weiter und versucht später erneut, das Display zu erreichen.

### Headless- und DRM-Betrieb

- Über `install.sh --drm` oder die Umgebungsvariable `SLIDESHOW_VIDEO_BACKEND=drm` richtet der Dienst automatisch den DRM-/Framebuffer-Modus ein. Ein Desktop-Benutzer ist dann nicht erforderlich; die Wiedergabe erfolgt direkt über `mpv --gpu-context=drm`.
- Die Wiedergabeeinstellungen im Webinterface enthalten Auswahlfelder für Video- und Bild-Backend (`auto`, `x11`, `drm`) sowie zusätzliche Argumentlisten. Im Automatikmodus erkennt die Anwendung anhand der gesetzten Umgebungsvariablen bzw. eines vorhandenen `DISPLAY`, welches Backend verwendet werden soll.
- Für Desktop-Systeme wartet der systemd-Dienst beim Start auf eine erreichbare X11-Sitzung (`xset q`). Dadurch werden Timing-Probleme beim Booten vermieden, wenn der Display-Manager länger benötigt.

### Updates ohne Git-Checkout

Wird die Anwendung als Paket ohne `.git`-Verzeichnis ausgeliefert, blendet die Update-Seite den Branch-Wechsler aus und verweist stattdessen auf die veröffentlichten Branches des GitHub-Repositories (`https://github.com/joni123467/Slideshow`). Sobald ein Git-Checkout verfügbar ist, erscheinen die Branches wie gewohnt in der Auswahl.

## Sicherheitshinweise

- Der Webzugang ist nur für authentifizierte Benutzer zugänglich. Die Authentifizierung nutzt das PAM-System des Betriebssystems.
- Netzwerkänderungen erfordern Root-Rechte. Stellen Sie sicher, dass der Dienst mit ausreichenden Rechten ausgeführt wird.
- SMB-Zugangsdaten werden verschlüsselt im Konfigurationsspeicher abgelegt.
- Das Installationsskript legt gezielte `sudoers`-Regeln an, die ausschließlich das Update-Skript, das SMB-Helferskript, ausgewählte `systemctl`-Befehle sowie `reboot` ohne Passwort erlauben.

## Zukunftsperspektive

Die REST-API (`/api/*`) ist so gestaltet, dass sie mittelfristig von einem zentralen Verwaltungsserver genutzt werden kann. Dieser könnte mehrere Raspberry Pis überwachen, Konfigurationen verteilen und Statusinformationen abfragen. Ein mögliches Folgeprojekt ist ein zentrales Dashboard, das diese API konsumiert.

