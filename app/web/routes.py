"""Server-rendered pages."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.audit import audit
from app.authz import event_or_403
from app.models import GroupKind, RsvpStatus
from app.themes import (
    DEFAULT_LAYOUT,
    DEFAULT_THEME,
    LAYOUTS,
    all_fonts_url,
    font_query_for,
    get_layout,
    get_theme,
    themes_by_mood,
)
from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invitations as invites_svc
from app.services import invite_links as links_svc
from app.services import mail as mail_svc
from app.services import members as members_svc
from app.services import users as users_svc
from app.preview_data import SAMPLE_GROUP, SAMPLE_LINK, SAMPLE_MEMBERS
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
        events=events_svc.list_events(current_user),
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

def _appearance_picker() -> dict:
    """Context for the theme/layout grid.

    ``all_fonts_url`` covers every theme in one request so each swatch previews
    in its real typeface -- worth it on a host-facing page, not on a card.
    """
    return {
        "theme_groups": themes_by_mood(),
        "layouts": LAYOUTS,
        "all_fonts_url": all_fonts_url(),
    }


@web_bp.get("/events")
def events():
    return render_template(
        "events.html",
        events=events_svc.list_events(current_user),
        default_theme=DEFAULT_THEME,
        default_layout=DEFAULT_LAYOUT,
        **_appearance_picker(),
    )


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
            card_theme=request.form.get("card_theme", DEFAULT_THEME),
            card_layout=request.form.get("card_layout", DEFAULT_LAYOUT),
            owner=current_user,
        )
    except ValueError as err:
        flash(str(err), "error")
        return redirect(url_for("web.events"))

    flash(f"Created {event.name}.", "success")
    return redirect(url_for("web.event_detail", event_id=event.id))


@web_bp.get("/events/<int:event_id>")
def event_detail(event_id: int):
    event = event_or_403(event_id)
    invited_ids = {inv.member_id for inv in event.invitations}
    links = {link.group_id: link for link in links_svc.links_for_event(event.id)}
    emailed_link_ids = mail_svc.sent_link_ids(event)
    return render_template(
        "event_detail.html",
        event=event,
        summary=invites_svc.group_summary(event),
        counts=event.counts(),
        groups=groups_svc.list_groups(),
        uninvited=[m for m in members_svc.list_members() if m.id not in invited_ids],
        statuses=RsvpStatus.ALL,
        links=links,
        emailed_link_ids=emailed_link_ids,
        mail_enabled=mail_svc.is_enabled(),
        default_theme=event.card_theme,
        default_layout=event.card_layout,
        hosts=event.hosts(),
        host_candidates=[
            u for u in users_svc.list_users()
            if u.is_active and not event.is_managed_by_directly(u)
        ],
        can_transfer=(current_user.is_admin or event.owner_id == current_user.id),
        **_appearance_picker(),
    )


@web_bp.post("/events/<int:event_id>/delete")
def delete_event(event_id: int):
    event = event_or_403(event_id)
    name = event.name
    events_svc.delete_event(event)
    flash(f"Deleted {name}.", "success")
    return redirect(url_for("web.events"))


@web_bp.post("/events/<int:event_id>/invite")
def invite(event_id: int):
    event = event_or_403(event_id)
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
    event = event_or_403(event_id)
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
    event_or_403(invitation.event_id)  # the guard the id alone would bypass
    event_id = invitation.event_id
    invites_svc.uninvite(invitation)
    flash("Removed from the guest list.", "success")
    return redirect(url_for("web.event_detail", event_id=event_id))


# --- Shareable invite links -------------------------------------------------

@web_bp.post("/events/<int:event_id>/links/<int:group_id>/<action>")
def manage_link(event_id: int, group_id: int, action: str):
    """Create, revoke, restore or rotate a group's shareable invitation link."""
    event = event_or_403(event_id)
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
    event = event_or_403(event_id)
    links = links_svc.create_links_for_all_groups(event)
    flash(f"{len(links)} invitation link{'' if len(links) == 1 else 's'} ready.", "success")
    return redirect(url_for("web.event_detail", event_id=event.id))


# --- Card appearance --------------------------------------------------------

@web_bp.post("/events/<int:event_id>/appearance")
def set_appearance(event_id: int):
    event = event_or_403(event_id)
    try:
        events_svc.set_appearance(
            event,
            request.form.get("card_theme", DEFAULT_THEME),
            request.form.get("card_layout", DEFAULT_LAYOUT),
        )
        flash(f"Cards now use {event.theme.label} / {event.layout.label}.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("web.event_detail", event_id=event.id))


@web_bp.get("/events/<int:event_id>/preview")
def preview_card(event_id: int):
    """This event's card rendered with sample guests.

    Lets a host see a theme before anything is sent. Creates no rows and touches
    no real invitation; ``?theme=`` and ``?layout=`` override for side-by-side
    comparison.
    """
    event = event_or_403(event_id)
    # "card_theme"/"card_layout" are what the picker form posts; "theme"/"layout"
    # are the short forms for hand-written comparison URLs.
    theme = get_theme(
        request.args.get("theme") or request.args.get("card_theme") or event.card_theme
    )
    layout = get_layout(
        request.args.get("layout") or request.args.get("card_layout") or event.card_layout
    )

    return render_template(
        "invite/card.html",
        preview=True,
        link=SAMPLE_LINK,
        event=event,
        group=SAMPLE_GROUP,
        members=SAMPLE_MEMBERS,
        rsvps={},
        group_status=None,
        mixed=False,
        statuses=RsvpStatus.ALL,
        restricted=True,
        theme_name=theme.name,
        layout_name=layout.name,
        fonts_url=font_query_for(theme.name),
        preview_theme=theme,
        preview_layout=layout,
        preview_saved=(theme.name == event.card_theme and layout.name == event.card_layout),
    )


# --- Co-hosts ---------------------------------------------------------------

@web_bp.post("/events/<int:event_id>/hosts")
def add_co_host(event_id: int):
    """Grant another account the same powers over this event."""
    event = event_or_403(event_id)
    user = users_svc.get_user_or_404(_form_int("user_id") or 0)
    try:
        events_svc.add_co_host(event, user)
        audit("event.cohost.add", event=event.id, target=user.email)
        flash(f"{user.display_name} can now manage this event.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("web.event_detail", event_id=event.id))


@web_bp.post("/events/<int:event_id>/hosts/<int:user_id>/remove")
def remove_co_host(event_id: int, user_id: int):
    event = event_or_403(event_id)
    user = users_svc.get_user_or_404(user_id)
    events_svc.remove_co_host(event, user)
    audit("event.cohost.remove", event=event.id, target=user.email)
    flash(f"{user.display_name} no longer manages this event.", "success")

    # Removing yourself means losing access, so land somewhere you can still see.
    if user.id == current_user.id and not event.is_managed_by(current_user):
        return redirect(url_for("web.events"))
    return redirect(url_for("web.event_detail", event_id=event.id))


@web_bp.post("/events/<int:event_id>/hosts/<int:user_id>/transfer")
def transfer_ownership(event_id: int, user_id: int):
    event = event_or_403(event_id)
    if not (current_user.is_admin or event.owner_id == current_user.id):
        flash("Only the owner can hand over an event.", "error")
        return redirect(url_for("web.event_detail", event_id=event.id))

    user = users_svc.get_user_or_404(user_id)
    try:
        events_svc.transfer_ownership(event, user)
        audit("event.ownership.transfer", event=event.id, target=user.email)
        flash(f"{user.display_name} now owns this event.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("web.event_detail", event_id=event.id))


# --- Email invitations ------------------------------------------------------

@web_bp.post("/events/<int:event_id>/email/<int:group_id>")
def email_group_invitation(event_id: int, group_id: int):
    event = event_or_403(event_id)
    if not mail_svc.is_enabled():
        flash("Email is disabled on this server.", "error")
        return redirect(url_for("web.event_detail", event_id=event.id))
    group = groups_svc.get_group_or_404(group_id)
    link = links_svc.get_link(event.id, group.id)
    if link is None:
        flash("Create an invitation link for this group first.", "error")
        return redirect(url_for("web.event_detail", event_id=event.id))

    result = mail_svc.email_invitation(link)
    if result["no_email"]:
        flash(f"No email on file for {group.name} — add a contact email or member emails.", "error")
    else:
        flash(f"Queued invitation for {group.name} ({result['enqueued']} recipient(s)).", "success")
    return redirect(url_for("web.event_detail", event_id=event.id))


@web_bp.post("/events/<int:event_id>/email")
def email_all_invitations(event_id: int):
    event = event_or_403(event_id)
    if not mail_svc.is_enabled():
        flash("Email is disabled on this server.", "error")
        return redirect(url_for("web.event_detail", event_id=event.id))
    links = links_svc.links_for_event(event.id)
    if not links:
        flash("No invitation links yet — invite some groups first.", "error")
        return redirect(url_for("web.event_detail", event_id=event.id))

    queued = skipped = 0
    for link in links:
        result = mail_svc.email_invitation(link)
        if result["no_email"]:
            skipped += 1
        else:
            queued += result["enqueued"]
    msg = f"Queued {queued} invitation email(s)."
    if skipped:
        msg += f" {skipped} group(s) had no email on file."
    flash(msg, "success" if queued else "error")
    return redirect(url_for("web.event_detail", event_id=event.id))
