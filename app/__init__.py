"""Application factory."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import get_config
from app.extensions import db, login_manager, migrate

load_dotenv()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """SQLite ignores foreign keys unless asked, which would let ON DELETE
    CASCADE silently do nothing.  Guarded by a driver check so this is inert on
    Postgres/MySQL."""
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# Endpoints reachable without a session. Everything else is denied by default,
# so a newly added route is protected unless it is named here on purpose.
PUBLIC_ENDPOINTS = frozenset({"auth.login", "static"})

# The whole invite blueprint is public: guests RSVP with a token, never a login.
PUBLIC_BLUEPRINTS = frozenset({"invite"})


def _install_auth_guard(app: Flask) -> None:
    """Require a session for every request except the explicitly public ones."""
    from flask import jsonify, redirect, request, url_for
    from flask_login import current_user

    @app.before_request
    def _require_login():
        endpoint = request.endpoint
        if endpoint is None:
            return None  # unrouted; let Flask produce the 404
        if endpoint in PUBLIC_ENDPOINTS or request.blueprint in PUBLIC_BLUEPRINTS:
            return None
        if current_user.is_authenticated:
            return None

        if request.blueprint == "api":
            return jsonify({"error": "Authentication required"}), 401
        # full_path always appends "?"; drop it when there is no query string.
        target = request.full_path.rstrip("?") or request.path
        return redirect(url_for("auth.login", next=target))


def _install_proxy_fix(app: Flask) -> None:
    """Trust proxy headers when explicitly configured to sit behind one.

    ``x_prefix`` is the piece that makes the app mount-point agnostic: nginx
    sends ``X-Forwarded-Prefix: /e`` and every generated URL picks it up, so the
    same code serves at ``/``, ``/e`` or any depth without edits. Off by default
    so a directly-exposed app never trusts spoofable headers.
    """
    # Config captures the env at import; also read it here so a deploy can set
    # PROXY_FIX_HOPS in the process environment without a config change.
    hops = app.config.get("PROXY_FIX_HOPS") or int(os.environ.get("PROXY_FIX_HOPS", "0"))
    if hops <= 0:
        return

    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_prefix=hops
    )


def _install_request_logging(app: Flask) -> None:
    """Log one line per request, and any unhandled error with a traceback."""
    import logging
    import time

    from flask import g, request
    from flask_login import current_user

    request_log = logging.getLogger("events.request")

    @app.before_request
    def _mark_start():
        g._start_time = time.monotonic()

    @app.after_request
    def _log_request(response):
        if request.endpoint == "static":
            return response
        elapsed_ms = (time.monotonic() - getattr(g, "_start_time", time.monotonic())) * 1000
        try:
            who = current_user.email if current_user.is_authenticated else "-"
        except Exception:
            who = "-"
        request_log.info(
            "%s %s %s %.0fms user=%s",
            request.method,
            request.full_path.rstrip("?"),
            response.status_code,
            elapsed_ms,
            who,
        )
        return response

    @app.errorhandler(Exception)
    def _log_unhandled(error):
        from werkzeug.exceptions import HTTPException

        # Intentional HTTP responses (404, 403, ValueError->400) pass through;
        # only genuine crashes are logged, then re-raised so Flask renders 500.
        if isinstance(error, HTTPException):
            return error
        app.logger.exception("Unhandled exception on %s %s", request.method, request.path)
        raise error


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))

    from app.logging_config import init_logging

    init_logging(app)

    # Fail loud on insecure production config before wiring anything up.
    from app.startup import validate_config

    validate_config(app)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Imported for their side effect of registering with the metadata, so that
    # create_all() and Alembic autogenerate can see every table.
    from app import models  # noqa: F401

    from app.admin import admin_bp
    from app.api import api_bp
    from app.auth import auth_bp
    from app.invite import invite_bp
    from app.web import web_bp

    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(auth_bp)
    app.register_blueprint(invite_bp)
    app.register_blueprint(web_bp)

    _install_auth_guard(app)
    _install_request_logging(app)
    _install_proxy_fix(app)

    from app.cli import register_cli

    register_cli(app)

    @app.shell_context_processor
    def _shell_context():
        from app.models import Event, Group, Invitation, InviteLink, Member, User

        return {
            "db": db,
            "Group": Group,
            "Member": Member,
            "Event": Event,
            "Invitation": Invitation,
            "InviteLink": InviteLink,
            "User": User,
        }

    return app
