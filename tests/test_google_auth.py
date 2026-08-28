"""Google sign-in (OpenID Connect), match-only."""

from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db as _db
from app.services import users as users_svc


# --- Match/link logic (the security-critical core) --------------------------

def test_matches_an_existing_account_by_verified_email_and_links(db):
    user = users_svc.create_user("jane@example.com", "correct-horse")
    assert user.google_sub is None

    matched = users_svc.login_with_google("google-123", "jane@example.com", True)
    assert matched is user
    assert user.google_sub == "google-123"          # linked on first sign-in


def test_second_login_matches_by_stable_sub(db):
    user = users_svc.create_user("jane@example.com", "correct-horse")
    users_svc.login_with_google("google-123", "jane@example.com", True)

    # Even if the email later differs, the sub still resolves the account.
    again = users_svc.login_with_google("google-123", "changed@example.com", True)
    assert again is user


def test_unknown_email_is_refused_never_created(db):
    assert users_svc.login_with_google("google-x", "stranger@example.com", True) is None
    assert users_svc.list_users() == []             # nothing auto-provisioned


def test_unverified_email_is_never_linked(db):
    """Guards account takeover: an unverified Google email must not match."""
    users_svc.create_user("jane@example.com", "correct-horse")
    assert users_svc.login_with_google("evil-sub", "jane@example.com", False) is None
    assert users_svc.find_by_email("jane@example.com").google_sub is None


def test_deactivated_account_cannot_sign_in_with_google(db):
    user = users_svc.create_user("jane@example.com", "correct-horse")
    users_svc.update_user(user, is_active=False)
    assert users_svc.login_with_google("google-123", "jane@example.com", True) is None


# --- Account model: password + Google coexist -------------------------------

def test_google_only_account_has_no_password(db):
    user = users_svc.create_user("sso@example.com")          # no password
    assert user.has_password is False
    assert user.check_password("anything") is False
    assert users_svc.login_with_google("g-1", "sso@example.com", True) is user


def test_a_linked_account_keeps_both_methods(db):
    user = users_svc.create_user("jane@example.com", "correct-horse")
    users_svc.login_with_google("g-1", "jane@example.com", True)

    assert user.has_password and user.google_linked
    assert user.check_password("correct-horse")              # password still works
    assert users_svc.authenticate("jane@example.com", "correct-horse") is user


# --- Routes -----------------------------------------------------------------

def test_google_is_off_without_config(client, db):
    assert client.get("/auth/google").status_code == 404
    users_svc.create_user("a@example.com", "correct-horse", is_admin=True)
    body = client.get("/login").get_data(as_text=True)
    assert "Sign in with Google" not in body


@pytest.fixture
def google_app():
    """A testing app with Google configured (no real network calls)."""
    app = create_app("testing")
    app.config["GOOGLE_CLIENT_ID"] = "test-id"
    app.config["GOOGLE_CLIENT_SECRET"] = "test-secret"
    from app import _init_google_oauth
    _init_google_oauth(app)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


def _stub_token(google_app, monkeypatch, userinfo):
    g = google_app.extensions["oauth"].google
    monkeypatch.setattr(g, "authorize_access_token", lambda: {"userinfo": userinfo})


def test_login_page_shows_google_button_when_enabled(google_app):
    with google_app.app_context():
        users_svc.create_user("a@example.com", "correct-horse", is_admin=True)
    body = google_app.test_client().get("/login").get_data(as_text=True)
    assert "Sign in with Google" in body
    assert "/auth/google" in body


def test_callback_signs_in_a_matching_user(google_app, monkeypatch):
    with google_app.app_context():
        users_svc.create_user("jane@example.com", "correct-horse")
    _stub_token(google_app, monkeypatch,
                {"sub": "g-1", "email": "jane@example.com", "email_verified": True})

    client = google_app.test_client()
    r = client.get("/auth/google/callback")
    assert r.status_code == 302
    assert client.get("/events").status_code == 200          # a real session now


def test_callback_denies_an_unmatched_google_user(google_app, monkeypatch):
    _stub_token(google_app, monkeypatch,
                {"sub": "g-9", "email": "stranger@example.com", "email_verified": True})

    client = google_app.test_client()
    r = client.get("/auth/google/callback", follow_redirects=True)
    assert b"No Cordially account matches" in r.data
    assert client.get("/events").status_code == 302          # still not signed in


def test_callback_denies_unverified_email(google_app, monkeypatch):
    with google_app.app_context():
        users_svc.create_user("jane@example.com", "correct-horse")
    _stub_token(google_app, monkeypatch,
                {"sub": "evil", "email": "jane@example.com", "email_verified": False})

    client = google_app.test_client()
    r = client.get("/auth/google/callback", follow_redirects=True)
    assert b"No Cordially account matches" in r.data


def test_start_route_redirects_to_google(google_app, monkeypatch):
    from flask import redirect as _redirect

    g = google_app.extensions["oauth"].google
    monkeypatch.setattr(g, "authorize_redirect",
                        lambda uri, **k: _redirect("https://accounts.google.com/o/oauth2/v2/auth"))
    r = google_app.test_client().get("/auth/google")
    assert r.status_code == 302
    assert "accounts.google.com" in r.headers["Location"]
