"""Flask-Anwendung für die Slideshow."""
from __future__ import annotations

import functools
import logging
import subprocess
from typing import Optional

from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user

from . import __version__
from .auth import PamAuthenticator, User
from .config import AppConfig
from .logging_config import available_logs
from .media import MediaManager
from .network import NetworkManager
from .player import PlayerService
from .state import get_state
from .system import SystemManager

LOGGER = logging.getLogger(__name__)


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
        )

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

    @app.route("/playback")
    @pam_required
    def playback_settings_page():
        sources = media_manager.list_sources()
        return render_template(
            "playback.html",
            config=cfg,
            sources=sources,
            state=get_state(),
        )

    @app.route("/network")
    @pam_required
    def network_settings():
        return render_template(
            "network.html",
            config=cfg,
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
        )

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
        if transition not in {"none", "fade", "slide"}:
            transition = "none"
        playback.transition_type = transition

        try:
            transition_duration = float(request.form.get("transition_duration") or playback.transition_duration)
        except ValueError:
            transition_duration = playback.transition_duration
        playback.transition_duration = max(0.2, min(10.0, transition_duration))

        display_resolution = (request.form.get("display_resolution") or playback.display_resolution).strip()
        playback.display_resolution = display_resolution

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
        return jsonify({
            "primary_item": state.primary_item,
            "primary_status": state.primary_status,
            "primary_started_at": state.primary_started_at,
            "secondary_item": state.secondary_item,
            "secondary_status": state.secondary_status,
            "secondary_started_at": state.secondary_started_at,
            "info_screen": state.info_screen,
            "info_manual": state.info_manual,
        })

    @app.route("/api/config")
    @pam_required
    def api_config():
        return jsonify({
            "sources": media_manager.serialize_sources(),
            "playlist": media_manager.serialize_playlist(),
            "network": network_manager.serialize(),
        })

    return app
