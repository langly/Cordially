"""Portable column types.

SQLite has no native timezone-aware timestamp: it stores whatever string it is
given and hands back a naive datetime, while PostgreSQL returns an aware one.
Left alone, that means the same code yields different values depending on the
backend -- exactly the kind of silent difference that makes a database swap
painful.  ``UtcDateTime`` normalises both directions so every backend behaves
like the timezone-aware one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """A timezone-aware datetime that always reads back as UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            # Naive input (e.g. an HTML datetime-local field) is read as UTC.
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
