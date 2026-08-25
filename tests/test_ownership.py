"""Event ownership, co-hosts, and site administration."""

from __future__ import annotations

import pytest

from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import members as members_svc
from app.services import users as users_svc
from tests.conftest import sign_in


@pytest.fixture
def owned(db, host):
    return events_svc.create_event("Host's Party", owner=host)


# --- One host owns N events -------------------------------------------------

def test_a_host_owns_many_events(db, host):
    events_svc.create_event("One", owner=host)
    events_svc.create_event("Two", owner=host)

    assert len(host.owned_events) == 2
    assert {e.name for e in events_svc.list_events(host)} == {"One", "Two"}


def test_hosts_only_see_their_own_events(db, host, other_host):
    events_svc.create_event("Mine", owner=host)
    events_svc.create_event("Theirs", owner=other_host)

    assert [e.name for e in events_svc.list_events(host)] == ["Mine"]
    assert [e.name for e in events_svc.list_events(other_host)] == ["Theirs"]


def test_creating_through_the_web_assigns_the_owner(as_host, host):
    as_host.post("/events", data={"name": "Birthday"}, follow_redirects=True)
    event = events_svc.list_events(host)[0]
    assert event.owner_id == host.id


def test_another_host_gets_403_not_404(client, db, owned, other_host):
    sign_in(client, other_host)

    assert client.get(f"/events/{owned.id}").status_code == 403
    assert client.post(f"/events/{owned.id}/delete").status_code == 403
    assert client.get(f"/events/{owned.id}/preview").status_code == 403
    assert client.get("/events").status_code == 200  # their own list still works


def test_another_host_cannot_reach_it_through_the_api(client, db, owned, other_host):
    sign_in(client, other_host)

    assert client.get(f"/api/events/{owned.id}").status_code == 403
    assert client.patch(f"/api/events/{owned.id}", json={"name": "Hijacked"}).status_code == 403
    assert client.delete(f"/api/events/{owned.id}").status_code == 403
    assert client.get("/api/events").get_json() == []


def test_deleting_a_user_leaves_their_events_unowned(db, host, owned):
    users_svc.delete_user(host)

    from app.models import Event

    event = db.session.get(Event, owned.id)
    assert event is not None and event.owner_id is None


# --- Co-hosts ---------------------------------------------------------------

def test_co_host_can_do_everything_the_owner_can(client, db, owned, other_host):
    events_svc.add_co_host(owned, other_host)
    sign_in(client, other_host)

    assert client.get(f"/events/{owned.id}").status_code == 200
    assert owned.name in [e.name for e in events_svc.list_events(other_host)]

    # Guest-list and appearance actions, not just reading.
    group = groups_svc.create_group("The Smith Family")
    members_svc.create_member("Jane", "Smith", group_id=group.id)
    invited = client.post(
        f"/events/{owned.id}/invite", data={"group_id": group.id, "restricted": "1"}
    )
    assert invited.status_code == 302
    assert owned.counts()["invited"] == 1

    appearance = client.post(
        f"/events/{owned.id}/appearance",
        data={"card_theme": "midnight", "card_layout": "banner"},
    )
    assert appearance.status_code == 302
    assert owned.card_theme == "midnight"


def test_removing_a_co_host_revokes_access(client, db, owned, other_host):
    events_svc.add_co_host(owned, other_host)
    events_svc.remove_co_host(owned, other_host)

    sign_in(client, other_host)
    assert client.get(f"/events/{owned.id}").status_code == 403


def test_co_host_cannot_be_added_twice(db, owned, other_host):
    events_svc.add_co_host(owned, other_host)
    with pytest.raises(ValueError, match="already a co-host"):
        events_svc.add_co_host(owned, other_host)


def test_the_owner_cannot_be_their_own_co_host(db, owned, host):
    with pytest.raises(ValueError, match="already owns"):
        events_svc.add_co_host(owned, host)


def test_deactivated_users_cannot_be_made_co_hosts(db, owned, other_host):
    users_svc.update_user(other_host, is_active=False)
    with pytest.raises(ValueError, match="deactivated"):
        events_svc.add_co_host(owned, other_host)


def test_co_host_added_through_the_web(as_host, owned, other_host):
    as_host.post(f"/events/{owned.id}/hosts", data={"user_id": other_host.id})
    assert [u.id for u in owned.co_hosts] == [other_host.id]


def test_ownership_can_be_transferred(db, owned, host, other_host):
    events_svc.add_co_host(owned, other_host)
    events_svc.transfer_ownership(owned, other_host)

    assert owned.owner_id == other_host.id
    assert other_host not in owned.co_hosts  # promoted, not both


# --- Site admins ------------------------------------------------------------

def test_admins_see_and_manage_every_event(client, db, owned, admin):
    sign_in(client, admin)

    assert client.get(f"/events/{owned.id}").status_code == 200
    assert owned.name in [e.name for e in events_svc.list_events(admin)]


def test_admins_see_unowned_events(db, admin):
    orphan = events_svc.create_event("Legacy", owner=None)
    assert orphan.name in [e.name for e in events_svc.list_events(admin)]


def test_non_admin_hosts_cannot_see_unowned_events(db, host):
    events_svc.create_event("Legacy", owner=None)
    assert events_svc.list_events(host) == []


def test_a_host_can_also_be_an_admin(db, make_user):
    both = make_user("both@example.com", is_admin=True)
    mine = events_svc.create_event("Mine", owner=both)

    assert both.is_admin and mine.owner_id == both.id


def test_only_admins_reach_user_administration(client, db, host, admin):
    sign_in(client, host)
    assert client.get("/admin/users").status_code == 403
    assert client.get("/api/users").status_code == 403

    client.post("/logout")
    sign_in(client, admin)
    assert client.get("/admin/users").status_code == 200
    assert client.get("/api/users").status_code == 200


def test_admins_add_modify_and_delete_users(client, db, admin):
    sign_in(client, admin)

    client.post(
        "/admin/users",
        data={"email": "New@Example.com", "name": "New Host", "password": "another-good-one"},
    )
    created = users_svc.find_by_email("new@example.com")
    assert created is not None and created.email == "new@example.com"  # lowercased
    assert not created.is_admin

    client.post(
        f"/admin/users/{created.id}",
        data={"flags": "1", "is_admin": "1", "is_active": "1", "name": "Promoted"},
    )
    assert created.is_admin and created.name == "Promoted"

    client.post(f"/admin/users/{created.id}/delete")
    assert users_svc.find_by_email("new@example.com") is None


def test_duplicate_emails_are_refused(db, host):
    with pytest.raises(ValueError, match="already exists"):
        users_svc.create_user(host.email.upper(), "another-password")


def test_the_last_admin_cannot_be_removed(db, admin):
    with pytest.raises(ValueError, match="last administrator"):
        users_svc.update_user(admin, is_admin=False)
    with pytest.raises(ValueError, match="last administrator"):
        users_svc.update_user(admin, is_active=False)
    with pytest.raises(ValueError, match="last administrator"):
        users_svc.delete_user(admin)


def test_demotion_is_allowed_once_another_admin_exists(db, admin, make_user):
    make_user("second@example.com", is_admin=True)
    users_svc.update_user(admin, is_admin=False)
    assert not admin.is_admin


def test_admins_cannot_delete_themselves_through_the_ui(client, db, admin, make_user):
    make_user("second@example.com", is_admin=True)
    sign_in(client, admin)

    client.post(f"/admin/users/{admin.id}/delete", follow_redirects=True)
    assert users_svc.get_user(admin.id) is not None


def test_a_password_only_update_does_not_change_roles(db, admin, make_user):
    user = make_user("plain@example.com")
    users_svc.update_user(user, password="a-brand-new-password")

    assert user.check_password("a-brand-new-password")
    assert not user.is_admin and user.is_active


# --- The address book stays shared ------------------------------------------

def test_groups_are_visible_to_every_signed_in_host(client, db, host, other_host):
    groups_svc.create_group("The Smith Family")

    for user in (host, other_host):
        client.post("/logout")
        sign_in(client, user)
        body = client.get("/groups").get_data(as_text=True)
        assert "The Smith Family" in body
