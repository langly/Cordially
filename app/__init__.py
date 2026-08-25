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


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))

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
