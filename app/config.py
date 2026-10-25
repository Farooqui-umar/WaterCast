from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

_TRUE = {"1", "true", "yes", "on"}


def env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    return default if raw is None or raw == "" else raw.strip().lower() in _TRUE


def env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def env_list(env: Mapping[str, str], name: str, default: str = "") -> list[str]:
    raw = env.get(name, default) or ""
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


class ConfigError(RuntimeError):
    pass


def normalise_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def on_vercel(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("VERCEL"))


def load_settings(env: Mapping[str, str] | None = None) -> dict:
    env = os.environ if env is None else env
    vercel = on_vercel(env)
    app_env = (env.get("APP_ENV") or ("production" if vercel else "development")).strip().lower()
    if app_env not in {"development", "production", "testing"}:
        raise ConfigError("APP_ENV must be development, production or testing")
    prod = app_env == "production"
    testing = app_env == "testing"

    secret = env.get("SECRET_KEY") or ""
    if prod:
        if len(secret) < 32 or secret.lower().startswith(("change", "dev", "secret", "example")):
            raise ConfigError("SECRET_KEY must be set to a random value of at least 32 characters "
                              "(generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\")")
    elif not secret:
        secret = secrets.token_urlsafe(48)

    db_url = env.get("DATABASE_URL") or env.get("POSTGRES_URL") or ""
    ephemeral_db = False
    if prod and not db_url and not vercel:
        raise ConfigError("DATABASE_URL must be set in production (PostgreSQL is recommended)")
    if not db_url and vercel:
        db_url = "sqlite:////tmp/watercast.db"
        ephemeral_db = True
    if not db_url:
        (BASE_DIR / "instance").mkdir(exist_ok=True)
        db_url = "sqlite:///" + str(BASE_DIR / "instance" / ("test.db" if testing else "watercast.db"))
    db_url = normalise_database_url(db_url)

    engine_options: dict = {"pool_pre_ping": True}
    if not db_url.startswith("sqlite"):
        engine_options.update(pool_recycle=1800, pool_size=env_int(env, "DB_POOL_SIZE", 2 if vercel else 5),
                              max_overflow=env_int(env, "DB_MAX_OVERFLOW", 3 if vercel else 10))

    redis_url = env.get("REDIS_URL") or env.get("KV_URL") or ""
    contact = env.get("CONTACT_EMAIL") or ""
    open_meteo_key = env.get("OPEN_METEO_API_KEY") or ""
    geocoder_key = env.get("GEOCODER_API_KEY") or ""
    geocoder_url = env.get("GEOCODER_URL") or "https://nominatim.openstreetmap.org/search"
    public_nominatim = "nominatim.openstreetmap.org" in geocoder_url

    settings = {
        "APP_ENV": app_env,
        "ON_VERCEL": vercel,
        "EPHEMERAL_DATABASE": ephemeral_db,
        "AUTO_MIGRATE": env_bool(env, "AUTO_MIGRATE", vercel),
        "CRON_SECRET": env.get("CRON_SECRET") or "",
        "TESTING": testing,
        "DEBUG": False,
        "SECRET_KEY": secret,
        "APP_VERSION": env.get("APP_VERSION") or "1.2.0",
        "ASSET_VERSION": env.get("ASSET_VERSION") or env.get("APP_VERSION") or "1.2.0",
        "SQLALCHEMY_DATABASE_URI": db_url,
        "SQLALCHEMY_ENGINE_OPTIONS": engine_options,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SESSION_COOKIE_NAME": "wc_session",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": env_bool(env, "SESSION_COOKIE_SECURE", prod),
        "PERMANENT_SESSION_LIFETIME": env_int(env, "SESSION_LIFETIME_HOURS", 8) * 3600,
        "MAX_CONTENT_LENGTH": env_int(env, "MAX_CONTENT_KB", 64) * 1024,
        "JSON_SORT_KEYS": False,
        "TRUSTED_PROXY_COUNT": env_int(env, "TRUSTED_PROXY_COUNT", 1 if prod else 0),
        "FORCE_HTTPS": env_bool(env, "FORCE_HTTPS", prod),
        "RATELIMIT_ENABLED": env_bool(env, "RATELIMIT_ENABLED", not testing),
        "RATELIMIT_STORAGE_URI": env.get("RATELIMIT_STORAGE_URI") or redis_url or "memory://",
        "RATELIMIT_DEFAULT": env.get("RATELIMIT_DEFAULT") or "240 per minute",
        "RATELIMIT_HEADERS_ENABLED": True,
        "CACHE_TYPE": "RedisCache" if redis_url else ("SimpleCache" if testing else "FileSystemCache"),
        "CACHE_DIR": env.get("CACHE_DIR") or ("/tmp/watercast-cache" if vercel else str(BASE_DIR / "instance" / "cache")),
        "CACHE_THRESHOLD": env_int(env, "CACHE_THRESHOLD", 5000),
        "CACHE_REDIS_URL": redis_url or None,
        "CACHE_DEFAULT_TIMEOUT": 600,
        "CACHE_KEY_PREFIX": "wc:",
        "LOG_LEVEL": (env.get("LOG_LEVEL") or ("INFO" if prod else "DEBUG")).upper(),
        "LOG_FORMAT": (env.get("LOG_FORMAT") or ("json" if prod else "text")).lower(),
        "SENTRY_DSN": env.get("SENTRY_DSN") or "",
        "ADMIN_USERNAME": env.get("ADMIN_USERNAME") or "",
        "ADMIN_PASSWORD": env.get("ADMIN_PASSWORD") or "",
        "LOGIN_MAX_FAILURES": env_int(env, "LOGIN_MAX_FAILURES", 5),
        "LOGIN_LOCK_MINUTES": env_int(env, "LOGIN_LOCK_MINUTES", 15),
        "MIN_PASSWORD_LENGTH": env_int(env, "MIN_PASSWORD_LENGTH", 12),
        "DATA_RETENTION_DAYS": env_int(env, "DATA_RETENTION_DAYS", 365),
        "CONTACT_EMAIL": contact,
        "HTTP_TIMEOUT": env_float(env, "HTTP_TIMEOUT", 10.0),
        "HTTP_USER_AGENT": f"WaterCast/{env.get('APP_VERSION') or '1.0'} (+{contact or 'https://example.org/contact'})",
        "OPEN_METEO_API_KEY": open_meteo_key,
        "OPEN_METEO_FORECAST_URL": env.get("OPEN_METEO_FORECAST_URL") or (
            "https://customer-api.open-meteo.com/v1/forecast" if open_meteo_key else "https://api.open-meteo.com/v1/forecast"),
        "OPEN_METEO_GEOCODING_URL": env.get("OPEN_METEO_GEOCODING_URL") or (
            "https://customer-geocoding-api.open-meteo.com/v1/search" if open_meteo_key
            else "https://geocoding-api.open-meteo.com/v1/search"),
        "GEOCODER_URL": geocoder_url,
        "GEOCODER_REVERSE_URL": env.get("GEOCODER_REVERSE_URL") or geocoder_url.rsplit("/", 1)[0] + "/reverse",
        "GEOCODER_API_KEY": geocoder_key,
        "GEOCODER_KEY_PARAM": env.get("GEOCODER_KEY_PARAM") or "key",
        "GEOCODER_MIN_INTERVAL": env_float(env, "GEOCODER_MIN_INTERVAL", 1.1 if public_nominatim else 0.0),
        "NEWS_ENABLED": env_bool(env, "NEWS_ENABLED", True),
        "NEWS_SOURCE": (env.get("NEWS_SOURCE") or "google").lower(),
        "NEWS_RSS_FEEDS": env_list(env, "NEWS_RSS_FEEDS"),
        "SACHET_FEEDS": env_list(env, "SACHET_FEEDS",
                                 "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml,"
                                 "https://sachet.ndma.gov.in/cap_public_website/rss/rss_maharashtra.xml"),
        "SACHET_INSECURE_TLS_FALLBACK": env_bool(env, "SACHET_INSECURE_TLS_FALLBACK", vercel or not prod),
        "HOT_ALERT_THRESHOLD": env_int(env, "HOT_ALERT_THRESHOLD", 10),
        "HOT_ALERT_DAYS": env_int(env, "HOT_ALERT_DAYS", 3),
        "COMPRESS_RESPONSES": env_bool(env, "COMPRESS_RESPONSES", not vercel),
        "COMPRESS_LEVEL": env_int(env, "COMPRESS_LEVEL", 5),
        "GEMINI_API_KEY": env.get("GEMINI_API_KEY") or GEMINI_API_KEY,
        "GEMINI_API_URL": env.get("GEMINI_API_URL") or "https://generativelanguage.googleapis.com/v1beta",
        "GEMINI_MODEL": env.get("GEMINI_MODEL") or "gemini-flash-latest",
        "GEMINI_FALLBACK_MODEL": env.get("GEMINI_FALLBACK_MODEL") or "gemini-flash-lite-latest",
        "GEMINI_TIMEOUT": env_float(env, "GEMINI_TIMEOUT", 30.0),
        "GEMINI_TRUST_TTL": env_int(env, "GEMINI_TRUST_TTL", 6 * 3600),
        "GEMINI_RISK_TTL": env_int(env, "GEMINI_RISK_TTL", 1800),
        "GEMINI_TIPS_TTL": env_int(env, "GEMINI_TIPS_TTL", 3 * 3600),
    }
    if settings["NEWS_SOURCE"] not in {"google", "rss"}:
        raise ConfigError("NEWS_SOURCE must be 'google' or 'rss'")
    if prod and public_nominatim and not contact:
        raise ConfigError("CONTACT_EMAIL is required in production when using the public OpenStreetMap geocoder "
                          "(its usage policy requires an identifying contact); or point GEOCODER_URL at your own/paid instance")
    return settings
