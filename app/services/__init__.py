"""Service layer.

Every database query lives here rather than in views.  Keeping persistence in
one layer is what makes swapping the backend (or adding caching, or moving a
query to a different store) a contained change.
"""

from __future__ import annotations

from app.services import events, groups, invitations, invite_links, members

__all__ = ["events", "groups", "invitations", "invite_links", "members"]
