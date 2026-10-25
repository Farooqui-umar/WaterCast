from flask import request
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
cache = Cache()
_UNLIMITED = {"static", "index", "login_page", "privacy_page", "healthz", "robots", "manifest", "favicon",
              "api.health", "api.ready"}
limiter = Limiter(key_func=get_remote_address, default_limits_exempt_when=lambda: request.endpoint in _UNLIMITED)
