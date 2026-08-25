"""Families and groups -- the container a member belongs to."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.invite_link import InviteLink
    from app.models.member import Member


class GroupKind(str):
    """Kind of grouping. Plain strings keep this portable and easy to extend."""

    FAMILY = "family"
    GROUP = "group"
    HOUSEHOLD = "household"
    COMPANY = "company"

    ALL = ("family", "group", "household", "company")


class Group(TimestampMixin, db.Model):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)

    # Stored as a VARCHAR with a CHECK constraint (native_enum=False) instead of
    # a database ENUM type, because native enums differ wildly between backends
    # and are painful to alter.
    kind: Mapped[str] = mapped_column(
        SAEnum(
            *GroupKind.ALL,
            name="group_kind",
            native_enum=False,
            length=20,
            validate_strings=True,
        ),
        default=GroupKind.FAMILY,
        nullable=False,
    )

    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(40))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    members: Mapped[List["Member"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Member.id",
    )
    invite_links: Mapped[List["InviteLink"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def size(self) -> int:
        return len(self.members)

    def to_dict(self, include_members: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "notes": self.notes,
            "size": self.size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_members:
            data["members"] = [m.to_dict() for m in self.members]
        return data

    def __repr__(self) -> str:
        return f"<Group {self.id} {self.name!r}>"
