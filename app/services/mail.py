"""Email outbox: enqueue, flush, retry.

Views/services enqueue rows; a separate flush (CLI, scheduled) sends them. The
body is rendered at enqueue time and stored, so the flush needs no request
context.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from flask import current_app
from sqlalchemy import func, select

from app.email import get_backend
from app.extensions import db
from app.models import EmailMessage, EmailStatus
from app.models.mixins import utcnow

logger = logging.getLogger("events.mail")


def is_enabled() -> bool:
    """Whether this server may queue/send email at all (MAIL_ENABLED)."""
    return bool(current_app.config.get("MAIL_ENABLED", True))


def enqueue(
    to_email: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    kind: Optional[str] = None,
    invite_link_id: Optional[int] = None,
    commit: bool = True,
) -> Optional[EmailMessage]:
    """Queue one email. Committed by default so it survives the request.

    Returns None and stores nothing when email is disabled server-wide.
    """
    if not is_enabled():
        logger.debug("Email disabled; not queuing message to %s", to_email)
        return None

    message = EmailMessage(
        to_email=to_email.strip(),
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        kind=kind,
        invite_link_id=invite_link_id,
        status=EmailStatus.PENDING,
    )
    db.session.add(message)
    if commit:
        db.session.commit()
    return message


def pending_count() -> int:
    stmt = select(func.count(EmailMessage.id)).where(EmailMessage.status == EmailStatus.PENDING)
    return db.session.scalar(stmt) or 0


def flush(limit: int = 100) -> dict:
    """Send pending messages via the configured backend.

    Each send is committed individually, so a crash mid-batch never re-sends an
    already-delivered message. A failure records the error and increments the
    attempt count; once attempts reach MAIL_MAX_ATTEMPTS the message is marked
    failed and skipped by future flushes.
    """
    if not is_enabled():
        return {"sent": 0, "failed": 0, "disabled": True}

    max_attempts = current_app.config.get("MAIL_MAX_ATTEMPTS", 3)
    backend = get_backend(current_app._get_current_object())

    stmt = (
        select(EmailMessage)
        .where(EmailMessage.status == EmailStatus.PENDING)
        .order_by(EmailMessage.id)
        .limit(limit)
    )
    result = {"sent": 0, "failed": 0}

    for message in db.session.scalars(stmt):
        message.attempts += 1
        try:
            backend.send(message.to_email, message.subject, message.body_text, message.body_html)
        except Exception as err:  # noqa: BLE001 -- any backend error is recorded
            message.last_error = f"{type(err).__name__}: {err}"[:2000]
            if message.attempts >= max_attempts:
                message.status = EmailStatus.FAILED
                result["failed"] += 1
                logger.error("Email %s to %s failed permanently: %s",
                             message.id, message.to_email, message.last_error)
            else:
                logger.warning("Email %s to %s attempt %s failed: %s",
                               message.id, message.to_email, message.attempts, message.last_error)
        else:
            message.status = EmailStatus.SENT
            message.sent_at = utcnow()
            message.last_error = None
            result["sent"] += 1
        db.session.commit()

    return result


def retry_failed() -> int:
    """Requeue permanently-failed messages (e.g. after fixing SMTP config)."""
    stmt = select(EmailMessage).where(EmailMessage.status == EmailStatus.FAILED)
    messages = list(db.session.scalars(stmt))
    for message in messages:
        message.status = EmailStatus.PENDING
        message.attempts = 0
        message.last_error = None
    db.session.commit()
    return len(messages)


def sent_link_ids(event) -> set:
    """Invite-link ids that already have an invitation email (any status)."""
    link_ids = [link.id for link in event.invite_links]
    if not link_ids:
        return set()
    stmt = select(EmailMessage.invite_link_id).where(
        EmailMessage.kind == "invitation",
        EmailMessage.invite_link_id.in_(link_ids),
    )
    return {row for row in db.session.scalars(stmt) if row is not None}


def _invitation_recipients(group) -> List[str]:
    """One email to the group's contact address; else each member with an email.

    Mirrors the "one reply covers the group" model -- a family with a shared
    contact gets a single email, not one per person.
    """
    if group.contact_email:
        return [group.contact_email]
    return [m.email for m in group.members if m.email]


def email_invitation(link) -> dict:
    """Render and enqueue a group's invitation email.

    Idempotent-friendly: callers can check ``sent_link_ids`` first. Returns what
    happened so the UI can report "sent to 1" or "no email on file".
    """
    from app.email.render import render_invitation

    if not is_enabled():
        return {"group": link.group.name, "enqueued": 0, "no_email": False, "disabled": True}

    recipients = _invitation_recipients(link.group)
    if not recipients:
        return {"group": link.group.name, "enqueued": 0, "no_email": True}

    subject, html, text = render_invitation(link)
    for address in recipients:
        enqueue(address, subject, text, html, kind="invitation",
                invite_link_id=link.id, commit=False)
    db.session.commit()
    return {"group": link.group.name, "enqueued": len(recipients), "no_email": False}
