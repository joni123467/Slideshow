# Slideshow für Raspberry Pi

Dieses Projekt stellt eine komplett verwaltete Slideshow-Anwendung für den Raspberry Pi bereit. Die Anwendung zeigt Bilder und Videos im Vollbildmodus an, kann lokale Verzeichnisse oder SMB-Freigaben als Quelle verwenden und bietet eine passwortgeschützte Weboberfläche, über die alle Einstellungen konfiguriert werden können.

## Funktionen

- **Automatisierte Wiedergabe** von Bildern (unterstützt durch `feh`) und Videos (unterstützt durch `mpv` oder `omxplayer`).
- **Mehrere Medienquellen**: lokale Ordner oder SMB/CIFS-Freigaben, die automatisch eingehängt und in regelmäßigen Abständen gescannt werden.
- **Automatischer Medienabgleich**: Neue Dateien in überwachten Ordnern werden ohne Neustart erkannt und automatisch in der Wiedergabe berücksichtigt.
- **Weboberfläche** mit Dashboard zur Anzeige der aktuell wiedergegebenen Datei, Verwaltung der Playlist, Netzwerk- und Systemeinstellungen sowie Update- und Service-Steuerung.
- **Login über PAM**: Standardmäßig meldet sich der Benutzer mit seinem Raspberry-Pi-Benutzernamen und -Passwort an (z. B. `pi`).
- **Netzwerkkonfiguration**: Hostname sowie IPv4-Konfiguration (DHCP oder statische Adresse) können aus der Oberfläche angepasst werden.
- **Installations- und Update-Skripte** für einen einfachen Rollout via `systemd`-Dienst (inklusive automatischem Branch-Checkout des neuesten Versions-Branches und Benutzeranlage).
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
manage.py            # CLI-Helfer (z. B. zum Starten im Entwicklungsmodus)
pyproject.toml       # Python-Abhängigkeiten (Poetry)
```

## Voraussetzungen

- Raspberry Pi OS (Bookworm oder Bullseye) mit Desktop-Komponenten.
- Internetzugang, damit das Installationsskript Repository und Pakete aus dem Netz beziehen kann.
- Optional: SMB-Freigaben, falls Netzlaufwerke eingebunden werden sollen.

## Installation

1. Installationsskript herunterladen (Beispiel: aktueller Versionsstand aus GitHub):

   ```bash
   wget https://raw.githubusercontent.com/SlideshowProject/Slideshow/main/scripts/install.sh
   chmod +x install.sh
   ```

   Alternativ lässt sich das Skript direkt ausführen:

   ```bash
   curl -sSL https://raw.githubusercontent.com/SlideshowProject/Slideshow/main/scripts/install.sh | sudo bash
   ```

2. Das Skript richtet automatisch alle Abhängigkeiten ein, ermittelt den neuesten Branch im Format `version-x.y.z`, klont diesen unter `/opt/slideshow` und legt dabei einen dedizierten Dienstbenutzer an. Benutzername und Passwort können während der Installation angepasst werden:

   ```bash
   sudo ./install.sh
   ```

3. Nach erfolgreicher Installation läuft der Dienst als `slideshow.service`. Der Code liegt unter `/opt/slideshow`, ein virtuelles Python-Environment befindet sich in `/opt/slideshow/.venv`.

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

Standardmäßig wird dabei der Flask-Debug-Server auf Port `8080` im lokalen Netzwerk erreichbar.

## Sicherheitshinweise

- Der Webzugang ist nur für authentifizierte Benutzer zugänglich. Die Authentifizierung nutzt das PAM-System des Betriebssystems.
- Netzwerkänderungen erfordern Root-Rechte. Stellen Sie sicher, dass der Dienst mit ausreichenden Rechten ausgeführt wird.
- SMB-Zugangsdaten werden verschlüsselt im Konfigurationsspeicher abgelegt.

## Zukunftsperspektive

Die REST-API (`/api/*`) ist so gestaltet, dass sie mittelfristig von einem zentralen Verwaltungsserver genutzt werden kann. Dieser könnte mehrere Raspberry Pis überwachen, Konfigurationen verteilen und Statusinformationen abfragen. Ein mögliches Folgeprojekt ist ein zentrales Dashboard, das diese API konsumiert.

