"""Individual people, each optionally belonging to a family/group."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.group import Group
    from app.models.invitation import Invitation


class Member(TimestampMixin, db.Model):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Nullable so a solo guest can exist without inventing a one-person family.
    # ondelete=CASCADE means removing a family removes its people; the matching
    # ORM cascade lives on Group.members.
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )

    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(80))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(40))

    is_child: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    age: Mapped[Optional[int]] = mapped_column(Integer)

    dietary_notes: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    group: Mapped[Optional["Group"]] = relationship(back_populates="members")
    invitations: Mapped[List["Invitation"]] = relationship(
        back_populates="member",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "group_id": self.group_id,
            "group_name": self.group.name if self.group else None,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "is_child": self.is_child,
            "age": self.age,
            "dietary_notes": self.dietary_notes,
            "notes": self.notes,
        }

    def __repr__(self) -> str:
        return f"<Member {self.id} {self.full_name!r}>"
