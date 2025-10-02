#!/usr/bin/env python3
"""Hilfs-CLI für die Slideshow-Anwendung."""
from __future__ import annotations

import argparse

from slideshow.app import create_app
from slideshow.player import PlayerService
from slideshow.config import AppConfig


def cmd_run(args: argparse.Namespace) -> None:
    """Startet den Flask-Server und den Player-Service im Vordergrund."""
    config = AppConfig.load()
    player = PlayerService(config)
    app = create_app(config=config, player_service=player)

    if args.host:
        app.config["HOST"] = args.host
    if args.port:
        app.config["PORT"] = args.port

    player.start()
    try:
        app.run(host=app.config.get("HOST", "0.0.0.0"), port=app.config.get("PORT", 8080), debug=args.debug)
    finally:
        player.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Slideshow Steuerung")
    sub = parser.add_subparsers(dest="command")

    parser_run = sub.add_parser("run", help="Startet die Anwendung im Vordergrund")
    parser_run.add_argument("--host", default=None, help="Bind-Adresse des Webservers")
    parser_run.add_argument("--port", type=int, default=None, help="Port des Webservers")
    parser_run.add_argument("--debug", action="store_true", help="Aktiviert Flask-Debug-Modus")
    parser_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
