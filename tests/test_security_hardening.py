"""CSRF protection and cookie hardening (audit items #1 and #2)."""

from __future__ import annotations

import re

import pytest

from app import create_app
from app.config import Config, TestConfig
from app.extensions import db as _db
from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invite_links as links_svc
from app.services import members as members_svc
from app.services import users as users_svc


@pytest.fixture
def csrf_app():
    """A real app with CSRF enforcement turned on (TestConfig disables it)."""
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    with app.app_context():
        _db.create_all()
        users_svc.create_user("admin@example.com", "correct-horse", is_admin=True)
        yield app
        _db.session.remove()
        _db.drop_all()


def _token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "no csrf_token field rendered"
    return m.group(1)


# --- #1 CSRF ----------------------------------------------------------------

def test_login_form_renders_a_csrf_token(csrf_app):
    html = csrf_app.test_client().get("/login").get_data(as_text=True)
    assert 'name="csrf_token"' in html


def test_post_without_token_is_rejected(csrf_app):
    r = csrf_app.test_client().post(
        "/login", data={"email": "admin@example.com", "password": "correct-horse"}
    )
    assert r.status_code == 400  # CSRF failure, not a login attempt


def test_post_with_token_succeeds(csrf_app):
    client = csrf_app.test_client()
    token = _token(client)
    r = client.post("/login", data={
        "email": "admin@example.com", "password": "correct-horse", "csrf_token": token,
    })
    assert r.status_code == 302
    assert client.get("/events").status_code == 200


def test_admin_action_needs_a_token(csrf_app):
    client = csrf_app.test_client()
    client.post("/login", data={
        "email": "admin@example.com", "password": "correct-horse", "csrf_token": _token(client),
    })
    # A state-changing admin POST without a token is blocked.
    r = client.post("/admin/users", data={"email": "x@example.com", "password": "another-one"})
    assert r.status_code == 400
    assert users_svc.find_by_email("x@example.com") is None


def test_json_api_is_exempt(csrf_app):
    """Cross-origin JSON POSTs are preflight-blocked; the API serves clients."""
    client = csrf_app.test_client()
    client.post("/login", data={
        "email": "admin@example.com", "password": "correct-horse", "csrf_token": _token(client),
    })
    r = client.post("/api/groups", json={"name": "The Smith Family"})  # no csrf token
    assert r.status_code == 201


def test_public_invite_forms_are_exempt(csrf_app):
    """Guests are unauthenticated and hold the token; CSRF must not block RSVP."""
    with csrf_app.app_context():
        event = events_svc.create_event("Gala")
        group = groups_svc.create_group("The Smith Family")
        members_svc.create_member("Jane", "Smith", group_id=group.id)
        link = links_svc.create_link(event, group)
        token = link.token

    r = csrf_app.test_client().post(
        f"/i/{token}/respond", data={"rsvp": "yes", "responded_by": "Jane"}  # no csrf token
    )
    assert r.status_code == 302


# --- #2 Cookie hardening ----------------------------------------------------

def test_production_cookie_flags():
    assert Config.SESSION_COOKIE_HTTPONLY is True
    assert Config.SESSION_COOKIE_SAMESITE == "Lax"
    assert Config.SESSION_COOKIE_SECURE is True       # default (no env override)
    assert Config.REMEMBER_COOKIE_SECURE is True
    assert Config.REMEMBER_COOKIE_SAMESITE == "Lax"


def test_tests_relax_secure_so_the_http_client_works():
    assert TestConfig.SESSION_COOKIE_SECURE is False


def test_harden_cookies_keeps_secure_when_not_debug(monkeypatch):
    """Outside debug, Secure stays on (production). Tested directly to avoid the
    SECRET_KEY boot guard, which reads the env at import time."""
    from flask import Flask

    from app import _harden_cookies

    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    app = Flask(__name__)
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["REMEMBER_COOKIE_SECURE"] = True
    _harden_cookies(app)
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_SECURE"] is True


def test_debug_relaxes_secure_for_local_http_dev(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a-real-secret-value")
    monkeypatch.setenv("FLASK_DEBUG", "1")
    app = create_app()
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_login_response_sets_httponly_session_cookie(csrf_app):
    client = csrf_app.test_client()
    r = client.post("/login", data={
        "email": "admin@example.com", "password": "correct-horse", "csrf_token": _token(client),
    })
    cookies = "; ".join(h for k, h in r.headers if k == "Set-Cookie")
    assert "session=" in cookies
    assert "HttpOnly" in cookies
    assert "SameSite=Lax" in cookies
