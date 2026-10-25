from __future__ import annotations

import os
from pathlib import Path

import hashlib
import hmac

from flask import Flask, jsonify, render_template, request, send_from_directory
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import ConfigError, load_settings, on_vercel
from .extensions import cache, db, limiter, migrate

BASE_DIR = Path(__file__).resolve().parent


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _):
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.execute("PRAGMA cache_size=-16000")
        cur.close()


def _asset_fingerprint(static_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(static_dir.rglob("*")):
        if path.is_file() and path.suffix in {".js", ".css", ".webmanifest", ".svg", ".woff2"}:
            digest.update(str(path.relative_to(static_dir)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def create_app(overrides: dict | None = None) -> Flask:
    if os.environ.get("APP_ENV", "development") == "development":
        try:
            from dotenv import load_dotenv
            load_dotenv(BASE_DIR.parent / ".env")
        except ImportError:
            pass

    try:
        settings = load_settings()
    except ConfigError as exc:
        if not on_vercel():
            raise
        import logging
        logging.getLogger("watercast.startup").error("Configuration error: %s", exc)
        from .startup import setup_needed_app
        return setup_needed_app(str(exc))

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(settings)
    if overrides:
        app.config.update(overrides)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31536000
    if not app.config.get("ASSET_VERSION"):
        app.config["ASSET_VERSION"] = _asset_fingerprint(BASE_DIR / "static")
    app.json.sort_keys = False
    if app.config.get("CACHE_TYPE") == "FileSystemCache":
        try:
            os.makedirs(app.config["CACHE_DIR"], exist_ok=True)
            if not os.access(app.config["CACHE_DIR"], os.W_OK):
                raise OSError
        except OSError:
            app.config["CACHE_TYPE"] = "SimpleCache"

    from .logging_conf import configure_logging, init_sentry
    configure_logging(app)
    init_sentry(app)

    if app.config["TRUSTED_PROXY_COUNT"]:
        n = app.config["TRUSTED_PROXY_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n, x_prefix=0)

    db.init_app(app)
    migrate.init_app(app, db, directory=str(BASE_DIR.parent / "migrations"), render_as_batch=True)
    cache.init_app(app)
    limiter.init_app(app)

    from .errors import register_error_handlers
    from .security import init_security
    register_error_handlers(app)
    init_security(app)
    from .compression import init_compression
    init_compression(app)

    from .api import bp as api_bp
    app.register_blueprint(api_bp)

    from . import cli
    cli.register(app)

    register_pages(app)
    return app


def register_pages(app: Flask) -> None:

    rendered: dict[str, tuple[str, str]] = {}

    def page(name: str):
        hit = rendered.get(name)
        if hit is None:
            body = render_template(name, asset_v=app.config["ASSET_VERSION"])
            hit = rendered[name] = (body, hashlib.sha256(body.encode()).hexdigest()[:20])
        resp = app.make_response(hit[0])
        resp.headers["Cache-Control"] = "no-cache"
        resp.set_etag(hit[1])
        return resp.make_conditional(request)

    @app.get("/")
    def index():
        return page("index.html")

    @app.get("/login")
    @app.get("/login.html")
    def login_page():
        return page("login.html")

    @app.get("/privacy")
    def privacy_page():
        return page("privacy.html")

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/cron/purge")
    def cron_purge():
        secret = app.config.get("CRON_SECRET") or ""
        given = request.headers.get("Authorization", "")
        if not secret or not hmac.compare_digest(given, f"Bearer {secret}"):
            return jsonify({"error": "Not found."}), 404
        days = app.config["DATA_RETENTION_DAYS"]
        if days <= 0:
            return jsonify({"ok": True, "deleted": {}, "note": "retention disabled"})
        from .cli import purge_old
        return jsonify({"ok": True, "days": days, "deleted": purge_old(days)})


    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(app.static_folder + "/img", "favicon.svg", mimetype="image/svg+xml")
