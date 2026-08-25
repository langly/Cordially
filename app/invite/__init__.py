"""Public invitation-card blueprint.

Unauthenticated by design: possession of the token is the credential, so these
views must never expose anything beyond the one group's own invitation.
"""

from __future__ import annotations

from flask import Blueprint

invite_bp = Blueprint("invite", __name__, url_prefix="/i")

from app.invite import routes  # noqa: E402,F401
