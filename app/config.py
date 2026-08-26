"""Application configuration.

The database is selected entirely through the ``DATABASE_URL`` environment
variable, so moving off SQLite later means changing one setting -- no code
changes.  Examples::

    sqlite:///instance/events.db                       (default)
    postgresql+psycopg://user:pw@localhost/events
    mysql+pymysql://user:pw@localhost/events
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_URL = f"sqlite:///{BASE_DIR / 'instance' / 'events.db'}"

# Sentinel default. The startup guard refuses to boot in production while this
# is still in force, because it lets anyone forge a session cookie.
DEFAULT_SECRET_KEY = "dev-secret-change-me"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)

    # None means "use the strongest method this Python build supports"
    # (see app/models/user.py). Overridden in tests for speed.
    PASSWORD_HASH_METHOD = os.environ.get("PASSWORD_HASH_METHOD")

    # Base URL used when building shareable invite links. Set this in
    # production so links generated behind a proxy point at the public host.
    INVITE_BASE_URL = os.environ.get("INVITE_BASE_URL")

    # Number of trusted reverse proxies in front of the app. 0 (default) means
    # "not behind a proxy" -- X-Forwarded-* headers are ignored, because a
    # direct client could otherwise spoof them. Set to 1 behind a single nginx.
    # When > 0, the app honours X-Forwarded-Proto/Host/For and, crucially,
    # X-Forwarded-Prefix -- which is what lets it be mounted under any sub-path
    # (/e, /cordially, …) with only nginx config, no code changes.
    PROXY_FIX_HOPS = int(os.environ.get("PROXY_FIX_HOPS", "0"))

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URL)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.environ.get("SQL_ECHO", "").lower() in {"1", "true", "yes"}

    # Connection pooling matters for server databases and is ignored by SQLite's
    # default driver, so it is safe to set unconditionally.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }


class TestConfig(Config):
    TESTING = True
    # One PBKDF2 round: the suite creates many accounts and is not testing the
    # KDF's cost factor. Never used outside tests.
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:1"
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    WTF_CSRF_ENABLED = False


def get_config(name: str | None = None) -> type[Config]:
    if name == "testing" or os.environ.get("FLASK_ENV") == "testing":
        return TestConfig
    return Config
