"""JSON endpoints, thin wrappers over the service layer."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask import jsonify, request

from app.api import api_bp
from app.models import RsvpStatus
from app.themes import DEFAULT_LAYOUT, DEFAULT_THEME
from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invitations as invites_svc
from app.services import invite_links as links_svc
from app.services import members as members_svc


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid datetime: {value!r} (expected ISO 8601)")


@api_bp.errorhandler(ValueError)
def _handle_value_error(err: ValueError):
    return jsonify({"error": str(err)}), 400


# --- Groups -----------------------------------------------------------------

@api_bp.get("/groups")
def list_groups():
    groups = groups_svc.list_groups(search=request.args.get("q"))
    include = request.args.get("include") == "members"
    return jsonify([g.to_dict(include_members=include) for g in groups])


@api_bp.post("/groups")
def create_group():
    data = request.get_json(silent=True) or {}
    group = groups_svc.create_group(
        name=data.get("name", ""),
        kind=data.get("kind", "family"),
        contact_email=data.get("contact_email"),
        contact_phone=data.get("contact_phone"),
        notes=data.get("notes"),
    )
    return jsonify(group.to_dict(include_members=True)), 201


@api_bp.get("/groups/<int:group_id>")
def get_group(group_id: int):
    group = groups_svc.get_group_or_404(group_id)
    return jsonify(group.to_dict(include_members=True))


@api_bp.patch("/groups/<int:group_id>")
def update_group(group_id: int):
    group = groups_svc.get_group_or_404(group_id)
    group = groups_svc.update_group(group, **(request.get_json(silent=True) or {}))
    return jsonify(group.to_dict(include_members=True))


@api_bp.delete("/groups/<int:group_id>")
def delete_group(group_id: int):
    groups_svc.delete_group(groups_svc.get_group_or_404(group_id))
    return "", 204


# --- Members ----------------------------------------------------------------

@api_bp.get("/members")
def list_members():
    group_id = request.args.get("group_id", type=int)
    members = members_svc.list_members(group_id=group_id, search=request.args.get("q"))
    return jsonify([m.to_dict() for m in members])


@api_bp.post("/members")
def create_member():
    data = request.get_json(silent=True) or {}
    member = members_svc.create_member(
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name"),
        group_id=data.get("group_id"),
        email=data.get("email"),
        phone=data.get("phone"),
        is_child=data.get("is_child", False),
        age=data.get("age"),
        dietary_notes=data.get("dietary_notes"),
        notes=data.get("notes"),
    )
    return jsonify(member.to_dict()), 201


@api_bp.get("/members/<int:member_id>")
def get_member(member_id: int):
    return jsonify(members_svc.get_member_or_404(member_id).to_dict())


@api_bp.patch("/members/<int:member_id>")
def update_member(member_id: int):
    member = members_svc.get_member_or_404(member_id)
    member = members_svc.update_member(member, **(request.get_json(silent=True) or {}))
    return jsonify(member.to_dict())


@api_bp.delete("/members/<int:member_id>")
def delete_member(member_id: int):
    members_svc.delete_member(members_svc.get_member_or_404(member_id))
    return "", 204


# --- Events -----------------------------------------------------------------

@api_bp.get("/events")
def list_events():
    return jsonify([e.to_dict() for e in events_svc.list_events()])


@api_bp.post("/events")
def create_event():
    data = request.get_json(silent=True) or {}
    event = events_svc.create_event(
        name=data.get("name", ""),
        description=data.get("description"),
        location=data.get("location"),
        starts_at=_parse_dt(data.get("starts_at")),
        ends_at=_parse_dt(data.get("ends_at")),
        capacity=data.get("capacity"),
        card_theme=data.get("card_theme", DEFAULT_THEME),
        card_layout=data.get("card_layout", DEFAULT_LAYOUT),
    )
    return jsonify(event.to_dict()), 201


@api_bp.get("/events/<int:event_id>")
def get_event(event_id: int):
    return jsonify(events_svc.get_event_or_404(event_id).to_dict())


@api_bp.patch("/events/<int:event_id>")
def update_event(event_id: int):
    event = events_svc.get_event_or_404(event_id)
    data = dict(request.get_json(silent=True) or {})
    for key in ("starts_at", "ends_at"):
        if key in data:
            data[key] = _parse_dt(data[key])
    return jsonify(events_svc.update_event(event, **data).to_dict())


@api_bp.delete("/events/<int:event_id>")
def delete_event(event_id: int):
    events_svc.delete_event(events_svc.get_event_or_404(event_id))
    return "", 204


# --- Invitations / RSVP -----------------------------------------------------

@api_bp.get("/events/<int:event_id>/guests")
def guest_list(event_id: int):
    events_svc.get_event_or_404(event_id)
    return jsonify([i.to_dict() for i in events_svc.guest_list(event_id)])


@api_bp.post("/events/<int:event_id>/invite")
def invite(event_id: int):
    """Invite a single member (``member_id``) or a whole group (``group_id``)."""
    event = events_svc.get_event_or_404(event_id)
    data = request.get_json(silent=True) or {}

    if data.get("group_id"):
        group = groups_svc.get_group_or_404(int(data["group_id"]))
        invitations = invites_svc.invite_group(event, group)
    elif data.get("member_id"):
        member = members_svc.get_member_or_404(int(data["member_id"]))
        invitations = [invites_svc.invite_member(event, member)]
    else:
        raise ValueError("Provide either member_id or group_id")

    return jsonify([i.to_dict() for i in invitations]), 201


@api_bp.post("/events/<int:event_id>/rsvp")
def rsvp(event_id: int):
    """Set an RSVP for one member, or for an entire group at once."""
    event = events_svc.get_event_or_404(event_id)
    data = request.get_json(silent=True) or {}
    status = data.get("rsvp", "")
    if status not in RsvpStatus.ALL:
        raise ValueError(f"rsvp must be one of {', '.join(RsvpStatus.ALL)}")

    if data.get("group_id"):
        group = groups_svc.get_group_or_404(int(data["group_id"]))
        updated = invites_svc.set_group_rsvp(event, group, status)
    elif data.get("member_id"):
        invitation = invites_svc.get_invitation(event.id, int(data["member_id"]))
        if invitation is None:
            raise ValueError("That member has not been invited to this event")
        updated = [invites_svc.set_rsvp(invitation, status, data.get("plus_ones"))]
    else:
        raise ValueError("Provide either member_id or group_id")

    return jsonify([i.to_dict() for i in updated])


# --- Shareable invite links -------------------------------------------------

@api_bp.get("/events/<int:event_id>/links")
def list_links(event_id: int):
    events_svc.get_event_or_404(event_id)
    links = links_svc.links_for_event(event_id)
    return jsonify([{**link.to_dict(), "url": link.url()} for link in links])


@api_bp.post("/events/<int:event_id>/links")
def create_link(event_id: int):
    """Mint a link for one group, or for every group already on the guest list."""
    event = events_svc.get_event_or_404(event_id)
    data = request.get_json(silent=True) or {}

    restricted = bool(data.get("restricted", True))

    if data.get("group_id"):
        group = groups_svc.get_group_or_404(int(data["group_id"]))
        links = [links_svc.create_link(event, group, restricted=restricted)]
    else:
        links = links_svc.create_links_for_all_groups(event)

    return jsonify([{**link.to_dict(), "url": link.url()} for link in links]), 201


@api_bp.patch("/events/<int:event_id>/links/<int:group_id>")
def update_link(event_id: int, group_id: int):
    """Switch a group between restricted and open, or set its head count."""
    link = links_svc.get_link(event_id, group_id)
    if link is None:
        return jsonify({"error": "No link for that group"}), 404

    data = request.get_json(silent=True) or {}
    if "restricted" in data:
        links_svc.set_restricted(link, bool(data["restricted"]))
    if "adults_attending" in data or "children_attending" in data:
        links_svc.set_headcount(
            link, data.get("adults_attending"), data.get("children_attending")
        )
    return jsonify({**link.to_dict(), "url": link.url()})


@api_bp.delete("/events/<int:event_id>/links/<int:group_id>")
def revoke_link(event_id: int, group_id: int):
    link = links_svc.get_link(event_id, group_id)
    if link is None:
        return jsonify({"error": "No link for that group"}), 404
    links_svc.revoke(link)
    return "", 204


@api_bp.post("/events/<int:event_id>/links/<int:group_id>/rotate")
def rotate_link(event_id: int, group_id: int):
    link = links_svc.get_link(event_id, group_id)
    if link is None:
        return jsonify({"error": "No link for that group"}), 404
    links_svc.rotate(link)
    return jsonify({**link.to_dict(), "url": link.url()})
