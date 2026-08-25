"""Parties and events."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin
from app.models.types import UtcDateTime
from app.themes import DEFAULT_LAYOUT, DEFAULT_THEME, get_layout, get_theme

if TYPE_CHECKING:
    from app.models.invitation import Invitation
    from app.models.invite_link import InviteLink
    from app.models.user import User


class Event(TimestampMixin, db.Model):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(String(255))

    starts_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime, index=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)

    capacity: Mapped[Optional[int]] = mapped_column(Integer)

    # Nullable so events that predate accounts stay readable; an event with no
    # owner is manageable by site admins only.
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # Appearance of this event's invitation cards. Stored as plain strings and
    # resolved through app.themes, so adding or renaming a theme never needs a
    # migration -- unknown names fall back to the default.
    card_theme: Mapped[str] = mapped_column(
        String(32), default=DEFAULT_THEME, server_default=DEFAULT_THEME, nullable=False
    )
    card_layout: Mapped[str] = mapped_column(
        String(32), default=DEFAULT_LAYOUT, server_default=DEFAULT_LAYOUT, nullable=False
    )

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
    owner: Mapped[Optional["User"]] = relationship(
        back_populates="owned_events", foreign_keys=[owner_id]
    )
    co_hosts: Mapped[List["User"]] = relationship(
        secondary="event_hosts", back_populates="co_hosted_events"
    )

    def is_managed_by(self, user) -> bool:
        """Single source of truth for "may this user act on this event?".

        Site admins may manage anything. Otherwise it is the owner or a
        co-host -- co-hosts currently have the same powers as the owner.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if user.is_admin:
            return True
        if self.owner_id is not None and self.owner_id == user.id:
            return True
        return any(host.id == user.id for host in self.co_hosts)

    def is_managed_by_directly(self, user) -> bool:
        """Owner or co-host, ignoring the site-admin override.

        Admins can manage every event, but they are not *hosts* of it -- the
        co-host picker still offers them.
        """
        if user is None:
            return False
        if self.owner_id is not None and self.owner_id == user.id:
            return True
        return any(host.id == user.id for host in self.co_hosts)

    def hosts(self) -> List["User"]:
        """Owner first, then co-hosts."""
        people = [self.owner] if self.owner else []
        return people + sorted(self.co_hosts, key=lambda u: (u.name or u.email).lower())

    @property
    def theme(self):
        return get_theme(self.card_theme)

    @property
    def layout(self):
        return get_layout(self.card_layout)

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
            "card_theme": self.card_theme,
            "card_layout": self.card_layout,
            "owner_id": self.owner_id,
            "owner": self.owner.display_name if self.owner else None,
            "co_hosts": [u.display_name for u in self.co_hosts],
        }
        if include_counts:
            data["counts"] = self.counts()
        return data

    def __repr__(self) -> str:
        return f"<Event {self.id} {self.name!r}>"
