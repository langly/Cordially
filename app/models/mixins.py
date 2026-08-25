"""Reusable model building blocks."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Mapped, mapped_column

from app.models.types import UtcDateTime


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Timestamps are generated in Python rather than by the database so that every
    backend stores the same value.  SQLite has no native timezone support and
    each engine spells "now" differently.
    """
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
