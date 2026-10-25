from __future__ import annotations

import gzip
import os
import threading

from flask import Flask, Response, request
from werkzeug.security import safe_join

TYPES = {"text/html", "text/css", "text/plain", "text/xml", "text/javascript", "application/javascript",
         "application/json", "application/xml", "application/manifest+json", "image/svg+xml"}
MIN_SIZE = 860
_static: dict[str, tuple[float, int, bytes]] = {}
_lock = threading.Lock()


def _accepts_gzip() -> bool:
    for part in request.headers.get("Accept-Encoding", "").lower().split(","):
        name, _, params = part.strip().partition(";")
        if name.strip() not in ("gzip", "*"):
            continue
        q = 1.0
        for p in params.split(";"):
            k, _, v = p.strip().partition("=")
            if k == "q":
                try:
                    q = float(v)
                except ValueError:
                    q = 0.0
        return q > 0
    return False


def _tag(resp: Response) -> None:
    etag = resp.headers.get("ETag")
    if etag and etag.endswith('"') and not etag.endswith('-gz"'):
        resp.headers["ETag"] = etag[:-1] + '-gz"'


def _static_gzip(app: Flask, rel: str) -> bytes | None:
    path = safe_join(app.static_folder, rel)
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    hit = _static.get(path)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    with open(path, "rb") as fh:
        raw = fh.read()
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    if len(gz) >= len(raw):
        gz = b""
    with _lock:
        _static[path] = (st.st_mtime, st.st_size, gz)
    return gz


def init_compression(app: Flask) -> None:
    if not app.config.get("COMPRESS_RESPONSES", True):
        return
    level = int(app.config.get("COMPRESS_LEVEL", 5))

    @app.before_request
    def _gz_etag_in():
        inm = request.environ.get("HTTP_IF_NONE_MATCH")
        if inm and '-gz"' in inm:
            request.environ["HTTP_IF_NONE_MATCH"] = inm.replace('-gz"', '"')

    @app.after_request
    def _gz(resp: Response):
        if resp.mimetype not in TYPES or request.method != "GET":
            return resp
        resp.vary.add("Accept-Encoding")
        if "Content-Encoding" in resp.headers or request.path.startswith("/api/auth") or not _accepts_gzip():
            return resp
        is_static = request.path.startswith("/static/")
        if resp.status_code == 304:
            _tag(resp)
            return resp
        if resp.status_code != 200 or "Range" in request.headers:
            return resp
        if resp.direct_passthrough:
            if not is_static:
                return resp
            gz = _static_gzip(app, request.path[len("/static/"):])
            if not gz:
                return resp
            old = resp.response
            resp.direct_passthrough = False
            resp.set_data(gz)
            if hasattr(old, "close"):
                old.close()
        else:
            if resp.is_streamed:
                return resp
            data = resp.get_data()
            if len(data) < MIN_SIZE:
                return resp
            gz = gzip.compress(data, compresslevel=level)
            if len(gz) >= len(data):
                return resp
            resp.set_data(gz)
        _tag(resp)
        resp.headers["Content-Encoding"] = "gzip"
        return resp
