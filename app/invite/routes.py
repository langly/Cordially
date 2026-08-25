"""The public invitation card: view it, respond for the whole group."""

from __future__ import annotations

from typing import Optional

from flask import abort, flash, redirect, render_template, request, url_for

from app.invite import invite_bp
from app.models import RsvpStatus
from app.services import invite_links as links_svc


def _count_field(field: str) -> Optional[int]:
    """Read a head-count field. Blank means "not answered", 0 means "none of us"."""
    raw = (request.form.get(field) or "").strip()
    if raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ValueError("Please give whole numbers for adults and children")
    if value < 0:
        raise ValueError("Numbers cannot be negative")
    if value > 500:
        raise ValueError("That is more guests than we can take")
    return value


def _load(token: str, for_response: bool = False):
    """Resolve a token to a link, or fail closed.

    Unknown tokens 404 rather than reporting anything about the event; revoked
    ones return 410 so a holder of an old link learns it is dead rather than
    silently seeing nothing.
    """
    link = links_svc.get_by_token(token)
    if link is None:
        abort(404)
    if link.revoked:
        abort(410)
    if for_response and not link.group.members:
        abort(409)
    return link


@invite_bp.get("/<token>")
def card(token: str):
    link = links_svc.get_by_token(token)
    if link is None:
        abort(404)
    if link.revoked:
        abort(410)

    links_svc.record_view(link)

    rsvps = {
        inv.member_id: inv
        for inv in link.event.invitations
        if inv.member.group_id == link.group_id
    }
    # The group's answer is whatever everyone shares; mixed replies show as None
    # so the card doesn't claim a decision nobody made.
    statuses = {inv.rsvp for inv in rsvps.values()}
    group_status = statuses.pop() if len(statuses) == 1 else None

    return render_template(
        "invite/card.html",
        link=link,
        event=link.event,
        group=link.group,
        members=link.group.members,
        rsvps=rsvps,
        group_status=group_status,
        mixed=len(statuses) > 0,
        statuses=RsvpStatus.ALL,
        restricted=link.restricted,
    )


@invite_bp.post("/<token>/respond")
def respond(token: str):
    """One reply on behalf of the entire group."""
    link = _load(token, for_response=True)
    status = request.form.get("rsvp", "")

    try:
        updated = links_svc.respond(
            link,
            status,
            responded_by=request.form.get("responded_by"),
            note=request.form.get("note"),
            adults=_count_field("adults_attending"),
            children=_count_field("children_attending"),
        )
    except ValueError as err:
        flash(str(err), "error")
        return redirect(url_for("invite.card", token=token))

    if status == RsvpStatus.YES and link.is_open and link.has_headcount:
        bits = []
        if link.adults_attending:
            bits.append(f"{link.adults_attending} adult{'' if link.adults_attending == 1 else 's'}")
        if link.children_attending:
            bits.append(
                f"{link.children_attending} child{'' if link.children_attending == 1 else 'ren'}"
            )
        who = " and ".join(bits) if bits else "nobody"
        flash(f"Wonderful — we've got {who} down as coming.", "success")
    elif status == RsvpStatus.YES:
        flash(f"Wonderful — we've got all {len(updated)} of you down as coming.", "success")
    elif status == RsvpStatus.NO:
        flash("Thanks for letting us know — you'll be missed.", "success")
    else:
        flash("Thanks — we've noted your reply.", "success")

    return redirect(url_for("invite.card", token=token))


@invite_bp.post("/<token>/member/<int:member_id>")
def member_rsvp(token: str, member_id: int):
    """Adjust a single person after the group answer."""
    link = _load(token, for_response=True)
    try:
        links_svc.set_member_rsvp(link, member_id, request.form.get("rsvp", ""))
        links_svc.set_dietary_note(link, member_id, request.form.get("dietary_notes"))
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("invite.card", token=token))


# Scoped to this blueprint so the public card styling never leaks into admin
# error pages.
@invite_bp.errorhandler(404)
def _not_found(err):
    return render_template("invite/unavailable.html", reason="unknown"), 404


@invite_bp.errorhandler(409)
def _empty_group(err):
    return render_template("invite/unavailable.html", reason="empty"), 409


@invite_bp.errorhandler(410)
def _gone(err):
    return render_template("invite/unavailable.html", reason="revoked"), 410
