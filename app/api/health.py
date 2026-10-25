from flask import current_app, jsonify
from sqlalchemy import text

from ..extensions import db
from ..timeutil import iso, utcnow
from . import bp


def _db_ok() -> bool:
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except Exception:
        current_app.logger.exception("database health check failed")
        return False


@bp.get("/health")
def health():
    return jsonify({"service": "watercast", "status": "ok", "version": current_app.config["APP_VERSION"],
                    "time": iso(utcnow())})


@bp.get("/ready")
def ready():
    ok = _db_ok()
    return jsonify({"status": "ready" if ok else "unavailable", "database": ok}), (200 if ok else 503)
