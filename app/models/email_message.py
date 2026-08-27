"""Transactional email outbox.

Every outbound email is a row here first: enqueued in the same transaction as
the action that triggers it, then sent by a separate flush (``flask
send-pending-mail``). That decoupling makes sending durable and retryable, keeps
slow/flaky SMTP out of the request path, and gives an auditable record of what
was sent -- all without a message-queue dependency.

The HTML/text body is rendered and stored at enqueue time, so the sender needs
no request context or URL building later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin
from app.models.types import UtcDateTime


class EmailStatus(str):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"

    ALL = ("pending", "sent", "failed")


class EmailMessage(TimestampMixin, db.Model):
    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(primary_key=True)

    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[Optional[str]] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        SAEnum(*EmailStatus.ALL, name="email_status", native_enum=False,
               length=16, validate_strings=True),
        default=EmailStatus.PENDING, nullable=False, index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(UtcDateTime)

    # What this email is (e.g. "invitation") and, when relevant, which link it
    # relates to -- for showing "emailed" state and avoiding duplicate sends.
    kind: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    invite_link_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("invite_links.id", ondelete="SET NULL"), index=True
    )
    invite_link = relationship("InviteLink")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "to_email": self.to_email,
            "subject": self.subject,
            "status": self.status,
            "attempts": self.attempts,
            "kind": self.kind,
            "last_error": self.last_error,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<EmailMessage {self.id} to={self.to_email!r} {self.status}>"
