from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(db):
    """Factory for host accounts."""
    from app.services import users as users_svc

    def _make(email="host@example.com", password="correct-horse", is_admin=False, name=None):
        return users_svc.create_user(email, password, name=name, is_admin=is_admin)

    return _make


@pytest.fixture
def host(make_user):
    return make_user("host@example.com", name="Host")


@pytest.fixture
def admin(make_user):
    return make_user("admin@example.com", is_admin=True, name="Admin")


@pytest.fixture
def other_host(make_user):
    return make_user("other@example.com", name="Other")


@pytest.fixture
def as_host(client, host):
    """A client already signed in as `host`."""
    client.post("/login", data={"email": host.email, "password": "correct-horse"})
    return client


def sign_in(client, user, password="correct-horse"):
    return client.post(
        "/login", data={"email": user.email, "password": password}, follow_redirects=False
    )
