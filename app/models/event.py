"""Parties and events."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    from app.models.invitation import Invitation
    from app.models.invite_link import InviteLink


class Event(TimestampMixin, db.Model):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(String(255))

    starts_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, index=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)

    capacity: Mapped[Optional[int]] = mapped_column(Integer)

    invitations: Mapped[List["Invitation"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    invite_links: Mapped[List["InviteLink"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def counts(self) -> dict:
        """RSVP tally for this event, split into adults and children.

        Two kinds of group contribute to the head count:

        * **restricted** groups are counted person by person, using each
          member's ``is_child`` flag (plus-ones are assumed to be adults);
        * **open** groups report their own numbers, so their supplied head count
          replaces their named members entirely -- that is the whole point of an
          open invitation. A group that accepted without filling the numbers in
          falls back to being counted by name, so they are never lost.
        """
        from app.models.invitation import RsvpStatus

        tally = {status: 0 for status in RsvpStatus.ALL}
        for inv in self.invitations:
            tally[inv.rsvp] = tally.get(inv.rsvp, 0) + 1
        tally["invited"] = len(self.invitations)

        open_links = {
            link.group_id: link
            for link in self.invite_links
            if link.is_open and not link.revoked and link.has_headcount
        }

        adults = children = 0
        accepted_open_groups = set()

        for inv in self.invitations:
            if inv.rsvp != RsvpStatus.YES:
                continue
            group_id = inv.member.group_id
            if group_id is not None and group_id in open_links:
                accepted_open_groups.add(group_id)
                continue
            if inv.member.is_child:
                children += 1
            else:
                adults += 1
            adults += inv.plus_ones or 0

        for group_id in accepted_open_groups:
            link = open_links[group_id]
            adults += link.adults_attending or 0
            children += link.children_attending or 0

        tally["adults"] = adults
        tally["children"] = children
        tally["attending"] = adults + children
        return tally

    def to_dict(self, include_counts: bool = True) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "capacity": self.capacity,
        }
        if include_counts:
            data["counts"] = self.counts()
        return data

    def __repr__(self) -> str:
        return f"<Event {self.id} {self.name!r}>"
