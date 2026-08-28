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
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_SQLITE_URL = f"sqlite:///{BASE_DIR / 'instance' / 'events.db'}"

# Sentinel default. The startup guard refuses to boot in production while this
# is still in force, because it lets anyone forge a session cookie.
DEFAULT_SECRET_KEY = "dev-secret-change-me"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)

    # Google sign-in (OpenID Connect). Set both to enable the "Sign in with
    # Google" button; match-only -- it authenticates existing accounts, never
    # creates them. Leave unset to keep password-only login.
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    # Cookie hardening. Secure defaults to on (production over HTTPS); the app
    # factory turns it off for local http dev (FLASK_DEBUG). SameSite=Lax is the
    # second line of CSRF defence behind the CSRF tokens on forms.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)
    REMEMBER_COOKIE_DURATION = timedelta(days=14)

    # None means "use the strongest method this Python build supports"
    # (see app/models/user.py). Overridden in tests for speed.
    PASSWORD_HASH_METHOD = os.environ.get("PASSWORD_HASH_METHOD")

    # Base URL used when building shareable invite links. Set this in
    # production so links generated behind a proxy point at the public host.
    INVITE_BASE_URL = os.environ.get("INVITE_BASE_URL")

    # --- Email -------------------------------------------------------------
    # Backend: "console" logs the message (dev default, sends nothing), "smtp"
    # sends for real, "memory" captures in-process (tests). Swappable like the
    # database, so dev needs no mail server.
    # Hard opt-out. When False, the app never queues or sends any email,
    # regardless of MAIL_BACKEND -- an operator-level guarantee.
    MAIL_ENABLED = _env_bool("MAIL_ENABLED", True)
    MAIL_BACKEND = os.environ.get("MAIL_BACKEND", "console")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "Cordially <no-reply@localhost>")
    MAIL_MAX_ATTEMPTS = int(os.environ.get("MAIL_MAX_ATTEMPTS", "3"))

    MAIL_SMTP_HOST = os.environ.get("MAIL_SMTP_HOST", "localhost")
    MAIL_SMTP_PORT = int(os.environ.get("MAIL_SMTP_PORT", "587"))
    MAIL_SMTP_USERNAME = os.environ.get("MAIL_SMTP_USERNAME")
    MAIL_SMTP_PASSWORD = os.environ.get("MAIL_SMTP_PASSWORD")
    MAIL_SMTP_USE_TLS = _env_bool("MAIL_SMTP_USE_TLS", True)   # STARTTLS on 587
    MAIL_SMTP_USE_SSL = _env_bool("MAIL_SMTP_USE_SSL", False)  # implicit TLS on 465
    MAIL_SMTP_TIMEOUT = int(os.environ.get("MAIL_SMTP_TIMEOUT", "30"))

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
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    MAIL_BACKEND = "memory"
    # One PBKDF2 round: the suite creates many accounts and is not testing the
    # KDF's cost factor. Never used outside tests.
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:1"
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    WTF_CSRF_ENABLED = False


def get_config(name: str | None = None) -> type[Config]:
    if name == "testing" or os.environ.get("FLASK_ENV") == "testing":
        return TestConfig
    return Config
