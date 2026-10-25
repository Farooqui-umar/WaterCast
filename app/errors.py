from __future__ import annotations

import logging

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

log = logging.getLogger("watercast")

CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
         409: "conflict", 413: "payload_too_large", 415: "unsupported_media_type", 422: "invalid", 429: "rate_limited",
         500: "server_error", 502: "upstream_unavailable", 503: "unavailable"}


class ApiError(HTTPException):
    def __init__(self, code: int, message: str):
        super().__init__(description=message)
        self.code = code


def _json_error(status: int, message: str):
    resp = jsonify({"error": message, "code": CODES.get(status, "error"), "request_id": getattr(g, "request_id", None)})
    resp.status_code = status
    return resp


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        status = exc.code or 500
        if not request.path.startswith("/api/"):
            return exc
        message = exc.description if status != 429 else "Too many requests - please slow down and try again shortly."
        return _json_error(status, message)

    @app.errorhandler(Exception)
    def unhandled(exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.path)
        if request.path.startswith("/api/"):
            return _json_error(500, "Something went wrong on our side. Please try again.")
        return "Internal Server Error", 500
