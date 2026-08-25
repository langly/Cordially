"""Application factory."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import get_config
from app.extensions import db, migrate

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


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    # Imported for their side effect of registering with the metadata, so that
    # create_all() and Alembic autogenerate can see every table.
    from app import models  # noqa: F401

    from app.api import api_bp
    from app.invite import invite_bp
    from app.web import web_bp

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(invite_bp)
    app.register_blueprint(web_bp)

    from app.cli import register_cli

    register_cli(app)

    @app.shell_context_processor
    def _shell_context():
        from app.models import Event, Group, Invitation, Member

        return {
            "db": db,
            "Group": Group,
            "Member": Member,
            "Event": Event,
            "Invitation": Invitation,
        }

    return app
