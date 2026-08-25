"""Shared extension instances.

Kept in their own module so models, blueprints and the app factory can import
them without creating circular imports.
"""

from __future__ import annotations

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Explicit constraint naming is required for Alembic to autogenerate reliable
# migrations, and for SQLite's batch-mode ALTER emulation to find constraints
# by name.  Without it, unnamed constraints are undroppable on SQLite.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


db = SQLAlchemy(model_class=Base)

# render_as_batch rewrites ALTER TABLE into create/copy/drop for SQLite, which
# otherwise cannot alter or drop columns.  It is a no-op on other backends.
migrate = Migrate(render_as_batch=True)
