"""Audit trail and request logging."""

from __future__ import annotations

import logging

import pytest

from app.services import events as events_svc
from tests.conftest import sign_in


# --- Audit trail ------------------------------------------------------------

def test_successful_login_is_audited(client, host, caplog):
    with caplog.at_level(logging.INFO, logger="events.audit"):
        sign_in(client, host)

    line = _audit_line(caplog, "login.success")
    assert f"actor={host.email}" in line
    assert "admin=False" in line


def test_failed_login_is_audited_without_an_actor(client, host, caplog):
    with caplog.at_level(logging.INFO, logger="events.audit"):
        client.post("/login", data={"email": host.email, "password": "wrong"})

    line = _audit_line(caplog, "login.failure")
    assert "actor=-" in line          # no session established
    assert host.email in line         # the attempted address is recorded


def test_login_audit_records_the_client_ip(client, host, caplog):
    with caplog.at_level(logging.INFO, logger="events.audit"):
        client.post(
            "/login",
            data={"email": host.email, "password": "correct-horse"},
            headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"},
        )
    assert "ip=203.0.113.7" in _audit_line(caplog, "login.success")


def test_user_administration_is_audited(client, admin, caplog):
    sign_in(client, admin)
    with caplog.at_level(logging.INFO, logger="events.audit"):
        client.post(
            "/admin/users",
            data={"email": "new@example.com", "name": "New", "password": "a-good-password"},
        )
    line = _audit_line(caplog, "user.create")
    assert "target=new@example.com" in line
    assert f"actor={admin.email}" in line


def test_co_host_changes_are_audited(client, db, admin, other_host, caplog):
    event = events_svc.create_event("Party", owner=admin)
    sign_in(client, admin)

    with caplog.at_level(logging.INFO, logger="events.audit"):
        client.post(f"/events/{event.id}/hosts", data={"user_id": other_host.id})
    line = _audit_line(caplog, "event.cohost.add")
    assert f"event={event.id}" in line
    assert f"target={other_host.email}" in line


def test_audit_works_outside_a_request_context(db, caplog):
    """CLI-triggered actions have no request; audit must not blow up."""
    from app.audit import audit

    with caplog.at_level(logging.INFO, logger="events.audit"):
        audit("user.delete", target="someone@example.com")
    line = _audit_line(caplog, "user.delete")
    assert "actor=-" in line and "ip=-" in line


def test_values_with_spaces_are_quoted_to_one_line(caplog):
    from app.audit import audit

    with caplog.at_level(logging.INFO, logger="events.audit"):
        audit("event.create", name="Summer BBQ")
    line = _audit_line(caplog, "event.create")
    assert 'name="Summer BBQ"' in line
    assert "\n" not in line.strip()


# --- Request logging --------------------------------------------------------

def test_requests_are_logged_with_status_and_user(as_host, host, caplog):
    with caplog.at_level(logging.INFO, logger="events.request"):
        as_host.get("/events")

    line = next(r.message for r in caplog.records if r.name == "events.request")
    assert "GET /events 200" in line
    assert f"user={host.email}" in line


def test_anonymous_requests_log_a_dash_user(client, caplog):
    with caplog.at_level(logging.INFO, logger="events.request"):
        client.get("/events")  # redirects to login
    line = next(r.message for r in caplog.records if r.name == "events.request")
    assert "user=-" in line


# --- Handler wiring ---------------------------------------------------------

def test_testing_config_attaches_no_file_handler(app):
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    assert not any(isinstance(h, RotatingFileHandler) for h in root.handlers)


def _audit_line(caplog, event: str) -> str:
    for record in caplog.records:
        if record.name == "events.audit" and record.message.startswith(event + " "):
            return record.message
    raise AssertionError(f"no audit line for {event!r} in {[r.message for r in caplog.records]}")


def test_unwritable_log_dir_does_not_crash_the_app(tmp_path, caplog):
    """A logging destination problem must degrade to stdout, never abort boot."""
    import logging as _logging
    from logging.handlers import RotatingFileHandler

    from flask import Flask

    from app.logging_config import init_logging

    # A path that cannot be created: a file stands where a directory should be.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")

    app = Flask(__name__)
    app.config["LOG_DIR"] = str(blocker / "logs")

    root = _logging.getLogger()
    saved = root.handlers[:]
    root.handlers = [h for h in saved if not getattr(h, "_events_handler", False)]
    try:
        with caplog.at_level(_logging.WARNING, logger="events.startup"):
            init_logging(app)  # must not raise
        assert not any(isinstance(h, RotatingFileHandler) for h in root.handlers)
        assert any("File logging disabled" in r.message for r in caplog.records)
    finally:
        # Leave the shared root logger as we found it for other tests.
        root.handlers = saved
