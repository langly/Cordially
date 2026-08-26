"""Mount-point independence: the app must work at /, /e, or any depth.

Deploying under a sub-path is config only (X-Forwarded-Prefix + PROXY_FIX_HOPS),
never a code change. The app's own middleware strips the prefix from the path,
so it works whether or not NGINX also strips it.
"""

from __future__ import annotations

import re

import pytest

from app import create_app
from app.extensions import db as _db
from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invite_links as links_svc
from app.services import members as members_svc
from app.services import users as users_svc

PREFIX = {"X-Forwarded-Prefix": "/e", "X-Forwarded-Proto": "https",
          "X-Forwarded-Host": "party.example.com"}


@pytest.fixture
def prefixed(monkeypatch):
    """A real app with the proxy middleware active, driven with UN-stripped
    paths (`/e/...`) — i.e. NGINX did not strip, the app must."""
    monkeypatch.setenv("PROXY_FIX_HOPS", "1")
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        admin = users_svc.create_user("admin@example.com", "correct-horse", is_admin=True)
        event = events_svc.create_event("Gala", owner=admin)
        group = groups_svc.create_group("The Smith Family")
        members_svc.create_member("Jane", "Smith", group_id=group.id)
        link = links_svc.create_link(event, group)
        yield app, {"event_id": event.id, "token": link.token}
        _db.session.remove()
        _db.drop_all()


def _login(client):
    return client.post("/e/login", headers=PREFIX,
                       data={"email": "admin@example.com", "password": "correct-horse"})


def test_unstripped_prefix_still_routes(prefixed):
    """The exact failure from the field: GET /e/ must reach the app, not 404."""
    app, _ = prefixed
    r = app.test_client().get("/e/", headers=PREFIX)
    assert r.status_code == 302                       # redirect to login, not 404
    assert "/e/login" in r.headers["Location"]


def test_guard_redirect_keeps_the_prefix(prefixed):
    app, _ = prefixed
    r = app.test_client().get("/e/events", headers=PREFIX)
    assert r.headers["Location"].startswith("/e/login")


def test_post_login_redirect_keeps_the_prefix(prefixed):
    app, _ = prefixed
    client = app.test_client()
    client.get("/e/events", headers=PREFIX)
    r = client.post("/e/login?next=/events", headers=PREFIX,
                    data={"email": "admin@example.com", "password": "correct-horse"})
    assert r.headers["Location"].rstrip("/").endswith("/e/events")


def test_generated_links_carry_the_prefix(prefixed):
    app, ctx = prefixed
    client = app.test_client()
    _login(client)
    body = client.get(f"/e/events/{ctx['event_id']}", headers=PREFIX).get_data(as_text=True)
    assert 'href="/e/events"' in body
    assert re.search(r'href="/e/static/', body)
    assert f'/e/i/{ctx["token"]}' in body                       # preview link
    assert f'https://party.example.com/e/i/{ctx["token"]}' in body  # copy box


def test_public_invite_card_works_under_the_prefix(prefixed):
    app, ctx = prefixed
    r = app.test_client().get(f"/e/i/{ctx['token']}", headers=PREFIX)
    assert r.status_code == 200
    assert f'action="/e/i/{ctx["token"]}/respond"' in r.get_data(as_text=True)


def test_already_stripped_path_also_works(prefixed):
    """If NGINX *does* strip (PATH_INFO=/events), the middleware is a no-op on
    the path and still sets the prefix — so both nginx styles work."""
    app, ctx = prefixed
    client = app.test_client()
    client.post("/login", headers=PREFIX,
                data={"email": "admin@example.com", "password": "correct-horse"})
    r = client.get(f"/events/{ctx['event_id']}", headers=PREFIX)
    assert r.status_code == 200
    assert 'href="/e/events"' in r.get_data(as_text=True)


# --- The boundary bug the naive strip would introduce -----------------------

def test_prefix_strip_respects_path_boundaries():
    """Prefix /e must not corrupt /events into /vents."""
    from app import _ForwardedPrefix

    seen = {}

    def app(environ, start_response):
        seen["PATH_INFO"] = environ["PATH_INFO"]
        seen["SCRIPT_NAME"] = environ["SCRIPT_NAME"]
        start_response("200 OK", []); return [b""]

    mw = _ForwardedPrefix(app)
    for raw, expected in [("/e", "/"), ("/e/", "/"), ("/e/events", "/events"),
                          ("/events", "/events"), ("/e/i/abc", "/i/abc")]:
        mw({"PATH_INFO": raw, "SCRIPT_NAME": "", "HTTP_X_FORWARDED_PREFIX": "/e"},
           lambda *a: None)
        assert seen["PATH_INFO"] == expected, f"{raw} -> {seen['PATH_INFO']} != {expected}"
        assert seen["SCRIPT_NAME"] == "/e"


# --- Root deployment is unaffected ------------------------------------------

def test_at_root_no_prefix_leaks_in(client, db):
    admin = users_svc.create_user("a@example.com", "correct-horse", is_admin=True)
    client.post("/login", data={"email": "a@example.com", "password": "correct-horse"})
    event = events_svc.create_event("Gala", owner=admin)
    body = client.get(f"/events/{event.id}").get_data(as_text=True)
    assert 'href="/events"' in body
    assert "/e/" not in body


def test_proxy_fix_is_off_by_default(app):
    from app import _ForwardedPrefix

    assert app.config["PROXY_FIX_HOPS"] == 0
    assert not isinstance(app.wsgi_app, _ForwardedPrefix)


def test_factory_enables_proxy_fix_when_configured(monkeypatch):
    from app import _ForwardedPrefix

    monkeypatch.setenv("PROXY_FIX_HOPS", "1")
    app = create_app("testing")
    assert isinstance(app.wsgi_app, _ForwardedPrefix)
