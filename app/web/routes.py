"""Server-rendered pages."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask import flash, redirect, render_template, request, url_for

from app.models import GroupKind, RsvpStatus
from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invitations as invites_svc
from app.services import invite_links as links_svc
from app.services import members as members_svc
from app.web import web_bp


def _form_dt(field: str) -> Optional[datetime]:
    raw = (request.form.get(field) or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"Could not read the date/time in {field!r}")


def _form_int(field: str) -> Optional[int]:
    raw = (request.form.get(field) or "").strip()
    return int(raw) if raw.isdigit() else None


@web_bp.get("/")
def index():
    return render_template(
        "index.html",
        events=events_svc.list_events(),
        groups=groups_svc.list_groups(),
    )


# --- Groups -----------------------------------------------------------------

@web_bp.get("/groups")
def groups():
    return render_template(
        "groups.html",
        groups=groups_svc.list_groups(search=request.args.get("q")),
        kinds=GroupKind.ALL,
        q=request.args.get("q", ""),
    )


@web_bp.post("/groups")
def create_group():
    try:
        group = groups_svc.create_group(
            name=request.form.get("name", ""),
            kind=request.form.get("kind", GroupKind.FAMILY),
            contact_email=request.form.get("contact_email"),
            contact_phone=request.form.get("contact_phone"),
            notes=request.form.get("notes"),
        )
    except ValueError as err:
        flash(str(err), "error")
        return redirect(url_for("web.groups"))

    flash(f"Added {group.name}.", "success")
    return redirect(url_for("web.group_detail", group_id=group.id))


@web_bp.get("/groups/<int:group_id>")
def group_detail(group_id: int):
    return render_template(
        "group_detail.html",
        group=groups_svc.get_group_or_404(group_id),
        kinds=GroupKind.ALL,
        all_groups=groups_svc.list_groups(),
    )


@web_bp.post("/groups/<int:group_id>/delete")
def delete_group(group_id: int):
    group = groups_svc.get_group_or_404(group_id)
    name = group.name
    groups_svc.delete_group(group)
    flash(f"Deleted {name} and everyone in it.", "success")
    return redirect(url_for("web.groups"))


@web_bp.post("/groups/<int:group_id>/members")
def add_member(group_id: int):
    group = groups_svc.get_group_or_404(group_id)
    try:
        members_svc.create_member(
            first_name=request.form.get("first_name", ""),
            last_name=request.form.get("last_name"),
            group_id=group.id,
            email=request.form.get("email"),
            phone=request.form.get("phone"),
            is_child=bool(request.form.get("is_child")),
            age=_form_int("age"),
            dietary_notes=request.form.get("dietary_notes"),
        )
        flash("Member added.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("web.group_detail", group_id=group.id))


@web_bp.post("/members/<int:member_id>/delete")
def delete_member(member_id: int):
    member = members_svc.get_member_or_404(member_id)
    group_id = member.group_id
    members_svc.delete_member(member)
    flash("Member removed.", "success")
    if group_id:
        return redirect(url_for("web.group_detail", group_id=group_id))
    return redirect(url_for("web.groups"))


@web_bp.post("/members/<int:member_id>/move")
def move_member(member_id: int):
    member = members_svc.get_member_or_404(member_id)
    origin = member.group_id
    target = _form_int("group_id")
    try:
        members_svc.move_to_group(member, target)
        flash(f"Moved {member.full_name}.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("web.group_detail", group_id=target or origin))


# --- Events -----------------------------------------------------------------

@web_bp.get("/events")
def events():
    return render_template("events.html", events=events_svc.list_events())


@web_bp.post("/events")
def create_event():
    try:
        event = events_svc.create_event(
            name=request.form.get("name", ""),
            description=request.form.get("description"),
            location=request.form.get("location"),
            starts_at=_form_dt("starts_at"),
            ends_at=_form_dt("ends_at"),
            capacity=_form_int("capacity"),
        )
    except ValueError as err:
        flash(str(err), "error")
        return redirect(url_for("web.events"))

    flash(f"Created {event.name}.", "success")
    return redirect(url_for("web.event_detail", event_id=event.id))


@web_bp.get("/events/<int:event_id>")
def event_detail(event_id: int):
    event = events_svc.get_event_or_404(event_id)
    invited_ids = {inv.member_id for inv in event.invitations}
    links = {link.group_id: link for link in links_svc.links_for_event(event.id)}
    return render_template(
        "event_detail.html",
        event=event,
        summary=invites_svc.group_summary(event),
        counts=event.counts(),
        groups=groups_svc.list_groups(),
        uninvited=[m for m in members_svc.list_members() if m.id not in invited_ids],
        statuses=RsvpStatus.ALL,
        links=links,
    )


@web_bp.post("/events/<int:event_id>/delete")
def delete_event(event_id: int):
    event = events_svc.get_event_or_404(event_id)
    name = event.name
    events_svc.delete_event(event)
    flash(f"Deleted {name}.", "success")
    return redirect(url_for("web.events"))


@web_bp.post("/events/<int:event_id>/invite")
def invite(event_id: int):
    event = events_svc.get_event_or_404(event_id)
    group_id = _form_int("group_id")
    member_id = _form_int("member_id")

    if group_id:
        group = groups_svc.get_group_or_404(group_id)
        # Absent checkbox means open; the form ships it checked by default.
        restricted = bool(request.form.get("restricted"))
        created = invites_svc.invite_group(event, group)
        links_svc.create_link(event, group, restricted=restricted)
        mode = (
            f"{len(created)} named guests"
            if restricted
            else "they can bring extra guests"
        )
        flash(f"Invited {group.name} ({mode}) — share link ready below.", "success")
    elif member_id:
        member = members_svc.get_member_or_404(member_id)
        invites_svc.invite_member(event, member)
        flash(f"Invited {member.full_name}.", "success")
    else:
        flash("Pick a group or a person to invite.", "error")

    return redirect(url_for("web.event_detail", event_id=event.id))


@web_bp.post("/events/<int:event_id>/rsvp")
def rsvp(event_id: int):
    event = events_svc.get_event_or_404(event_id)
    status = request.form.get("rsvp", "")
    group_id = _form_int("group_id")
    member_id = _form_int("member_id")

    try:
        if group_id:
            group = groups_svc.get_group_or_404(group_id)
            updated = invites_svc.set_group_rsvp(event, group, status)
            flash(f"Marked {len(updated)} people as {status}.", "success")
        elif member_id:
            invitation = invites_svc.get_invitation(event.id, member_id)
            if invitation is None:
                raise ValueError("That person has not been invited yet")
            invites_svc.set_rsvp(invitation, status)
        else:
            raise ValueError("Nothing to update")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("web.event_detail", event_id=event.id))


@web_bp.post("/invitations/<int:invitation_id>/remove")
def remove_invitation(invitation_id: int):
    from app.extensions import db
    from app.models import Invitation

    invitation = db.get_or_404(Invitation, invitation_id)
    event_id = invitation.event_id
    invites_svc.uninvite(invitation)
    flash("Removed from the guest list.", "success")
    return redirect(url_for("web.event_detail", event_id=event_id))


# --- Shareable invite links -------------------------------------------------

@web_bp.post("/events/<int:event_id>/links/<int:group_id>/<action>")
def manage_link(event_id: int, group_id: int, action: str):
    """Create, revoke, restore or rotate a group's shareable invitation link."""
    event = events_svc.get_event_or_404(event_id)
    group = groups_svc.get_group_or_404(group_id)

    if action == "create":
        links_svc.create_link(event, group, restricted=bool(request.form.get("restricted")))
        flash(f"Invitation link ready for {group.name}.", "success")
    else:
        link = links_svc.get_link(event.id, group.id)
        if link is None:
            flash("No link exists for that group yet.", "error")
        elif action == "revoke":
            links_svc.revoke(link)
            flash(f"Revoked the link for {group.name}.", "success")
        elif action == "restore":
            links_svc.restore(link)
            flash(f"Reactivated the link for {group.name}.", "success")
        elif action == "restrict":
            links_svc.set_restricted(link, True)
            flash(f"{group.name} is now limited to its named members.", "success")
        elif action == "open":
            links_svc.set_restricted(link, False)
            flash(f"{group.name} can now bring extra guests.", "success")
        elif action == "rotate":
            links_svc.rotate(link)
            flash(f"New link issued for {group.name} — the old one no longer works.", "success")
        else:
            flash("Unknown action.", "error")

    return redirect(url_for("web.event_detail", event_id=event.id))


@web_bp.post("/events/<int:event_id>/links")
def create_all_links(event_id: int):
    event = events_svc.get_event_or_404(event_id)
    links = links_svc.create_links_for_all_groups(event)
    flash(f"{len(links)} invitation link{'' if len(links) == 1 else 's'} ready.", "success")
    return redirect(url_for("web.event_detail", event_id=event.id))
