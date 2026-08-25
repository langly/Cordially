"""Authentication: who can reach what."""

from __future__ import annotations

import pytest

from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invite_links as links_svc
from app.services import members as members_svc
from tests.conftest import sign_in


# --- Nothing host-facing is reachable without a session ---------------------

HOST_PAGES = ["/", "/events", "/groups", "/admin/users"]
HOST_API = ["/api/events", "/api/groups", "/api/members", "/api/users"]


@pytest.mark.parametrize("path", HOST_PAGES)
def test_host_pages_redirect_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.parametrize("path", HOST_API)
def test_api_returns_401_not_a_redirect(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required"


def test_every_route_is_protected_unless_deliberately_public(app):
    """The guard is default-deny, so this catches a new route added without
    thinking about auth."""
    from app import PUBLIC_BLUEPRINTS, PUBLIC_ENDPOINTS

    client = app.test_client()
    unprotected = []
    for rule in app.url_map.iter_rules():
        endpoint = rule.endpoint
        blueprint = endpoint.rsplit(".", 1)[0] if "." in endpoint else None
        if endpoint in PUBLIC_ENDPOINTS or blueprint in PUBLIC_BLUEPRINTS:
            continue
        if "GET" not in (rule.methods or set()):
            continue
        if rule.arguments:
            continue  # needs ids; covered by the ownership tests
        response = client.get(rule.rule)
        if response.status_code not in (302, 401):
            unprotected.append((rule.rule, response.status_code))
    assert unprotected == []


# --- Guests never log in ----------------------------------------------------

def test_guests_rsvp_without_an_account(client, db):
    """The whole point: an invite link works with no session at all."""
    event = events_svc.create_event("Summer BBQ")
    group = groups_svc.create_group("The Smith Family")
    members_svc.create_member("Jane", "Smith", group_id=group.id)
    members_svc.create_member("Tom", "Smith", group_id=group.id)
    link = links_svc.create_link(event, group)

    assert client.get(f"/i/{link.token}").status_code == 200

    client.post(f"/i/{link.token}/respond", data={"rsvp": "yes", "responded_by": "Jane"})
    assert event.counts()["yes"] == 2


# --- Signing in -------------------------------------------------------------

def test_correct_password_signs_in(client, host):
    response = sign_in(client, host)
    assert response.status_code == 302
    assert client.get("/events").status_code == 200


def test_wrong_password_is_refused(client, host):
    response = client.post("/login", data={"email": host.email, "password": "nope"})
    assert response.status_code == 401
    assert client.get("/events").status_code == 302


def test_login_does_not_reveal_whether_an_account_exists(client, host):
    """Same status and same wording whether the address exists or not.

    (The bodies differ only where the form echoes back the submitted email.)
    """
    unknown = client.post("/login", data={"email": "ghost@example.com", "password": "x"})
    wrong = client.post("/login", data={"email": host.email, "password": "wrong"})

    assert unknown.status_code == wrong.status_code == 401
    message = "Those details did not match an active account."
    assert message in unknown.get_data(as_text=True)
    assert message in wrong.get_data(as_text=True)


def test_unknown_email_still_pays_the_password_cost(client, host):
    """Guards the timing side-channel: a miss must not short-circuit."""
    from app.services import users as users_svc

    calls = []
    original = users_svc._burn_password_check
    users_svc._burn_password_check = lambda pw: calls.append(pw) or original(pw)
    try:
        users_svc.authenticate("ghost@example.com", "whatever")
    finally:
        users_svc._burn_password_check = original

    assert calls == ["whatever"]


def test_deactivated_users_cannot_sign_in(client, host, db):
    from app.services import users as users_svc

    users_svc.update_user(host, is_active=False)
    assert client.post("/login", data={"email": host.email, "password": "correct-horse"}).status_code == 401


def test_signing_out_ends_the_session(as_host):
    as_host.post("/logout")
    assert as_host.get("/events").status_code == 302


def test_next_only_follows_relative_paths(client, host):
    """An absolute `next` would make the login form an open redirect."""
    evil = client.post(
        "/login?next=https://evil.example.com/",
        data={"email": host.email, "password": "correct-horse"},
    )
    assert "evil.example.com" not in evil.headers["Location"]

    client.post("/logout")
    ok = client.post(
        "/login?next=/groups", data={"email": host.email, "password": "correct-horse"}
    )
    assert ok.headers["Location"].endswith("/groups")


def test_passwords_are_hashed_not_stored(host):
    assert "correct-horse" not in host.password_hash
    assert host.check_password("correct-horse") and not host.check_password("wrong")


def test_short_passwords_are_rejected(db):
    from app.services import users as users_svc

    with pytest.raises(ValueError, match="at least 8 characters"):
        users_svc.create_user("x@example.com", "short")
