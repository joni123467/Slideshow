# Slideshow REST- und Hilfs-API

Die Weboberfläche stellt mehrere JSON-Endpunkte bereit, die nach einer erfolgreichen Anmeldung (Session-Cookie via `/login`) genutzt werden können. Alle Antworten verwenden UTF-8 und den MIME-Type `application/json`, sofern nicht anders angegeben.

## Authentifizierung

* **Login:** `POST /login` mit den Formularfeldern `username` und `password`. Bei Erfolg wird ein Session-Cookie gesetzt, das für alle API-Aufrufe benötigt wird.
* **Logout:** `GET /logout` beendet die Session.

## Status-Endpunkte

### `GET /api/state`

Aktueller Wiedergabestatus.

```json
{
  "primary_item": "Pfad/zur/datei.jpg",
  "primary_status": "playing",
  "primary_started_at": 1700000000.0,
  "primary_source": "local",
  "primary_media_path": "bilder/motiv.jpg",
  "primary_media_type": "image",
  "primary_preview": "/home/pi/.slideshow/cache/local/bilder/motiv.jpg",
  "primary_preview_token": 1700000123,
  "primary_preview_available": true,
  "secondary_item": null,
  "secondary_status": "stopped",
  "secondary_started_at": null,
  "secondary_source": null,
  "secondary_media_type": null,
  "secondary_preview": null,
  "secondary_preview_token": 0,
  "secondary_preview_available": false,
  "info_screen": false,
  "info_manual": false,
  "service_status": "running",
  "service_active": true,
  "version": "0.0.4",
  "theme": "mid"
}
```

Das Feld `service_status` beschreibt den Status der Slideshow-Wiedergabe (`running` oder `stopped`), `service_active` liefert das dazugehörige Boolesche Convenience-Feld. Die `*_preview`-Felder geben Pfadinformationen (falls verfügbar) und einen Cache-Busting-Zeitstempel an, sodass Clients gezielt Vorschaubilder nachladen können.

### `GET /api/config`

Gesamtkonfiguration in kompakter Form.

* `sources` – Liste der Medienquellen (siehe `MediaSource` Felder)
* `playlist` – Manuell konfigurierte Playlist-Einträge
* `network` – Netzwerkkonfiguration
* `playback` – Aktuelle Wiedergabeeinstellungen

## Playersteuerung

### `POST /api/player/<action>`

* `action` ∈ {`start`, `stop`, `reload`}
* Antwort: `{ "status": "ok", "action": "start" }`

### `POST /api/player/info-screen`

* JSON-Body: `{ "enabled": true }`
* Schaltet den Infobildschirm dauerhaft ein/aus.

## Wiedergabeeinstellungen

### `PUT /api/playback`

Akzeptiert ein (teilweises) JSON-Objekt mit denselben Feldern wie die Wiedergabekonfiguration. Validierte Felder werden übernommen, alle anderen bleiben unverändert.

Wichtige Felder:

* `image_duration` – Ganzzahl ≥ 1
* `image_fit` – `contain`, `stretch` oder `original`
* `image_rotation` – 0…359
* `transition_type` – `none`, `fade`, `fadeblack`, `fadewhite`, `wipeleft`, `wiperight`, `wipeup`, `wipedown`, `slideleft`, `slideright`, `slideup`, `slidedown`
* `transition_duration` – 0.2…10.0 Sekunden
* `splitscreen_enabled` – Boolesch
* `splitscreen_left_source`, `splitscreen_right_source` – Namen existierender Quellen
* `splitscreen_left_path`, `splitscreen_right_path` – optionale Unterordner
* `video_player_args`, `image_viewer_args` – Liste zusätzlicher Argumente

Antwort: `{ "status": "ok", "playback": { ... } }`

## Netzwerkeinstellungen

### `GET /api/network`

Liefert sowohl die gespeicherte Netzwerkkonfiguration als auch die aktuell ermittelten Systemwerte.

```json
{
  "status": "ok",
  "config": {
    "hostname": "slideshow",
    "interface": "eth0",
    "ipv4": {
      "mode": "dhcp",
      "static": {
        "address": null,
        "router": null,
        "dns": []
      }
    },
    "ipv6": {
      "mode": "dhcp",
      "static": {
        "address": null,
        "router": null,
        "dns": []
      }
    }
  },
  "current": {
    "hostname": "slideshow",
    "interface": "eth0",
    "ipv4": {
      "mode": "dhcp",
      "address": "192.168.1.20/24",
      "router": "192.168.1.1",
      "dns": ["192.168.1.1"]
    },
    "ipv6": {
      "mode": "dhcp",
      "address": "fd00::1234/64",
      "router": "fd00::1",
      "dns": []
    },
    "dns": ["192.168.1.1"]
  }
}
```

### `PUT /api/network`

Aktualisiert Hostname, Interface sowie IPv4- und IPv6-Einstellungen. Teilupdates sind erlaubt; nicht gesetzte Felder bleiben unverändert. Das JSON kann entweder flache Felder oder verschachtelte Objekte enthalten.

Unterstützte Felder:

- `hostname` – neuer Hostname (String)
- `interface` – Name des Netzwerkinterfaces
- `ipv4_mode`, `ipv6_mode` – `dhcp`, `static` bzw. bei IPv6 zusätzlich `disabled`
- `ipv4_address`, `ipv4_router`, `ipv6_address`, `ipv6_router` – Strings oder `null`
- `ipv4_dns`, `ipv6_dns` – Liste oder (komma-/strichpunktgetrennter) String
- `ipv4`, `ipv6` – optional verschachtelte Objekte mit den gleichen Feldern (`mode`, `static.address`, `static.router`, `static.dns`)

Beispiel:

```json
{
  "hostname": "display-01",
  "interface": "eth0",
  "ipv4": {
    "mode": "static",
    "static": {
      "address": "192.168.1.50/24",
      "router": "192.168.1.1",
      "dns": ["192.168.1.1", "8.8.8.8"]
    }
  },
  "ipv6_mode": "disabled"
}
```

Antwort: `{ "status": "ok", "config": { ... }, "current": { ... } }`

## Quellenverwaltung

### `GET /api/sources`

Listet alle konfigurierten Quellen: `{ "sources": [ {"name": "…", ...}, ... ] }`

### `POST /api/sources`

Legt eine neue SMB-Quelle an. Erwartete Felder (alle Strings):

* `name` (erforderlich)
* `server`, `share` (optional, werden überschrieben wenn `smb_path` gesetzt ist)
* `smb_path` (optional, z. B. `\\\\server\\share\\bilder`)
* `username`, `password`, `domain`, `subpath`
* `auto_scan` (boolesch, Standard `true`)

Antwort: `{ "status": "ok", "source": { ... } }`

### `PUT /api/sources/<name>`

Aktualisiert eine bestehende SMB-Quelle. Unterstützt dieselben Felder wie `POST /api/sources` plus `name` (zum Umbenennen). Wird `password` auf einen leeren String gesetzt, wird das gespeicherte Kennwort gelöscht.

### `DELETE /api/sources/<name>`

Entfernt eine Quelle (die lokale Standardquelle ist geschützt).

## Medienvorschauen

### `GET /media/preview/<source>/<path>`

Liefert ein kleines JPEG-Vorschaubild für Bilddateien einer Quelle. Für andere Dateitypen wird HTTP 415 zurückgegeben. Der Endpunkt ist authentifizierungspflichtig und hauptsächlich für die Dashboard-Anzeige gedacht.

### `GET /logs/<name>/download`

Lädt eine komplette Logdatei als Text herunter. Der Parameter `<name>` entspricht einem Schlüssel aus der Logauswahl des System-Tabs (`app`, `player`, `media`, `network`, `system`, `update`).

## Systemverwaltung

### `GET /config/export`

Lädt die aktuelle Konfiguration (inklusive `config.yml` und optional `secrets.json`, falls vorhanden) als ZIP-Archiv herunter.

### `POST /config/import`

Erwartet ein Multipart-Formular mit dem Feld `config_file`. Akzeptiert entweder das zuvor exportierte ZIP-Archiv oder eine einzelne `config.yml`. Nach erfolgreichem Import werden Player- und Netzwerkverwaltung neu initialisiert.

## Fehlercodes

* `400 Bad Request` – Eingabedaten fehlerhaft oder unvollständig
* `404 Not Found` – Quelle/Datei nicht vorhanden
* `415 Unsupported Media Type` – Vorschau für Datei nicht verfügbar
* `500 Internal Server Error` – Unerwarteter Fehler (Log prüfen)

Alle Fehlerantworten enthalten ein JSON-Objekt `{ "status": "error", "message": "…" }` mit einer kurzen Beschreibung.
