"""Mount-point independence: the app must work at /, /e, or any depth.

Everything the app emits must carry the mount prefix, so deploying under a
sub-path is nginx config only (X-Forwarded-Prefix + ProxyFix), never a code
change.
"""

from __future__ import annotations

import re

import pytest
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.extensions import db as _db
from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invite_links as links_svc
from app.services import members as members_svc
from app.services import users as users_svc


@pytest.fixture
def prefixed():
    """An app that trusts one proxy hop, exercised as if mounted under /e."""
    app = create_app("testing")
    app.config["PROXY_FIX_HOPS"] = 1
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    with app.app_context():
        _db.create_all()
        admin = users_svc.create_user("admin@example.com", "correct-horse", is_admin=True)
        event = events_svc.create_event("Gala", owner=admin)
        group = groups_svc.create_group("The Smith Family")
        members_svc.create_member("Jane", "Smith", group_id=group.id)
        link = links_svc.create_link(event, group)
        ctx = {"event_id": event.id, "token": link.token}
        yield app, ctx
        _db.session.remove()
        _db.drop_all()


PREFIX = {"X-Forwarded-Prefix": "/e", "X-Forwarded-Proto": "https",
          "X-Forwarded-Host": "party.example.com"}


def _login(client):
    return client.post("/login", headers=PREFIX,
                       data={"email": "admin@example.com", "password": "correct-horse"})


def test_guard_redirect_keeps_the_prefix(prefixed):
    app, _ = prefixed
    r = app.test_client().get("/events", headers=PREFIX)
    assert r.headers["Location"].startswith("/e/login")


def test_post_login_redirect_keeps_the_prefix(prefixed):
    app, _ = prefixed
    client = app.test_client()
    client.get("/events", headers=PREFIX)  # sets next=/events
    r = client.post("/login?next=/events", headers=PREFIX,
                    data={"email": "admin@example.com", "password": "correct-horse"})
    assert r.headers["Location"].rstrip("/").endswith("/e/events")


def test_generated_links_carry_the_prefix(prefixed):
    app, ctx = prefixed
    client = app.test_client()
    _login(client)
    body = client.get(f"/events/{ctx['event_id']}", headers=PREFIX).get_data(as_text=True)

    # nav, static, and the preview invite link all under /e
    assert 'href="/e/events"' in body or 'href="/e/"' in body
    assert re.search(r'href="/e/static/', body)
    assert f'/e/i/{ctx["token"]}' in body     # preview link, was the raw-path bug


def test_external_invite_url_uses_https_and_host(prefixed):
    app, ctx = prefixed
    client = app.test_client()
    _login(client)
    body = client.get(f"/events/{ctx['event_id']}", headers=PREFIX).get_data(as_text=True)
    # The shareable/copy box is an absolute URL; ProxyFix gives it https + host + prefix.
    assert f'https://party.example.com/e/i/{ctx["token"]}' in body


def test_the_public_invite_card_works_under_the_prefix(prefixed):
    app, ctx = prefixed
    client = app.test_client()
    r = client.get(f"/i/{ctx['token']}", headers=PREFIX)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert f'action="/e/i/{ctx["token"]}/respond"' in body  # RSVP posts under /e


# --- Root deployment is unaffected ------------------------------------------

def test_at_root_no_prefix_leaks_in(client, db):
    """With no proxy configured, nothing gains a phantom prefix."""
    admin = users_svc.create_user("a@example.com", "correct-horse", is_admin=True)
    client.post("/login", data={"email": "a@example.com", "password": "correct-horse"})
    event = events_svc.create_event("Gala", owner=admin)

    body = client.get(f"/events/{event.id}").get_data(as_text=True)
    assert 'href="/events"' in body
    assert "/e/" not in body


def test_proxy_fix_is_off_by_default(app):
    from werkzeug.middleware.proxy_fix import ProxyFix as PF

    assert app.config["PROXY_FIX_HOPS"] == 0
    assert not isinstance(app.wsgi_app, PF)


def test_factory_enables_proxy_fix_when_configured(monkeypatch):
    from werkzeug.middleware.proxy_fix import ProxyFix as PF

    monkeypatch.setenv("PROXY_FIX_HOPS", "2")
    app = create_app("testing")
    assert isinstance(app.wsgi_app, PF)
