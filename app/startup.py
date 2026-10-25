from __future__ import annotations

import html
import logging
import os

from flask import Flask

log = logging.getLogger("watercast.startup")

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
_LOCK_ID = 727101


def prepare_database(app: Flask) -> None:
    from flask_migrate import upgrade
    from sqlalchemy import text

    from .cli import bootstrap_admin
    from .extensions import db

    with app.app_context():
        lock = None
        if db.engine.dialect.name == "postgresql":
            lock = db.engine.connect()
            lock.execute(text(f"SELECT pg_advisory_lock({_LOCK_ID})"))
        try:
            upgrade(directory=MIGRATIONS_DIR)
            try:
                bootstrap_admin()
            except ValueError as exc:
                log.error("Admin account not created: %s", exc)
        finally:
            if lock is not None:
                lock.execute(text(f"SELECT pg_advisory_unlock({_LOCK_ID})"))
                lock.close()
        if app.config.get("EPHEMERAL_DATABASE"):
            log.warning("DATABASE_URL is not set: using a temporary SQLite database in /tmp. "
                        "Data will be lost whenever Vercel starts a new instance.")


def setup_needed_app(message: str) -> Flask:
    setup = Flask(__name__)
    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>WaterCast setup needed</title>"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head>"
            "<body style=\"font-family:system-ui,sans-serif;background:#0b0f14;color:#e6edf3;max-width:640px;"
            "margin:12vh auto;padding:0 24px;line-height:1.55\"><h1 style=\"font-size:22px\">WaterCast needs one more setting</h1>"
            f"<p style=\"background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px\">{html.escape(message)}</p>"
            "<p>Add it in Vercel under Project &rarr; Settings &rarr; Environment Variables, then redeploy.</p></body></html>")

    @setup.route("/", defaults={"path": ""})
    @setup.route("/<path:path>")
    def needs_setup(path):
        return page, 503, {"Cache-Control": "no-store"}

    return setup
