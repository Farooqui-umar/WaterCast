from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import click
from flask import Flask, current_app
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import Alert, AuditEvent, CommunityPost, SOSRequest, TrustScore, User, Vote
from .security import create_user, validate_password
from .timeutil import utcnow


DEFAULT_USERS = (("JIBRAN", "JIBRAN", "admin"), ("ADMIN", "ADMIN", "admin"))


def seed_default_users() -> None:
    for name, password, role in DEFAULT_USERS:
        user = User.query.filter(db.func.lower(User.username) == name.lower()).first()
        if user is None:
            user = User(username=name, role=role)
            db.session.add(user)
        user.username, user.role, user.is_active = name, role, True
        user.password_hash = generate_password_hash(password)
        user.failed_logins, user.locked_until = 0, None
    db.session.commit()


def bootstrap_admin(*, generate_in_dev: bool = False) -> str | None:
    if User.query.filter_by(role="admin").first():
        return None
    cfg = current_app.config
    username, password = cfg["ADMIN_USERNAME"], cfg["ADMIN_PASSWORD"]
    if username and password:
        create_user(username, password, "admin")
        current_app.logger.info("created admin user %r from environment", username)
        return None
    if generate_in_dev and cfg["APP_ENV"] != "production":
        generated = secrets.token_urlsafe(12)
        create_user(username or "admin", generated, "admin")
        return generated
    current_app.logger.warning("No admin user exists. Set ADMIN_USERNAME and ADMIN_PASSWORD, or run: flask create-user")
    return None


@click.command("create-user")
@click.argument("username")
@click.option("--role", type=click.Choice(["official", "admin"]), default="official", show_default=True)
@click.password_option(confirmation_prompt=True)
@with_appcontext
def create_user_cmd(username, role, password):
    try:
        user = create_user(username, password, role)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created {user.role} {user.username!r}.")


def _find_user(username: str) -> User:
    user = User.query.filter(db.func.lower(User.username) == username.strip().lower()).first()
    if user is None:
        raise click.ClickException(f"No such user: {username!r}")
    return user


@click.command("list-users")
@with_appcontext
def list_users_cmd():
    rows = User.query.order_by(User.username).all()
    if not rows:
        click.echo("No staff accounts yet. Create one with: flask create-user <username>")
    for u in rows:
        last = u.last_login_at.strftime("%Y-%m-%d %H:%M UTC") if u.last_login_at else "never"
        flags = ("" if u.is_active else " [disabled]") + (" [locked]" if u.locked_until and u.locked_until > utcnow() else "")
        click.echo(f"{u.username:24} {u.role:9} last sign-in: {last}{flags}")


@click.command("set-password")
@click.argument("username")
@click.password_option(confirmation_prompt=True)
@with_appcontext
def set_password_cmd(username, password):
    user = _find_user(username)
    try:
        validate_password(password, user.username)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    user.password_hash = generate_password_hash(password)
    user.failed_logins, user.locked_until = 0, None
    db.session.add(AuditEvent(actor="cli", action="user.set_password", target=user.username))
    db.session.commit()
    click.echo(f"Password updated for {user.username!r} (lockout cleared).")


@click.command("deactivate-user")
@click.argument("username")
@click.option("--undo", is_flag=True, help="Re-enable the account")
@with_appcontext
def deactivate_user_cmd(username, undo):
    user = _find_user(username)
    user.is_active = bool(undo)
    db.session.add(AuditEvent(actor="cli", action="user.enable" if undo else "user.disable", target=user.username))
    db.session.commit()
    click.echo(f"{user.username!r} is now {'enabled' if undo else 'disabled'}.")


@click.command("bootstrap-admin")
@with_appcontext
def bootstrap_admin_cmd():
    try:
        bootstrap_admin()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def purge_old(days: int) -> dict:
    cutoff = utcnow() - timedelta(days=days)
    counts = {}
    for model in (SOSRequest, Vote, Alert, CommunityPost):
        counts[model.__tablename__] = model.query.filter(model.created_at < cutoff).delete(synchronize_session=False)
    counts["audit_events"] = AuditEvent.query.filter(AuditEvent.created_at < utcnow() - timedelta(days=days * 2)) \
        .delete(synchronize_session=False)
    live = {r[0] for r in db.session.query(SOSRequest.device_id).distinct()}
    counts["trust_scores"] = TrustScore.query.filter(~TrustScore.device_id.in_(live)).delete(synchronize_session=False) \
        if live else TrustScore.query.delete(synchronize_session=False)
    db.session.commit()
    return counts


@click.command("purge-old")
@click.option("--days", type=int, default=None, help="Override DATA_RETENTION_DAYS")
@with_appcontext
def purge_old_cmd(days):
    days = days if days is not None else current_app.config["DATA_RETENTION_DAYS"]
    if days <= 0:
        click.echo("Retention is disabled (DATA_RETENTION_DAYS <= 0); nothing deleted.")
        return
    counts = purge_old(days)
    click.echo(f"Deleted data older than {days} days: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


def _parse_legacy_ts(value):
    if not value:
        return utcnow()
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return utcnow()


@click.command("import-legacy")
@click.argument("sqlite_path", type=click.Path(exists=True, dir_okay=False))
@with_appcontext
def import_legacy_cmd(sqlite_path):
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    n = {"sos": 0, "votes": 0, "trust": 0, "posts": 0}
    if "sos_requests" in tables:
        for r in src.execute("SELECT * FROM sos_requests"):
            db.session.add(SOSRequest(device_id=r["device_id"], locality_name=r["locality_name"], lat=r["lat"], lon=r["lon"],
                                      issue_type=r["issue_type"], urgency=r["urgency"], description=r["description"],
                                      has_photo=bool(r["has_photo"]), status=r["status"] or "Pending",
                                      created_at=_parse_legacy_ts(r["created_at"])))
            n["sos"] += 1
    if "votes" in tables:
        for r in src.execute("SELECT * FROM votes"):
            db.session.add(Vote(device_id=r["device_id"], locality_name=r["locality_name"], lat=r["lat"], lon=r["lon"],
                                created_at=_parse_legacy_ts(r["created_at"])))
            n["votes"] += 1
    if "trust_scores" in tables:
        for r in src.execute("SELECT * FROM trust_scores"):
            if db.session.get(TrustScore, r["device_id"]) is None:
                db.session.add(TrustScore(device_id=r["device_id"], score=r["score"], reports_filed=r["reports_filed"],
                                          confirmed_accurate=r["confirmed_accurate"]))
                n["trust"] += 1
    if "community_posts" in tables:
        for r in src.execute("SELECT * FROM community_posts"):
            db.session.add(CommunityPost(device_id=r["device_id"] or "legacy", author=r["author"], locality=r["locality"],
                                         text=r["text"], created_at=_parse_legacy_ts(r["created_at"])))
            n["posts"] += 1
    db.session.commit()
    click.echo("Imported: " + ", ".join(f"{k}={v}" for k, v in n.items()) + "  (demo localities/alerts/news are not imported)")


@click.command("doctor")
@with_appcontext
def doctor_cmd():
    from sqlalchemy import text
    cfg = current_app.config
    ok = True

    def line(good, label, detail=""):
        nonlocal ok
        ok = ok and good
        click.echo(f"[{'ok' if good else '!!'}] {label}" + (f" - {detail}" if detail else ""))

    line(True, "environment", cfg["APP_ENV"])
    try:
        db.session.execute(text("SELECT 1"))
        line(True, "database reachable", cfg["SQLALCHEMY_DATABASE_URI"].split("@")[-1])
    except Exception as exc:
        line(False, "database reachable", str(exc)[:120])
    line(cfg["SQLALCHEMY_DATABASE_URI"].startswith("postgresql"), "PostgreSQL in use",
         "SQLite is fine for development, use PostgreSQL in production")
    line(cfg["CACHE_TYPE"] == "RedisCache", "shared cache / rate-limit store (Redis)",
         "without REDIS_URL each worker keeps its own counters")
    line(bool(User.query.filter_by(role="admin").first()), "an admin user exists")
    line(bool(cfg["CONTACT_EMAIL"]), "CONTACT_EMAIL set", "required by the public OpenStreetMap geocoder policy")
    line(cfg["SESSION_COOKIE_SECURE"], "secure cookies", "needs HTTPS")
    raise SystemExit(0 if ok else 1)


def register(app: Flask) -> None:
    commands = (create_user_cmd, list_users_cmd, set_password_cmd, deactivate_user_cmd, bootstrap_admin_cmd,
                purge_old_cmd, import_legacy_cmd, doctor_cmd)
    for cmd in commands:
        app.cli.add_command(cmd)
