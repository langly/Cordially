"""Member operations."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Group, Member


def list_members(group_id: Optional[int] = None, search: Optional[str] = None) -> List[Member]:
    stmt = (
        select(Member)
        .options(joinedload(Member.group))
        .order_by(Member.last_name, Member.first_name)
    )
    if group_id is not None:
        stmt = stmt.where(Member.group_id == group_id)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                Member.first_name.ilike(pattern),
                Member.last_name.ilike(pattern),
                Member.email.ilike(pattern),
            )
        )
    return list(db.session.scalars(stmt))


def get_member(member_id: int) -> Optional[Member]:
    return db.session.get(Member, member_id)


def get_member_or_404(member_id: int) -> Member:
    return db.get_or_404(Member, member_id)


def create_member(
    first_name: str,
    last_name: Optional[str] = None,
    group_id: Optional[int] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    is_child: bool = False,
    age: Optional[int] = None,
    dietary_notes: Optional[str] = None,
    notes: Optional[str] = None,
) -> Member:
    first_name = (first_name or "").strip()
    if not first_name:
        raise ValueError("First name is required")

    if group_id is not None and db.session.get(Group, group_id) is None:
        raise ValueError(f"No group with id {group_id}")

    member = Member(
        first_name=first_name,
        last_name=(last_name or "").strip() or None,
        group_id=group_id,
        email=email or None,
        phone=phone or None,
        is_child=bool(is_child),
        age=age,
        dietary_notes=dietary_notes or None,
        notes=notes or None,
    )
    db.session.add(member)
    db.session.commit()
    return member


def update_member(member: Member, **fields) -> Member:
    allowed = {
        "first_name",
        "last_name",
        "group_id",
        "email",
        "phone",
        "is_child",
        "age",
        "dietary_notes",
        "notes",
    }
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "group_id" and value is not None and db.session.get(Group, value) is None:
            raise ValueError(f"No group with id {value}")
        if key == "first_name":
            value = (value or "").strip()
            if not value:
                raise ValueError("First name is required")
        setattr(member, key, value)
    db.session.commit()
    return member


def move_to_group(member: Member, group_id: Optional[int]) -> Member:
    """Reassign a member to a different family/group (None detaches them)."""
    return update_member(member, group_id=group_id)


def delete_member(member: Member) -> None:
    db.session.delete(member)
    db.session.commit()
