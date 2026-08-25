"""Host accounts.

Guests never have accounts -- RSVPs happen through an unauthenticated invite
token. Users here are hosts (and optionally site admins) who manage events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import hashlib

from flask_login import UserMixin
from sqlalchemy import Boolean, Column, ForeignKey, String, Table, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event


# Werkzeug defaults to scrypt, which needs an OpenSSL build that provides it --
# some Python builds (notably macOS system Python against LibreSSL) do not.
# Fall back to PBKDF2 there. Existing hashes keep working either way, because
# the algorithm is recorded in the hash string itself.
PASSWORD_HASH_METHOD = "scrypt" if hasattr(hashlib, "scrypt") else "pbkdf2:sha256"


# Co-hosts. Kept as a plain association table because the pairing carries no
# data of its own -- a co-host can currently do everything the owner can.
event_hosts = Table(
    "event_hosts",
    db.metadata,
    Column("event_id", ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


def _hash_method() -> str:
    """Config wins when there is an app context, so tests can use a cheap factor
    without weakening the real default."""
    try:
        from flask import current_app

        return current_app.config.get("PASSWORD_HASH_METHOD") or PASSWORD_HASH_METHOD
    except RuntimeError:  # outside an app context, e.g. a plain script
        return PASSWORD_HASH_METHOD


class User(TimestampMixin, UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # Flask-Login checks `is_active` before establishing a session, so this
    # column deliberately shadows UserMixin.is_active: deactivating a user
    # blocks login without deleting their events.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )

    owned_events: Mapped[List["Event"]] = relationship(
        back_populates="owner", foreign_keys="Event.owner_id"
    )
    co_hosted_events: Mapped[List["Event"]] = relationship(
        secondary=event_hosts, back_populates="co_hosts"
    )

    # --- passwords ---------------------------------------------------------

    def set_password(self, password: str) -> None:
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        self.password_hash = generate_password_hash(password, method=_hash_method())

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password or "")

    # --- display -----------------------------------------------------------

    @property
    def display_name(self) -> str:
        return self.name or self.email

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "is_admin": self.is_admin,
            "is_active": self.is_active,
            "owned_events": len(self.owned_events),
        }

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email!r}{' admin' if self.is_admin else ''}>"
