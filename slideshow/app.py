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
from .config import AppConfig, PlaylistItem
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
        sources = media_manager.list_sources()
        auto_totals = dict(
            sorted(
                (
                    (source.name, len(media_manager.scan_directory(source)))
                    for source in sources
                    if source.auto_scan
                ),
                key=lambda item: item[0],
            )
        )
        branches = system_manager.list_branches()
        current_branch = system_manager.current_branch()
        service_status = system_manager.service_status()
        return render_template(
            "dashboard.html",
            state=state,
            playlist=media_manager.list_playlist(),
            sources=sources,
            config=cfg,
            branches=branches,
            current_branch=current_branch,
            service_status=service_status,
            auto_totals=auto_totals,
        )

    @app.route("/playlist", methods=["POST"])
    @pam_required
    def playlist_add():
        source = request.form.get("source")
        path = request.form.get("path")
        duration = request.form.get("duration")
        item_type = media_manager.detect_item_type(path or "")
        if not source or not path:
            flash("Quelle und Pfad müssen angegeben werden", "danger")
            return redirect(url_for("dashboard"))
        media_manager.add_to_playlist(PlaylistItem(source=source, path=path, type=item_type, duration=int(duration) if duration else None))
        player.reload()
        flash("Element hinzugefügt", "success")
        return redirect(url_for("dashboard"))

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
        name = request.form.get("name")
        server = request.form.get("server")
        share = request.form.get("share")
        username = request.form.get("username") or None
        password = request.form.get("password") or None
        if not all([name, server, share]):
            flash("Name, Server und Freigabe sind erforderlich", "danger")
            return redirect(url_for("dashboard"))
        media_manager.add_smb_source(name=name, server=server, share=share, username=username, password=password)
        flash("SMB-Quelle hinzugefügt", "success")
        return redirect(url_for("dashboard"))

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
        return redirect(url_for("dashboard"))

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
        return redirect(url_for("dashboard"))

    @app.route("/player/info-screen", methods=["POST"])
    @pam_required
    def player_info_screen():
        enabled = request.form.get("enabled") == "1"
        player.show_info_screen(enabled)
        flash("Infobildschirm aktiviert" if enabled else "Infobildschirm deaktiviert", "info")
        return redirect(url_for("dashboard"))

    @app.route("/system/update", methods=["POST"])
    @pam_required
    def system_update():
        branch = request.form.get("branch") or system_manager.current_branch() or "main"
        try:
            system_manager.update(branch)
            flash(f"Update auf Branch {branch} gestartet", "success")
        except subprocess.CalledProcessError as exc:
            LOGGER.exception("Update fehlgeschlagen")
            flash(f"Update fehlgeschlagen: {exc}", "danger")
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("dashboard"))

    @app.route("/system/service/<string:action>", methods=["POST"])
    @pam_required
    def system_service(action: str):
        try:
            system_manager.control_service(action)
            flash(f"Service {action} ausgeführt", "success")
        except (subprocess.CalledProcessError, ValueError) as exc:
            LOGGER.exception("Serviceaktion fehlgeschlagen")
            flash(f"Serviceaktion fehlgeschlagen: {exc}", "danger")
        return redirect(url_for("dashboard"))

    @app.route("/system/reboot", methods=["POST"])
    @pam_required
    def system_reboot():
        try:
            system_manager.reboot()
            flash("Neustart ausgelöst", "warning")
        except subprocess.CalledProcessError as exc:
            LOGGER.exception("Neustart fehlgeschlagen")
            flash(f"Neustart fehlgeschlagen: {exc}", "danger")
        return redirect(url_for("dashboard"))

    # API ---------------------------------------------------------------
    @app.route("/api/state")
    @pam_required
    def api_state():
        state = get_state()
        return jsonify({
            "current_item": state.current_item,
            "status": state.status,
            "started_at": state.started_at,
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
