"""Email delivery backends. Each exposes ``send(to, subject, text, html)`` and
raises on failure so the outbox can record it and retry."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from typing import List, Optional

logger = logging.getLogger("events.mail")


class BaseBackend:
    def __init__(self, app):
        self.sender = app.config.get("MAIL_DEFAULT_SENDER", "Cordially <no-reply@localhost>")

    def send(self, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        raise NotImplementedError

    def _mime(self, to: str, subject: str, text: str, html: Optional[str]) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = to
        msg.attach(MIMEText(text, "plain", "utf-8"))
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))
        return msg


class ConsoleBackend(BaseBackend):
    """Dev default: logs the email instead of sending. Never fails."""

    def send(self, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        logger.info(
            "[console mail] to=%s from=%s subject=%s\n%s",
            to, self.sender, subject, text,
        )


class MemoryBackend(BaseBackend):
    """Captures sent messages in-process for tests."""

    def __init__(self, app):
        super().__init__(app)
        self.sent: List[dict] = []

    def send(self, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})


class DisabledBackend(BaseBackend):
    """Installed when MAIL_ENABLED is False. Sending is short-circuited before
    this is ever reached; if something slips through, fail loudly rather than
    send."""

    def send(self, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        raise RuntimeError("Email is disabled on this server (MAIL_ENABLED=0)")


class SmtpBackend(BaseBackend):
    """Real delivery over SMTP (STARTTLS on 587, or implicit TLS on 465)."""

    def __init__(self, app):
        super().__init__(app)
        c = app.config
        self.host = c["MAIL_SMTP_HOST"]
        self.port = c["MAIL_SMTP_PORT"]
        self.username = c.get("MAIL_SMTP_USERNAME")
        self.password = c.get("MAIL_SMTP_PASSWORD")
        self.use_tls = c.get("MAIL_SMTP_USE_TLS", True)
        self.use_ssl = c.get("MAIL_SMTP_USE_SSL", False)
        self.timeout = c.get("MAIL_SMTP_TIMEOUT", 30)

    def send(self, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        msg = self._mime(to, subject, text, html)
        from_addr = parseaddr(self.sender)[1]
        to_addr = parseaddr(to)[1]

        if self.use_ssl:
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        try:
            server.ehlo()
            if self.use_tls and not self.use_ssl:
                server.starttls()
                server.ehlo()
            if self.username:
                server.login(self.username, self.password or "")
            server.sendmail(from_addr, [to_addr], msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001 -- closing a broken connection
                pass
