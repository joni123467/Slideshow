"""Flask-Anwendung für die Slideshow."""
from __future__ import annotations

import dataclasses
import datetime
import functools
import io
import logging
import subprocess
from typing import List, Optional, Tuple

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import LoginManager, current_user, login_required, login_user, logout_user

from . import __version__
from .auth import PamAuthenticator, User
from .config import AppConfig, export_config_bundle, import_config_bundle
from .logging_config import available_logs
from .media import MediaManager
from .network import NetworkManager
from .player import PlayerService
from .state import get_state
from .system import SystemManager

LOGGER = logging.getLogger(__name__)

TRANSITION_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("none", "Keiner"),
    ("fade", "Überblendung"),
    ("fadeblack", "Blende zu Schwarz"),
    ("fadewhite", "Blende zu Weiß"),
    ("wipeleft", "Wischen nach links"),
    ("wiperight", "Wischen nach rechts"),
    ("wipeup", "Wischen nach oben"),
    ("wipedown", "Wischen nach unten"),
    ("slideleft", "Schieben nach links"),
    ("slideright", "Schieben nach rechts"),
    ("slideup", "Schieben nach oben"),
    ("slidedown", "Schieben nach unten"),
)

ALLOWED_TRANSITIONS = {option for option, _ in TRANSITION_OPTIONS}


def create_app(config: Optional[AppConfig] = None, player_service: Optional[PlayerService] = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "slideshow-secret-key"
    app.config.setdefault("HOST", "0.0.0.0")
    app.config.setdefault("PORT", 8080)

    cfg = config or AppConfig.load()
    media_manager = MediaManager(cfg)
    network_manager = NetworkManager(cfg)
    player = player_service or PlayerService(cfg)
    system_manager = SystemManager()

    if cfg.playback.auto_start:
        player.start()

    app.extensions["player_service"] = player
    app.extensions["system_manager"] = system_manager
    app.config["SLIDESHOW_VERSION"] = __version__

    @app.context_processor
    def inject_globals():
        return {
            "slideshow_version": app.config.get("SLIDESHOW_VERSION", "0.0.0"),
            "log_sources": available_logs(),
        }

    def service_active(status: Optional[str]) -> bool:
        if not status:
            return False
        normalized = status.strip().lower()
        return normalized in {"active", "active (running)", "running"}

    @app.template_filter("datetimeformat")
    def datetimeformat(value, fmt="%d.%m.%Y %H:%M:%S"):
        import datetime

        if not value:
            return ""
        try:
            return datetime.datetime.fromtimestamp(float(value)).strftime(fmt)
        except Exception:
            return str(value)

    login_manager = LoginManager(app)
    login_manager.login_view = "login"
    authenticator = PamAuthenticator()

    @login_manager.user_loader
    def load_user(username: str) -> Optional[User]:
        return User(username=username)

    def pam_required(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapper

    # Views -------------------------------------------------------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            if authenticator.authenticate(username, password):
                login_user(User(username=username))
                flash("Login erfolgreich", "success")
                return redirect(url_for("dashboard"))
            flash("Login fehlgeschlagen", "danger")
        return render_template("login.html", default_user=authenticator.default_user())

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/")
    @pam_required
    def dashboard():
        state = get_state()
        playlist_preview = media_manager.build_playlist()
        service_status = system_manager.service_status()
        return render_template(
            "dashboard.html",
            state=state,
            playlist=playlist_preview,
            config=cfg,
            service_status=service_status,
            service_active=service_active(service_status),
        )

    @app.route("/media/preview/<string:source>/<path:media_path>")
    @pam_required
    def media_preview(source: str, media_path: str):
        try:
            content, mime = media_manager.generate_preview(source, media_path)
        except TypeError:
            abort(415)
        except (ValueError, FileNotFoundError, PermissionError):
            abort(404)
        response = Response(content, mimetype=mime)
        response.headers["Cache-Control"] = "public, max-age=60"
        return response

    @app.route("/media")
    @pam_required
    def media_settings():
        sources = media_manager.list_sources()
        auto_totals = {}
        for source in sources:
            if not source.auto_scan:
                continue
            try:
                media_manager.mount_source(source)
                auto_totals[source.name] = len(media_manager.scan_directory(source))
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Automatischer Scan für %s fehlgeschlagen: %s", source.name, exc)
                flash(f"Konnte Quelle {source.name} nicht einlesen: {exc}", "danger")
        auto_totals = dict(sorted(auto_totals.items(), key=lambda item: item[0]))
        return render_template(
            "media.html",
            sources=sources,
            auto_totals=auto_totals,
            config=cfg,
        )

    @app.route("/sources/<path:name>/edit", methods=["GET", "POST"])
    @pam_required
    def edit_source(name: str):
        source = cfg.get_source(name)
        if not source or source.type != "smb":
            abort(404)

        if request.method == "POST":
            new_name = (request.form.get("name") or "").strip() or source.name
            smb_path = (request.form.get("smb_path") or "").strip() or None
            server = (request.form.get("server") or "").strip() or None
            share = (request.form.get("share") or "").strip() or None
            username = (request.form.get("username") or "").strip()
            domain = (request.form.get("domain") or "").strip()
            subpath = (request.form.get("subpath") or "").strip() or None
            auto_scan = request.form.get("auto_scan") is not None
            password_raw = request.form.get("password")
            password_action = request.form.get("clear_password")
            password: Optional[str]
            if password_action == "1":
                password = ""
            elif password_raw:
                password = password_raw
            else:
                password = None

            try:
                media_manager.update_source(
                    name,
                    new_name=new_name,
                    smb_path=smb_path,
                    server=server,
                    share=share,
                    username=username or None,
                    password=password,
                    domain=domain or None,
                    subpath=subpath,
                    auto_scan=auto_scan,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.exception("Konnte Quelle nicht aktualisieren")
                flash(f"Aktualisierung fehlgeschlagen: {exc}", "danger")
            else:
                player.reload()
                flash("Quelle aktualisiert", "success")
                return redirect(url_for("media_settings"))

        return render_template("edit_source.html", source=source)

    @app.route("/playback")
    @pam_required
    def playback_settings_page():
        sources = media_manager.list_sources()
        return render_template(
            "playback.html",
            config=cfg,
            sources=sources,
            state=get_state(),
            transition_options=TRANSITION_OPTIONS,
        )

    @app.route("/network")
    @pam_required
    def network_settings():
        current = network_manager.current_settings()
        return render_template(
            "network.html",
            config=cfg,
            current=current,
        )

    @app.route("/system")
    @pam_required
    def system_settings():
        branches = system_manager.list_branches()
        current_branch = system_manager.current_branch()
        service_status = system_manager.service_status()
        return render_template(
            "system.html",
            config=cfg,
            branches=branches,
            current_branch=current_branch,
            has_branch_info=bool(branches or current_branch),
            fallback_repo=system_manager.fallback_repo,
            service_status=service_status,
            service_active=service_active(service_status),
        )

    @app.route("/config/export")
    @pam_required
    def export_config():
        archive = export_config_bundle()
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"slideshow-config-{timestamp}.zip"
        return send_file(
            io.BytesIO(archive),
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )

    @app.route("/config/import", methods=["POST"])
    @pam_required
    def import_config():
        nonlocal cfg, media_manager, network_manager, player
        file = request.files.get("config_file")
        if not file or not file.filename:
            flash("Keine Konfigurationsdatei ausgewählt", "danger")
            return redirect(url_for("system_settings"))
        data = file.read()
        if not data:
            flash("Die hochgeladene Datei ist leer", "danger")
            return redirect(url_for("system_settings"))
        try:
            new_cfg = import_config_bundle(data)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("system_settings"))

        was_running = player.is_running()
        player.stop()

        cfg = new_cfg
        media_manager = MediaManager(cfg)
        network_manager = NetworkManager(cfg)
        new_player = PlayerService(cfg)
        app.extensions["player_service"] = new_player
        player = new_player

        if was_running or cfg.playback.auto_start:
            player.start()

        flash("Konfiguration importiert", "success")
        return redirect(url_for("system_settings"))

    @app.route("/logs/<string:name>")
    @pam_required
    def show_log(name: str):
        lines = request.args.get("lines", default="200")
        try:
            line_count = max(10, min(2000, int(lines)))
        except ValueError:
            line_count = 200
        try:
            content = system_manager.read_log(name, line_count)
        except ValueError:
            abort(404)
        return Response(content, mimetype="text/plain; charset=utf-8")

    @app.route("/playlist/<int:index>/delete", methods=["POST"])
    @pam_required
    def playlist_delete(index: int):
        media_manager.remove_from_playlist(index)
        player.reload()
        flash("Element entfernt", "info")
        return redirect(url_for("dashboard"))

    @app.route("/sources/smb", methods=["POST"])
    @pam_required
    def add_smb_source():
        name = (request.form.get("name") or "").strip()
        smb_path = (request.form.get("smb_path") or "").strip()
        server = (request.form.get("server") or "").strip() or None
        share = (request.form.get("share") or "").strip() or None
        subpath = (request.form.get("subpath") or "").strip() or None
        domain = (request.form.get("domain") or "").strip() or None
        username = (request.form.get("username") or "").strip() or None
        password = (request.form.get("password") or "").strip() or None
        auto_scan = request.form.get("auto_scan") in {"1", "true", "on"}

        if not name:
            flash("Name der Quelle ist erforderlich", "danger")
            return redirect(url_for("media_settings"))

        try:
            media_manager.add_smb_source(
                name=name,
                server=server,
                share=share,
                username=username,
                password=password,
                domain=domain,
                subpath=subpath,
                smb_path=smb_path,
                auto_scan=auto_scan,
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("media_settings"))

        flash("SMB-Quelle hinzugefügt", "success")
        return redirect(url_for("media_settings"))

    @app.route("/sources/<path:name>/auto-scan", methods=["POST"])
    @pam_required
    def toggle_auto_scan(name: str):
        enabled = request.form.get("enabled") in {"1", "true", "on"}
        try:
            media_manager.set_auto_scan(name, enabled)
            player.reload()
        except ValueError as exc:
            flash(str(exc), "danger")
        else:
            status = "aktiviert" if enabled else "deaktiviert"
            flash(f"Automatischer Scan für {name} {status}", "success")
        return redirect(url_for("media_settings"))

    @app.route("/sources/<path:name>/delete", methods=["POST"])
    @pam_required
    def delete_source(name: str):
        confirm = request.form.get("confirm")
        if confirm not in {"1", "true", "on", "yes"}:
            flash("Löschung nicht bestätigt", "warning")
            return redirect(url_for("media_settings"))
        try:
            media_manager.remove_source(name)
            player.reload()
        except ValueError as exc:
            flash(str(exc), "danger")
        else:
            flash(f"Quelle {name} entfernt", "info")
        return redirect(url_for("media_settings"))

    @app.route("/network", methods=["POST"])
    @pam_required
    def update_network():
        hostname = request.form.get("hostname")
        mode = request.form.get("mode")
        interface = request.form.get("interface") or cfg.network.interface
        if hostname:
            network_manager.set_hostname(hostname)
        if mode == "static":
            address = request.form.get("address")
            router = request.form.get("router")
            dns = request.form.get("dns")
            network_manager.configure_static(interface, address, router, dns)
        else:
            network_manager.configure_dhcp(interface)
        flash("Netzwerk aktualisiert", "success")
        return redirect(url_for("network_settings"))

    @app.route("/player/<string:action>", methods=["POST"])
    @pam_required
    def player_control(action: str):
        try:
            if action == "start":
                player.start()
                flash("Slideshow gestartet", "success")
            elif action == "stop":
                player.stop()
                flash("Slideshow gestoppt", "info")
            elif action == "reload":
                player.reload()
                flash("Playlist neu geladen", "success")
            else:
                flash("Unbekannte Aktion", "danger")
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.exception("Fehler bei Player-Aktion")
            flash(f"Aktion fehlgeschlagen: {exc}", "danger")
        return redirect(url_for("playback_settings_page"))

    @app.route("/player/info-screen", methods=["POST"])
    @pam_required
    def player_info_screen():
        enabled = request.form.get("enabled") == "1"
        player.show_info_screen(enabled)
        flash("Infobildschirm aktiviert" if enabled else "Infobildschirm deaktiviert", "info")
        return redirect(url_for("playback_settings_page"))

    @app.route("/playback/settings", methods=["POST"])
    @pam_required
    def update_playback_settings():
        playback = cfg.playback

        def parse_args(field: str, current: List[str]) -> List[str]:
            raw = request.form.get(field)
            if raw is None:
                return current
            items: List[str] = []
            for entry in raw.replace("\r", "").splitlines():
                entry = entry.strip()
                if entry:
                    items.append(entry)
            return items

        try:
            playback.image_duration = max(1, int(request.form.get("image_duration") or playback.image_duration))
        except ValueError:
            flash("Ungültige Bilddauer", "danger")
            return redirect(url_for("dashboard"))

        fit = (request.form.get("image_fit") or playback.image_fit or "contain").lower()
        if fit not in {"contain", "stretch", "original"}:
            fit = "contain"
        playback.image_fit = fit

        try:
            rotation = int(request.form.get("image_rotation") or playback.image_rotation)
        except ValueError:
            rotation = playback.image_rotation
        playback.image_rotation = rotation % 360

        transition = (request.form.get("transition_type") or playback.transition_type or "none").lower()
        if transition not in ALLOWED_TRANSITIONS:
            transition = "none"
        playback.transition_type = transition

        try:
            transition_duration = float(request.form.get("transition_duration") or playback.transition_duration)
        except ValueError:
            transition_duration = playback.transition_duration
        playback.transition_duration = max(0.2, min(10.0, transition_duration))

        display_resolution = (request.form.get("display_resolution") or playback.display_resolution).strip()
        playback.display_resolution = display_resolution

        playback.video_player_args = parse_args("video_player_args", playback.video_player_args)
        playback.image_viewer_args = parse_args("image_viewer_args", playback.image_viewer_args)

        splitscreen_enabled = request.form.get("splitscreen_enabled") in {"1", "true", "on"}
        playback.splitscreen_enabled = splitscreen_enabled
        left_source = request.form.get("splitscreen_left_source")
        right_source = request.form.get("splitscreen_right_source")
        playback.splitscreen_left_source = left_source or None
        playback.splitscreen_left_path = (request.form.get("splitscreen_left_path") or "").strip()
        playback.splitscreen_right_source = right_source or None
        playback.splitscreen_right_path = (request.form.get("splitscreen_right_path") or "").strip()

        cfg.save()
        player.reload()
        flash("Wiedergabe-Einstellungen gespeichert", "success")
        return redirect(url_for("playback_settings_page"))

    @app.route("/system/update", methods=["POST"])
    @pam_required
    def system_update():
        branch = request.form.get("branch") or system_manager.current_branch() or "main"
        try:
            system_manager.update(branch)
            flash(f"Update auf Branch {branch} gestartet", "success")
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            LOGGER.exception("Update fehlgeschlagen")
            flash(f"Update fehlgeschlagen: {exc}", "danger")
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("system_settings"))

    @app.route("/system/service/<string:action>", methods=["POST"])
    @pam_required
    def system_service(action: str):
        try:
            system_manager.control_service(action)
            flash(f"Service {action} ausgeführt", "success")
        except (subprocess.CalledProcessError, ValueError, RuntimeError) as exc:
            LOGGER.exception("Serviceaktion fehlgeschlagen")
            flash(f"Serviceaktion fehlgeschlagen: {exc}", "danger")
        return redirect(url_for("system_settings"))

    @app.route("/system/reboot", methods=["POST"])
    @pam_required
    def system_reboot():
        try:
            system_manager.reboot()
            flash("Neustart ausgelöst", "warning")
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            LOGGER.exception("Neustart fehlgeschlagen")
            flash(f"Neustart fehlgeschlagen: {exc}", "danger")
        return redirect(url_for("system_settings"))

    @app.route("/system/shutdown", methods=["POST"])
    @pam_required
    def system_shutdown():
        try:
            system_manager.shutdown()
            flash("Shutdown ausgelöst", "warning")
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            LOGGER.exception("Shutdown fehlgeschlagen")
            flash(f"Shutdown fehlgeschlagen: {exc}", "danger")
        return redirect(url_for("system_settings"))

    # API ---------------------------------------------------------------
    @app.route("/api/state")
    @pam_required
    def api_state():
        state = get_state()
        svc_status = system_manager.service_status()
        return jsonify({
            "primary_item": state.primary_item,
            "primary_status": state.primary_status,
            "primary_started_at": state.primary_started_at,
            "secondary_item": state.secondary_item,
            "secondary_status": state.secondary_status,
            "secondary_started_at": state.secondary_started_at,
            "info_screen": state.info_screen,
            "info_manual": state.info_manual,
            "service_status": svc_status,
            "service_active": service_active(svc_status),
        })

    @app.route("/api/config")
    @pam_required
    def api_config():
        return jsonify({
            "sources": media_manager.serialize_sources(),
            "playlist": media_manager.serialize_playlist(),
            "network": network_manager.serialize(),
            "playback": dataclasses.asdict(cfg.playback),
        })

    @app.route("/api/player/<string:action>", methods=["POST"])
    @pam_required
    def api_player_action(action: str):
        try:
            if action == "start":
                player.start()
            elif action == "stop":
                player.stop()
            elif action == "reload":
                player.reload()
            else:
                return jsonify({"status": "error", "message": "Unbekannte Aktion"}), 400
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.exception("API-Aktion %s fehlgeschlagen", action)
            return jsonify({"status": "error", "message": str(exc)}), 500
        return jsonify({"status": "ok", "action": action})

    @app.route("/api/player/info-screen", methods=["POST"])
    @pam_required
    def api_player_info_screen():
        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get("enabled"))
        player.show_info_screen(enabled)
        return jsonify({"status": "ok", "enabled": enabled})

    @app.route("/api/playback", methods=["PUT"])
    @pam_required
    def api_update_playback():
        data = request.get_json(silent=True) or {}
        playback = cfg.playback
        try:
            if "image_duration" in data:
                playback.image_duration = max(1, int(data["image_duration"]))
            if "image_fit" in data:
                fit = str(data["image_fit"]).lower()
                if fit not in {"contain", "stretch", "original"}:
                    raise ValueError("Ungültiger Bildmodus")
                playback.image_fit = fit
            if "image_rotation" in data:
                playback.image_rotation = int(data["image_rotation"]) % 360
            if "transition_type" in data:
                transition = str(data["transition_type"]).lower()
                if transition not in ALLOWED_TRANSITIONS:
                    raise ValueError("Unbekannter Übergang")
                playback.transition_type = transition
            if "transition_duration" in data:
                playback.transition_duration = max(0.2, min(10.0, float(data["transition_duration"])))
            if "display_resolution" in data:
                playback.display_resolution = str(data["display_resolution"]).strip()
            if "video_player_args" in data:
                playback.video_player_args = [str(arg) for arg in data["video_player_args"] if str(arg).strip()]
            if "image_viewer_args" in data:
                playback.image_viewer_args = [str(arg) for arg in data["image_viewer_args"] if str(arg).strip()]
            if "splitscreen_enabled" in data:
                playback.splitscreen_enabled = bool(data["splitscreen_enabled"])
            if "splitscreen_left_source" in data:
                playback.splitscreen_left_source = data["splitscreen_left_source"] or None
            if "splitscreen_left_path" in data:
                playback.splitscreen_left_path = str(data["splitscreen_left_path"]).strip()
            if "splitscreen_right_source" in data:
                playback.splitscreen_right_source = data["splitscreen_right_source"] or None
            if "splitscreen_right_path" in data:
                playback.splitscreen_right_path = str(data["splitscreen_right_path"]).strip()
        except (TypeError, ValueError) as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400

        cfg.save()
        player.reload()
        return jsonify({"status": "ok", "playback": dataclasses.asdict(playback)})

    @app.route("/api/sources", methods=["GET", "POST"])
    @pam_required
    def api_sources():
        if request.method == "GET":
            return jsonify({"sources": media_manager.serialize_sources()})

        payload = request.get_json(silent=True) or {}
        try:
            source = media_manager.add_smb_source(
                name=payload.get("name", "").strip(),
                server=payload.get("server"),
                share=payload.get("share"),
                username=payload.get("username"),
                password=payload.get("password"),
                domain=payload.get("domain"),
                subpath=payload.get("subpath"),
                smb_path=payload.get("smb_path"),
                auto_scan=bool(payload.get("auto_scan", True)),
            )
        except Exception as exc:
            LOGGER.exception("Konnte Quelle nicht anlegen")
            return jsonify({"status": "error", "message": str(exc)}), 400
        player.reload()
        return jsonify({"status": "ok", "source": dataclasses.asdict(source)})

    @app.route("/api/sources/<path:name>", methods=["PUT", "DELETE"])
    @pam_required
    def api_source_detail(name: str):
        if request.method == "DELETE":
            try:
                media_manager.remove_source(name)
            except Exception as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
            player.reload()
            return jsonify({"status": "ok"})

        payload = request.get_json(silent=True) or {}
        try:
            password_value = payload.get("password")
            password = password_value if password_value is not None else None
            source = media_manager.update_source(
                name,
                new_name=payload.get("name"),
                smb_path=payload.get("smb_path"),
                server=payload.get("server"),
                share=payload.get("share"),
                username=payload.get("username"),
                password=password,
                domain=payload.get("domain"),
                subpath=payload.get("subpath"),
                auto_scan=payload.get("auto_scan"),
            )
        except Exception as exc:
            LOGGER.exception("Konnte Quelle nicht aktualisieren")
            return jsonify({"status": "error", "message": str(exc)}), 400
        player.reload()
        return jsonify({"status": "ok", "source": dataclasses.asdict(source)})

    return app
