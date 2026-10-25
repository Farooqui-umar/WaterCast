import logging

from flask import jsonify, session

from ..errors import ApiError
from ..extensions import limiter
from ..security import audit, authenticate, current_user, require_csrf_token, start_session
from ..validation import clean_text, json_body
from . import bp

log = logging.getLogger("watercast.auth")


@bp.post("/auth/login")
@limiter.limit("10 per 15 minutes")
def login():
    data = json_body()
    username = clean_text(data.get("username"), "Username", max_len=64, required=True)
    password = data.get("password")
    if not isinstance(password, str) or not password or len(password) > 256:
        raise ApiError(400, "Password is required.")
    user = authenticate(username, password)
    if user is None:
        log.warning("failed login for %r", username)
        raise ApiError(401, "Invalid username or password.")
    csrf = start_session(user)
    audit("login")
    return jsonify({"user": user.to_public(), "csrf": csrf})


@bp.get("/auth/session")
def session_status():
    user = current_user()
    if user is None:
        return jsonify({"authenticated": False, "user": None, "csrf": None})
    return jsonify({"authenticated": True, "user": user.to_public(), "csrf": session.get("csrf")})


@bp.get("/auth/me")
def me():
    user = current_user()
    if user is None:
        raise ApiError(401, "Not signed in.")
    return jsonify({"user": user.to_public(), "csrf": session.get("csrf")})


@bp.post("/auth/logout")
def logout():
    if current_user() is not None:
        require_csrf_token()
        audit("logout")
    session.clear()
    return jsonify({"ok": True})
