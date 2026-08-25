"""Family/group operations."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Group, GroupKind, Member


def list_groups(search: Optional[str] = None) -> List[Group]:
    stmt = select(Group).options(selectinload(Group.members)).order_by(Group.name)
    if search:
        stmt = stmt.where(Group.name.ilike(f"%{search}%"))
    return list(db.session.scalars(stmt))


def get_group(group_id: int) -> Optional[Group]:
    return db.session.get(Group, group_id)


def get_group_or_404(group_id: int) -> Group:
    return db.get_or_404(Group, group_id)


def find_by_name(name: str) -> Optional[Group]:
    stmt = select(Group).where(func.lower(Group.name) == name.strip().lower())
    return db.session.scalars(stmt).first()


def create_group(
    name: str,
    kind: str = GroupKind.FAMILY,
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    notes: Optional[str] = None,
) -> Group:
    name = (name or "").strip()
    if not name:
        raise ValueError("Group name is required")
    if find_by_name(name):
        raise ValueError(f"A group named {name!r} already exists")
    if kind not in GroupKind.ALL:
        raise ValueError(f"Unknown group kind: {kind!r}")

    group = Group(
        name=name,
        kind=kind,
        contact_email=contact_email or None,
        contact_phone=contact_phone or None,
        notes=notes or None,
    )
    db.session.add(group)
    db.session.commit()
    return group


def update_group(group: Group, **fields) -> Group:
    allowed = {"name", "kind", "contact_email", "contact_phone", "notes"}
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key == "name":
            value = value.strip()
            existing = find_by_name(value)
            if existing and existing.id != group.id:
                raise ValueError(f"A group named {value!r} already exists")
        if key == "kind" and value not in GroupKind.ALL:
            raise ValueError(f"Unknown group kind: {value!r}")
        setattr(group, key, value)
    db.session.commit()
    return group


def delete_group(group: Group) -> None:
    """Deletes the group and, by cascade, its members and their invitations."""
    db.session.delete(group)
    db.session.commit()


def member_count(group_id: int) -> int:
    stmt = select(func.count(Member.id)).where(Member.group_id == group_id)
    return db.session.scalar(stmt) or 0
