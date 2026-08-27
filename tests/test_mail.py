"""Email outbox: enqueue, render, flush, retry — and the invitation flow."""

from __future__ import annotations

import pytest

from app.email.backends import BaseBackend
from app.models import EmailMessage, EmailStatus
from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invite_links as links_svc
from app.services import mail as mail_svc
from app.services import members as members_svc
from app.services import users as users_svc


@pytest.fixture(autouse=True)
def _invite_base_url(app):
    # Emails render an absolute invite URL. Web-triggered sends have a request
    # context; here (pure service calls, and future CLI sends) INVITE_BASE_URL
    # supplies the origin. Set per-module so the sub-path test's proxy-derived
    # URLs are unaffected.
    app.config["INVITE_BASE_URL"] = "https://cordially.test"


def backend(app):
    return app.extensions["mail_backend"]


@pytest.fixture
def link(db):
    event = events_svc.create_event("Summer BBQ", location="Back garden")
    group = groups_svc.create_group("The Smith Family", contact_email="smiths@example.com")
    members_svc.create_member("Jane", "Smith", group_id=group.id)
    return links_svc.create_link(event, group)


# --- Outbox mechanics -------------------------------------------------------

def test_enqueue_stores_a_pending_row(db):
    msg = mail_svc.enqueue("a@example.com", "Hi", "body text")
    assert msg.status == EmailStatus.PENDING
    assert mail_svc.pending_count() == 1


def test_flush_sends_via_the_backend_and_marks_sent(app, db):
    mail_svc.enqueue("a@example.com", "Hi", "body", body_html="<p>body</p>")
    result = mail_svc.flush()

    assert result == {"sent": 1, "failed": 0}
    assert mail_svc.pending_count() == 0
    sent = backend(app).sent
    assert len(sent) == 1 and sent[0]["to"] == "a@example.com"
    assert sent[0]["html"] == "<p>body</p>"

    msg = db.session.query(EmailMessage).one()
    assert msg.status == EmailStatus.SENT and msg.sent_at is not None


def test_a_failing_send_retries_then_fails_permanently(app, db, monkeypatch):
    app.config["MAIL_MAX_ATTEMPTS"] = 2

    def boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(backend(app), "send", boom)
    mail_svc.enqueue("a@example.com", "Hi", "body")

    mail_svc.flush()  # attempt 1 -> still pending
    msg = db.session.query(EmailMessage).one()
    assert msg.status == EmailStatus.PENDING and msg.attempts == 1
    assert "smtp down" in msg.last_error

    mail_svc.flush()  # attempt 2 -> failed
    msg = db.session.query(EmailMessage).one()
    assert msg.status == EmailStatus.FAILED and msg.attempts == 2

    mail_svc.flush()  # failed rows are skipped
    assert msg.attempts == 2


def test_retry_failed_requeues(app, db, monkeypatch):
    app.config["MAIL_MAX_ATTEMPTS"] = 1
    monkeypatch.setattr(backend(app), "send",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    mail_svc.enqueue("a@example.com", "Hi", "body")
    mail_svc.flush()
    assert db.session.query(EmailMessage).one().status == EmailStatus.FAILED

    assert mail_svc.retry_failed() == 1
    assert db.session.query(EmailMessage).one().status == EmailStatus.PENDING


def test_flush_commits_each_message(app, db, monkeypatch):
    """A crash mid-batch must not re-send what already went out."""
    mail_svc.enqueue("a@example.com", "1", "body")
    mail_svc.enqueue("b@example.com", "2", "body")

    real_send = backend(app).send
    calls = {"n": 0}

    def send_then_crash(*a, **k):
        real_send(*a, **k)
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(backend(app), "send", send_then_crash)
    with pytest.raises(KeyboardInterrupt):
        mail_svc.flush()

    # First message is committed as sent; second raised before marking.
    statuses = sorted(m.status for m in db.session.query(EmailMessage))
    assert statuses == [EmailStatus.PENDING, EmailStatus.SENT]


# --- Invitation rendering + recipients --------------------------------------

def test_invitation_email_renders_link_and_details(app, db, link):
    result = mail_svc.email_invitation(link)
    assert result == {"group": "The Smith Family", "enqueued": 1, "no_email": False}

    msg = db.session.query(EmailMessage).one()
    assert msg.to_email == "smiths@example.com"        # group contact, not members
    assert msg.kind == "invitation" and msg.invite_link_id == link.id
    assert "Summer BBQ" in msg.body_text
    assert link.token in msg.body_text                 # the invite URL is embedded
    assert "Summer BBQ" in msg.body_html


def test_falls_back_to_member_emails_when_no_group_contact(db):
    event = events_svc.create_event("Party")
    group = groups_svc.create_group("Crew", kind="group")   # no contact_email
    members_svc.create_member("Mo", group_id=group.id, email="mo@example.com")
    members_svc.create_member("Kari", group_id=group.id, email="kari@example.com")
    members_svc.create_member("NoEmail", group_id=group.id)
    link = links_svc.create_link(event, group)

    result = mail_svc.email_invitation(link)
    assert result["enqueued"] == 2                          # only members with emails
    recipients = {m.to_email for m in db.session.query(EmailMessage)}
    assert recipients == {"mo@example.com", "kari@example.com"}


def test_group_with_no_email_is_reported(db):
    event = events_svc.create_event("Party")
    group = groups_svc.create_group("Anon", kind="group")
    members_svc.create_member("NoEmail", group_id=group.id)
    link = links_svc.create_link(event, group)

    result = mail_svc.email_invitation(link)
    assert result["no_email"] is True and result["enqueued"] == 0
    assert mail_svc.pending_count() == 0


def test_sent_link_ids_tracks_emailed_groups(db, link):
    assert mail_svc.sent_link_ids(link.event) == set()
    mail_svc.email_invitation(link)
    assert mail_svc.sent_link_ids(link.event) == {link.id}


# --- Backend selection ------------------------------------------------------

def test_tests_use_the_memory_backend(app):
    from app.email.backends import MemoryBackend

    assert isinstance(backend(app), MemoryBackend)


def test_unknown_backend_is_rejected():
    from app import create_app

    app = create_app("testing")
    app.config["MAIL_BACKEND"] = "carrier-pigeon"
    with pytest.raises(ValueError, match="Unknown MAIL_BACKEND"):
        from app.email import init_mail
        init_mail(app)


# --- The MAIL_ENABLED kill switch -------------------------------------------

@pytest.fixture
def mail_off(app):
    app.config["MAIL_ENABLED"] = False
    from app.email import init_mail
    init_mail(app)          # re-resolve backend -> DisabledBackend
    yield app


def test_disabled_installs_the_tripwire_backend(mail_off):
    from app.email.backends import DisabledBackend

    assert isinstance(mail_off.extensions["mail_backend"], DisabledBackend)


def test_disabled_queues_nothing(mail_off, db):
    assert mail_svc.enqueue("a@example.com", "Hi", "body") is None
    assert mail_svc.pending_count() == 0


def test_disabled_invitation_reports_and_queues_nothing(mail_off, db, link):
    result = mail_svc.email_invitation(link)
    assert result["disabled"] is True and result["enqueued"] == 0
    assert db.session.query(EmailMessage).count() == 0


def test_disabled_flush_sends_nothing(mail_off, db):
    # A row that somehow predates disabling must still not go out.
    mail_off.config["MAIL_ENABLED"] = True
    mail_svc.enqueue("a@example.com", "Hi", "body")
    mail_off.config["MAIL_ENABLED"] = False

    result = mail_svc.flush()
    assert result.get("disabled") is True
    assert mail_svc.pending_count() == 1          # still pending, untouched


def test_tripwire_backend_raises_if_send_is_ever_reached(mail_off):
    with pytest.raises(RuntimeError, match="disabled"):
        mail_off.extensions["mail_backend"].send("a@example.com", "s", "t")


def test_disabled_cli_reports(mail_off):
    runner = mail_off.test_cli_runner()
    out = runner.invoke(args=["send-pending-mail"]).output
    assert "disabled" in out.lower()


def test_disabled_hides_email_buttons(app, db):
    app.config["MAIL_ENABLED"] = False
    admin = users_svc.create_user("admin@example.com", "correct-horse", is_admin=True)
    event = events_svc.create_event("Party", owner=admin)
    group = groups_svc.create_group("Fam", contact_email="f@example.com")
    members_svc.create_member("A", group_id=group.id)
    links_svc.create_link(event, group)

    client = app.test_client()
    client.post("/login", data={"email": "admin@example.com", "password": "correct-horse"})
    body = client.get(f"/events/{event.id}").get_data(as_text=True)
    assert "email_all_invitations" not in body
    assert "Email all invitations" not in body


def test_disabled_web_route_refuses(app, db):
    app.config["MAIL_ENABLED"] = False
    admin = users_svc.create_user("admin@example.com", "correct-horse", is_admin=True)
    event = events_svc.create_event("Party", owner=admin)
    group = groups_svc.create_group("Fam", contact_email="f@example.com")
    members_svc.create_member("A", group_id=group.id)
    links_svc.create_link(event, group)

    client = app.test_client()
    client.post("/login", data={"email": "admin@example.com", "password": "correct-horse"})
    r = client.post(f"/events/{event.id}/email", follow_redirects=True)
    assert b"Email is disabled" in r.data
    assert mail_svc.pending_count() == 0


def test_disabled_api_returns_503(app, db):
    app.config["MAIL_ENABLED"] = False
    admin = users_svc.create_user("admin@example.com", "correct-horse", is_admin=True)
    event = events_svc.create_event("Party", owner=admin)

    client = app.test_client()
    client.post("/login", data={"email": "admin@example.com", "password": "correct-horse"})
    r = client.post(f"/api/events/{event.id}/email", json={})
    assert r.status_code == 503
