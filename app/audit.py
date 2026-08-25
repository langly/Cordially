"""Security audit trail.

One call site per notable action -- sign-ins, account changes, permission
changes. Records *who* did *what* to *whom*, so "who deleted this?" has an
answer after the fact.

Kept separate from the operational request log because these lines have a
different audience (security review) and retention need, even though they share
a file. Emitted through the ``events.audit`` logger.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("events.audit")


def _actor() -> str:
    """The logged-in user, read defensively.

    Audited actions can originate outside a request (CLI, tests), and a failed
    login has no actor at all, so never assume a user is present.
    """
    try:
        from flask_login import current_user

        if current_user and current_user.is_authenticated:
            return current_user.email
    except (RuntimeError, AttributeError):
        pass
    return "-"


def _client_ip() -> str:
    try:
        from flask import request

        # X-Forwarded-For's first hop when behind a proxy, else the peer.
        forwarded = request.headers.get("X-Forwarded-For", "")
        return forwarded.split(",")[0].strip() or request.remote_addr or "-"
    except RuntimeError:
        return "-"


def _format(value: object) -> str:
    text = "-" if value is None else str(value)
    # Keep every record a single greppable line of key=value tokens.
    if any(ch in text for ch in ' \t"'):
        text = '"' + text.replace('"', "'") + '"'
    return text


def audit(action: str, *, actor: str | None = None, **fields: object) -> None:
    """Write one audit line: ``<action> actor=… ip=… <fields>``.

    ``action`` is positional, so callers may pass an ``event=`` field (an event
    id) without colliding with it.
    """
    parts = [action, f"actor={_format(actor or _actor())}", f"ip={_client_ip()}"]
    parts += [f"{key}={_format(val)}" for key, val in fields.items()]
    logger.info(" ".join(parts))
