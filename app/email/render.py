"""Render outbound emails from templates.

Rendered at enqueue time (inside a request, or with INVITE_BASE_URL set) so the
stored body already contains the correct absolute invite URL.
"""

from __future__ import annotations

from typing import Tuple

from flask import render_template

from app.models import InviteLink


def render_invitation(link: InviteLink) -> Tuple[str, str, str]:
    """Return (subject, html, text) for a group's invitation email."""
    event = link.event
    ctx = {
        "event": event,
        "group": link.group,
        "invite_url": link.url(),
        "theme": event.theme,
    }
    subject = f"You're invited: {event.name}"
    html = render_template("email/invitation.html", **ctx)
    text = render_template("email/invitation.txt", **ctx)
    return subject, html, text
