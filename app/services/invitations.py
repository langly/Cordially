"""Invitation and RSVP operations."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select

from app.extensions import db
from app.models import Event, Group, Invitation, Member, RsvpStatus


def get_invitation(event_id: int, member_id: int) -> Optional[Invitation]:
    stmt = select(Invitation).where(
        Invitation.event_id == event_id, Invitation.member_id == member_id
    )
    return db.session.scalars(stmt).first()


def invite_member(event: Event, member: Member, commit: bool = True) -> Invitation:
    """Idempotent: inviting someone already invited returns their invitation."""
    existing = get_invitation(event.id, member.id)
    if existing:
        return existing

    invitation = Invitation(event_id=event.id, member_id=member.id)
    db.session.add(invitation)
    if commit:
        db.session.commit()
    return invitation


def invite_group(event: Event, group: Group) -> List[Invitation]:
    """Invite every member of a family/group in one go."""
    invitations = [invite_member(event, member, commit=False) for member in group.members]
    db.session.commit()
    return invitations


def uninvite(invitation: Invitation) -> None:
    db.session.delete(invitation)
    db.session.commit()


def set_rsvp(invitation: Invitation, status: str, plus_ones: Optional[int] = None) -> Invitation:
    invitation.set_rsvp(status)
    if plus_ones is not None:
        if plus_ones < 0:
            raise ValueError("plus_ones cannot be negative")
        invitation.plus_ones = plus_ones
    db.session.commit()
    return invitation


def set_group_rsvp(event: Event, group: Group, status: str) -> List[Invitation]:
    """Answer for a whole family at once -- the common case at RSVP time."""
    if status not in RsvpStatus.ALL:
        raise ValueError(f"Unknown RSVP status: {status!r}")

    member_ids = [m.id for m in group.members]
    if not member_ids:
        return []

    stmt = select(Invitation).where(
        Invitation.event_id == event.id, Invitation.member_id.in_(member_ids)
    )
    invitations = list(db.session.scalars(stmt))
    for invitation in invitations:
        invitation.set_rsvp(status)
    db.session.commit()
    return invitations


def set_table(invitation: Invitation, table_assignment: Optional[str]) -> Invitation:
    invitation.table_assignment = (table_assignment or "").strip() or None
    db.session.commit()
    return invitation


def group_summary(event: Event) -> List[dict]:
    """Guest list rolled up per family/group, for the event detail page.

    Mirrors :meth:`Event.counts` -- open groups show the numbers they reported
    rather than a per-person breakdown.
    """
    links = {link.group_id: link for link in event.invite_links}
    buckets: dict = {}

    for invitation in event.invitations:
        member = invitation.member
        group = member.group
        key = group.id if group else None
        link = links.get(key) if key else None
        bucket = buckets.setdefault(
            key,
            {
                "group_id": key,
                "group_name": group.name if group else "Individual guests",
                "kind": group.kind if group else None,
                "link": link,
                "restricted": link.restricted if link else True,
                "invitations": [],
                "counts": {status: 0 for status in RsvpStatus.ALL},
                "attending": 0,
                "adults": 0,
                "children": 0,
                "accepted": False,
            },
        )
        bucket["invitations"].append(invitation)
        bucket["counts"][invitation.rsvp] += 1
        if invitation.rsvp == RsvpStatus.YES:
            bucket["accepted"] = True
            if member.is_child:
                bucket["children"] += 1
            else:
                bucket["adults"] += 1
            bucket["adults"] += invitation.plus_ones or 0

    for bucket in buckets.values():
        link = bucket["link"]
        if link and link.is_open and not link.revoked and link.has_headcount:
            # Reported numbers replace the named tally for open groups.
            bucket["adults"] = (link.adults_attending or 0) if bucket["accepted"] else 0
            bucket["children"] = (link.children_attending or 0) if bucket["accepted"] else 0
            bucket["from_headcount"] = bucket["accepted"]
        else:
            bucket["from_headcount"] = False

        bucket["attending"] = bucket["adults"] + bucket["children"]
        bucket["invitations"].sort(key=lambda i: (i.member.first_name or "").lower())

    return sorted(
        buckets.values(),
        key=lambda b: (b["group_id"] is None, (b["group_name"] or "").lower()),
    )
