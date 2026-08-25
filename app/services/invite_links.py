"""Shareable per-group invitation links."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Event, Group, InviteLink, Member, RsvpStatus
from app.models.mixins import utcnow
from app.services import invitations as invites_svc


def get_link(event_id: int, group_id: int) -> Optional[InviteLink]:
    stmt = select(InviteLink).where(
        InviteLink.event_id == event_id, InviteLink.group_id == group_id
    )
    return db.session.scalars(stmt).first()


def get_by_token(token: str) -> Optional[InviteLink]:
    """Look up a link by its token, eager-loading everything the card renders."""
    if not token:
        return None
    stmt = (
        select(InviteLink)
        .options(
            selectinload(InviteLink.event),
            selectinload(InviteLink.group).selectinload(Group.members),
        )
        .where(InviteLink.token == token)
    )
    return db.session.scalars(stmt).first()


def links_for_event(event_id: int) -> List[InviteLink]:
    stmt = (
        select(InviteLink)
        .options(selectinload(InviteLink.group))
        .join(InviteLink.group)
        .where(InviteLink.event_id == event_id)
        .order_by(Group.name)
    )
    return list(db.session.scalars(stmt))


def create_link(event: Event, group: Group, restricted: bool = True) -> InviteLink:
    """Get or create the link for a group, inviting its members as a side effect.

    Idempotent: a group already holding a link keeps the same URL, so a link
    that has already been shared around never breaks. ``restricted`` is applied
    on every call, so re-inviting a group is also how you change the mode.
    """
    link = get_link(event.id, group.id)
    if link is None:
        link = InviteLink(event_id=event.id, group_id=group.id)
        db.session.add(link)
    link.restricted = bool(restricted)

    invites_svc.invite_group(event, group)
    db.session.commit()
    return link


def create_links_for_all_groups(event: Event) -> List[InviteLink]:
    """Issue a link to every group that has someone on the guest list."""
    group_ids = {
        inv.member.group_id for inv in event.invitations if inv.member.group_id is not None
    }
    links = []
    for group_id in group_ids:
        group = db.session.get(Group, group_id)
        if group is not None:
            links.append(create_link(event, group))
    return links


def set_restricted(link: InviteLink, restricted: bool) -> InviteLink:
    """Switch a group between "named members only" and "bring who you like"."""
    link.restricted = bool(restricted)
    if link.restricted:
        # Numbers are meaningless once the invitation is restricted again.
        link.adults_attending = None
        link.children_attending = None
    db.session.commit()
    return link


def set_headcount(
    link: InviteLink, adults: Optional[int], children: Optional[int]
) -> InviteLink:
    if link.restricted:
        raise ValueError("This invitation is limited to the named members")
    link.set_headcount(adults, children)
    db.session.commit()
    return link


def record_view(link: InviteLink) -> None:
    link.view_count = (link.view_count or 0) + 1
    if link.opened_at is None:
        link.opened_at = utcnow()
    db.session.commit()


def respond(
    link: InviteLink,
    status: str,
    responded_by: Optional[str] = None,
    note: Optional[str] = None,
    adults: Optional[int] = None,
    children: Optional[int] = None,
) -> List:
    """Answer on behalf of the whole group -- one reply covers everyone.

    Members added to the group after the link was shared are picked up here, so
    a late arrival is included in the answer rather than silently left pending.
    """
    if status not in RsvpStatus.ALL:
        raise ValueError(f"Unknown RSVP status: {status!r}")
    if link.revoked:
        raise ValueError("This invitation link is no longer active")
    if not link.group.members:
        raise ValueError("There is nobody in this group to respond for")

    if link.is_open:
        if status == RsvpStatus.NO:
            # Declining clears any numbers left over from an earlier "yes".
            link.set_headcount(None, None)
        elif adults is not None or children is not None:
            link.set_headcount(adults, children)

    invites_svc.invite_group(link.event, link.group)
    updated = invites_svc.set_group_rsvp(link.event, link.group, status)

    link.responded_by = (responded_by or "").strip()[:120] or None
    link.response_note = (note or "").strip() or None
    link.responded_at = utcnow()
    db.session.commit()
    return updated


def set_member_rsvp(link: InviteLink, member_id: int, status: str):
    """Adjust one person within the group, after the group-wide answer.

    Covers the common "we're all coming except one of the kids" case without
    making each person follow their own link.
    """
    if link.revoked:
        raise ValueError("This invitation link is no longer active")

    member = db.session.get(Member, member_id)
    if member is None or member.group_id != link.group_id:
        raise ValueError("That person is not part of this group")

    invitation = invites_svc.get_invitation(link.event_id, member_id)
    if invitation is None:
        invitation = invites_svc.invite_member(link.event, member)

    updated = invites_svc.set_rsvp(invitation, status)
    link.responded_at = utcnow()
    db.session.commit()
    return updated


def set_dietary_note(link: InviteLink, member_id: int, note: Optional[str]) -> Member:
    member = db.session.get(Member, member_id)
    if member is None or member.group_id != link.group_id:
        raise ValueError("That person is not part of this group")
    member.dietary_notes = (note or "").strip() or None
    db.session.commit()
    return member


def revoke(link: InviteLink) -> InviteLink:
    link.revoked = True
    db.session.commit()
    return link


def restore(link: InviteLink) -> InviteLink:
    link.revoked = False
    db.session.commit()
    return link


def rotate(link: InviteLink) -> InviteLink:
    """Issue a new token; anyone holding the old URL loses access."""
    link.rotate()
    link.revoked = False
    db.session.commit()
    return link


def delete_link(link: InviteLink) -> None:
    db.session.delete(link)
    db.session.commit()
