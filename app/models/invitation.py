"""Invitations: the link between a member and an event, carrying the RSVP."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.member import Member


class RsvpStatus(str):
    PENDING = "pending"
    YES = "yes"
    NO = "no"
    MAYBE = "maybe"

    ALL = ("pending", "yes", "no", "maybe")


class Invitation(TimestampMixin, db.Model):
    __tablename__ = "invitations"
    __table_args__ = (
        # One invitation per person per event; makes "invite this whole family"
        # safely repeatable.
        UniqueConstraint("event_id", "member_id", name="uq_invitation_event_member"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True
    )

    rsvp: Mapped[str] = mapped_column(
        SAEnum(
            *RsvpStatus.ALL,
            name="rsvp_status",
            native_enum=False,
            length=16,
            validate_strings=True,
        ),
        default=RsvpStatus.PENDING,
        nullable=False,
        index=True,
    )
    responded_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)
    plus_ones: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    table_assignment: Mapped[Optional[str]] = mapped_column(String(60))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    event: Mapped["Event"] = relationship(back_populates="invitations")
    member: Mapped["Member"] = relationship(back_populates="invitations")

    def set_rsvp(self, status: str) -> None:
        if status not in RsvpStatus.ALL:
            raise ValueError(f"Unknown RSVP status: {status!r}")
        self.rsvp = status
        self.responded_at = None if status == RsvpStatus.PENDING else utcnow()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "member_id": self.member_id,
            "member_name": self.member.full_name if self.member else None,
            "group_name": self.member.group.name if self.member and self.member.group else None,
            "rsvp": self.rsvp,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
            "plus_ones": self.plus_ones,
            "table_assignment": self.table_assignment,
            "notes": self.notes,
        }

    def __repr__(self) -> str:
        return f"<Invitation event={self.event_id} member={self.member_id} {self.rsvp}>"
