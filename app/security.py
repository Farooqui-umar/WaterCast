from __future__ import annotations

import hmac
import logging
import secrets
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, Response, current_app, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .errors import ApiError
from .extensions import db
from .models import AuditEvent, User
from .timeutil import utcnow

log = logging.getLogger("watercast.security")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-CSRF-Token"
ROLES = ("official", "admin")

_DUMMY_HASH = generate_password_hash("not-a-real-password")


def validate_password(password: str, username: str = "") -> None:
    minimum = current_app.config["MIN_PASSWORD_LENGTH"]
    if len(password) < minimum:
        raise ValueError(f"Password must be at least {minimum} characters long.")
    if username and username.lower() in password.lower():
        raise ValueError("Password must not contain the username.")
    if password.lower() in {"password1234", "123456789012", "qwertyuiopas", "administrator"}:
        raise ValueError("That password is too common.")
    if len(set(password)) < 5:
        raise ValueError("Password is too repetitive.")


def create_user(username: str, password: str, role: str = "official") -> User:
    username = username.strip()
    if not username or len(username) > 64:
        raise ValueError("Username must be 1-64 characters.")
    if role not in ROLES:
        raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
    validate_password(password, username)
    if User.query.filter(db.func.lower(User.username) == username.lower()).first():
        raise ValueError(f"User {username!r} already exists.")
    user = User(username=username, password_hash=generate_password_hash(password), role=role)
    db.session.add(user)
    db.session.commit()
    return user


def authenticate(username: str, password: str) -> User | None:
    cfg = current_app.config
    user = User.query.filter(db.func.lower(User.username) == (username or "").strip().lower()).first()
    now = utcnow()
    if user is None or not user.is_active:
        check_password_hash(_DUMMY_HASH, password or "")
        return None
    if user.locked_until and user.locked_until > now:
        check_password_hash(_DUMMY_HASH, password or "")
        return None
    if not check_password_hash(user.password_hash, password or ""):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= cfg["LOGIN_MAX_FAILURES"]:
            user.locked_until = now + timedelta(minutes=cfg["LOGIN_LOCK_MINUTES"])
            user.failed_logins = 0
            log.warning("account locked after repeated failures: %s", user.username)
        db.session.commit()
        return None
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    db.session.commit()
    return user


def start_session(user: User) -> str:
    session.clear()
    session["uid"] = user.id
    session["csrf"] = secrets.token_urlsafe(32)
    session.permanent = True
    return session["csrf"]


_UNSET = object()


def current_user() -> User | None:
    cached = request.environ.get("watercast.user", _UNSET)
    if cached is not _UNSET:
        return cached
    user = None
    uid = session.get("uid")
    if uid is not None:
        user = db.session.get(User, uid)
        if user is not None and not user.is_active:
            user = None
    request.environ["watercast.user"] = user
    return user


def staff_required(*roles: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                raise ApiError(401, "Staff sign-in required.")
            if roles and user.role not in roles:
                raise ApiError(403, "You do not have permission to do that.")
            require_csrf_token()
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def _same_origin(origin: str) -> bool:
    try:
        return urlparse(origin).netloc.lower() == request.host.lower()
    except ValueError:
        return False


def check_origin() -> None:
    if request.method in SAFE_METHODS:
        return
    if not (session.get("uid") or request.endpoint == "api.login"):
        return
    origin = request.headers.get("Origin")
    if origin and origin != "null" and not _same_origin(origin):
        raise ApiError(403, "Cross-site request blocked.")


def require_csrf_token() -> None:
    if request.method in SAFE_METHODS:
        return
    expected = session.get("csrf") or ""
    sent = request.headers.get(CSRF_HEADER, "")
    if not expected or not hmac.compare_digest(expected, sent):
        raise ApiError(403, "Security token missing or expired. Reload the page and try again.")


def audit(action: str, target: str = "", detail: str = "") -> None:
    user = current_user()
    db.session.add(AuditEvent(actor=user.username if user else "system", action=action[:60], target=str(target)[:120],
                              detail=detail[:500], ip=request.remote_addr if request else None))
    db.session.commit()
    log.info("audit action=%s target=%s actor=%s", action, target, user.username if user else "system")


CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "media-src 'self' blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def init_security(app: Flask) -> None:
    @app.before_request
    def _origin():
        check_origin()

    @app.after_request
    def _headers(resp: Response):
        h = resp.headers
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=(), payment=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if app.config["FORCE_HTTPS"]:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        return resp
