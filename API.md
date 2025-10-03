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
  "secondary_item": null,
  "secondary_status": "stopped",
  "secondary_started_at": null,
  "info_screen": false,
  "info_manual": false
}
```

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

## Fehlercodes

* `400 Bad Request` – Eingabedaten fehlerhaft oder unvollständig
* `404 Not Found` – Quelle/Datei nicht vorhanden
* `415 Unsupported Media Type` – Vorschau für Datei nicht verfügbar
* `500 Internal Server Error` – Unerwarteter Fehler (Log prüfen)

Alle Fehlerantworten enthalten ein JSON-Objekt `{ "status": "error", "message": "…" }` mit einer kurzen Beschreibung.
