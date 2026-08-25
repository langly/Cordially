"""Authorization helpers shared by the web and API blueprints."""

from __future__ import annotations

from functools import wraps

from flask import abort, jsonify, request
from flask_login import current_user

from app.services import events as events_svc


def admin_required(view):
    """Site-admin only. Assumes the app-level guard already required a session."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            if request.blueprint == "api":
                return jsonify({"error": "Administrator access required"}), 403
            abort(403)
        return view(*args, **kwargs)

    return wrapper


def event_or_403(event_id: int):
    """Load an event the current user may manage, or refuse.

    404 for a missing event, 403 for one that exists but isn't theirs. The
    distinction leaks only that an id exists, which the host UI already implies.
    """
    event = events_svc.get_event_or_404(event_id)
    if not event.is_managed_by(current_user):
        abort(403)
    return event
