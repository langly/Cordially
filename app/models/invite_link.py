"""Shareable invitation links.

One link per (event, group).  The group passes it around amongst themselves and
whoever opens it first can answer on behalf of everyone -- so the token *is* the
credential, and must be unguessable.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.group import Group

TOKEN_BYTES = 32  # -> 43 url-safe characters, ~256 bits


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


class InviteLink(TimestampMixin, db.Model):
    __tablename__ = "invite_links"
    __table_args__ = (
        UniqueConstraint("event_id", "group_id", name="uq_invite_link_event_group"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Length is fixed by TOKEN_BYTES; unique + indexed because every page view
    # looks the link up by this column alone.
    token: Mapped[str] = mapped_column(
        String(64), default=generate_token, nullable=False, unique=True, index=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Restricted: only the named members of the group are invited.
    # Open (restricted=False): the group reports how many adults and children
    # are coming instead of naming them.
    restricted: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    adults_attending: Mapped[Optional[int]] = mapped_column(Integer)
    children_attending: Mapped[Optional[int]] = mapped_column(Integer)

    # Who answered on behalf of the group, and what they said alongside the RSVP.
    responded_by: Mapped[Optional[str]] = mapped_column(String(120))
    responded_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    response_note: Mapped[Optional[str]] = mapped_column(Text)

    opened_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    event: Mapped["Event"] = relationship(back_populates="invite_links")
    group: Mapped["Group"] = relationship(back_populates="invite_links")

    @property
    def is_active(self) -> bool:
        return not self.revoked

    @property
    def has_response(self) -> bool:
        return self.responded_at is not None

    @property
    def is_open(self) -> bool:
        """Open invitations let the group bring guests who aren't named members."""
        return not self.restricted

    @property
    def has_headcount(self) -> bool:
        """True once an open group has actually supplied numbers.

        Explicit zeros count -- "nobody from us" is an answer. Until numbers are
        given, attendance falls back to the named members.
        """
        return self.adults_attending is not None or self.children_attending is not None

    @property
    def headcount(self) -> int:
        return (self.adults_attending or 0) + (self.children_attending or 0)

    def set_headcount(self, adults: Optional[int], children: Optional[int]) -> None:
        for label, value in (("adults", adults), ("children", children)):
            if value is not None and value < 0:
                raise ValueError(f"Number of {label} cannot be negative")
        self.adults_attending = adults
        self.children_attending = children

    def path(self) -> str:
        return f"/i/{self.token}"

    def url(self) -> str:
        """Absolute URL, safe to call outside a request context."""
        from flask import current_app, url_for

        external_base = current_app.config.get("INVITE_BASE_URL")
        if external_base:
            return f"{external_base.rstrip('/')}{self.path()}"
        return url_for("invite.card", token=self.token, _external=True)

    def rotate(self) -> str:
        """Issue a fresh token, invalidating the previously shared link."""
        self.token = generate_token()
        return self.token

    def to_dict(self, include_token: bool = True) -> dict:
        data = {
            "id": self.id,
            "event_id": self.event_id,
            "group_id": self.group_id,
            "group_name": self.group.name if self.group else None,
            "revoked": self.revoked,
            "restricted": self.restricted,
            "adults_attending": self.adults_attending,
            "children_attending": self.children_attending,
            "headcount": self.headcount if self.has_headcount else None,
            "responded_by": self.responded_by,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
            "response_note": self.response_note,
            "view_count": self.view_count,
        }
        if include_token:
            data["token"] = self.token
            data["path"] = self.path()
        return data

    def __repr__(self) -> str:
        return f"<InviteLink event={self.event_id} group={self.group_id}>"
