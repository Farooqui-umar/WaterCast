from __future__ import annotations

import json
import logging
import time
import uuid

from flask import Flask, g, request

_SKIP_ACCESS_LOG = ("/static/", "/api/health", "/api/ready", "/healthz")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
               "level": record.levelname, "logger": record.name, "message": record.getMessage()}
        for key in ("request_id", "method", "path", "status", "duration_ms", "ip"):
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def configure_logging(app: Flask) -> None:
    handler = logging.StreamHandler()
    if app.config["LOG_FORMAT"] == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(app.config["LOG_LEVEL"])
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    access = logging.getLogger("watercast.access")

    @app.before_request
    def _start():
        rid = request.headers.get("X-Request-ID", "")
        g.request_id = rid if 8 <= len(rid) <= 64 and rid.replace("-", "").isalnum() else uuid.uuid4().hex
        g.t0 = time.perf_counter()

    @app.after_request
    def _finish(resp):
        resp.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        if not request.path.startswith(_SKIP_ACCESS_LOG):
            access.info("%s %s -> %s", request.method, request.path, resp.status_code, extra={
                "request_id": getattr(g, "request_id", "-"), "method": request.method, "path": request.path,
                "status": resp.status_code, "ip": request.remote_addr,
                "duration_ms": round((time.perf_counter() - getattr(g, "t0", time.perf_counter())) * 1000, 1)})
        return resp


def init_sentry(app: Flask) -> None:
    dsn = app.config["SENTRY_DSN"]
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=dsn, integrations=[FlaskIntegration()], environment=app.config["APP_ENV"],
                        release=app.config["APP_VERSION"], send_default_pii=False, traces_sample_rate=0.0)
        app.logger.info("Sentry error reporting enabled")
    except ImportError:
        app.logger.warning("SENTRY_DSN is set but sentry-sdk is not installed (pip install sentry-sdk[flask])")
