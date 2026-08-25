"""Restricted vs open invitations.

Restricted: only the named members of the group are invited.
Open: the group reports how many adults and children are coming, no names.
"""

from __future__ import annotations

import pytest

from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invite_links as links_svc
from app.services import members as members_svc
from tests.conftest import sign_in


@pytest.fixture(autouse=True)
def _signed_in_admin(client, admin):
    """These tests exercise features, not authorization, so they run as a site
    admin -- which can also reach events created without an explicit owner.
    Authorization itself is covered in test_auth.py and test_ownership.py.
    """
    sign_in(client, admin)



@pytest.fixture
def party(db):
    return events_svc.create_event("Summer BBQ")


@pytest.fixture
def family(db):
    group = groups_svc.create_group("The Smith Family")
    members_svc.create_member("Jane", "Smith", group_id=group.id)
    members_svc.create_member("Tom", "Smith", group_id=group.id)
    members_svc.create_member("Ada", "Smith", group_id=group.id, is_child=True, age=8)
    return group


# --- Restricted (the default) -----------------------------------------------

def test_links_are_restricted_by_default(party, family):
    link = links_svc.create_link(party, family)
    assert link.restricted is True
    assert link.is_open is False


def test_restricted_group_is_counted_by_name(client, party, family):
    link = links_svc.create_link(party, family)
    client.post(f"/i/{link.token}/respond", data={"rsvp": "yes"})

    counts = party.counts()
    assert counts["attending"] == 3
    assert counts["adults"] == 2 and counts["children"] == 1  # Ada is a child


def test_restricted_card_shows_names_not_numbers(client, party, family):
    link = links_svc.create_link(party, family)
    body = client.get(f"/i/{link.token}").get_data(as_text=True)

    assert "Jane Smith" in body
    assert "How many of you are coming?" not in body
    assert 'name="adults_attending"' not in body


def test_headcount_refused_on_a_restricted_link(party, family):
    link = links_svc.create_link(party, family)
    with pytest.raises(ValueError, match="limited to the named members"):
        links_svc.set_headcount(link, 4, 2)


# --- Open invitations -------------------------------------------------------

def test_open_card_asks_for_numbers(client, party, family):
    link = links_svc.create_link(party, family, restricted=False)
    body = client.get(f"/i/{link.token}").get_data(as_text=True)

    assert "How many of you are coming?" in body
    assert 'name="adults_attending"' in body
    assert 'name="children_attending"' in body
    assert "Adjust individually" not in body  # meaningless without names


def test_open_group_reports_a_headcount(client, party, family):
    link = links_svc.create_link(party, family, restricted=False)

    client.post(
        f"/i/{link.token}/respond",
        data={"rsvp": "yes", "responded_by": "Jane",
              "adults_attending": "4", "children_attending": "3"},
    )

    assert link.adults_attending == 4 and link.children_attending == 3
    counts = party.counts()
    # The reported numbers replace the 3 named members entirely.
    assert counts["adults"] == 4 and counts["children"] == 3
    assert counts["attending"] == 7


def test_open_group_without_numbers_falls_back_to_named_members(client, party, family):
    link = links_svc.create_link(party, family, restricted=False)
    client.post(f"/i/{link.token}/respond", data={"rsvp": "yes"})

    assert link.has_headcount is False
    assert party.counts()["attending"] == 3  # nobody is lost


def test_zero_is_a_real_answer(client, party, family):
    link = links_svc.create_link(party, family, restricted=False)
    client.post(
        f"/i/{link.token}/respond",
        data={"rsvp": "yes", "adults_attending": "0", "children_attending": "0"},
    )

    assert link.has_headcount is True
    assert party.counts()["attending"] == 0


def test_declining_clears_the_headcount(client, party, family):
    link = links_svc.create_link(party, family, restricted=False)
    client.post(f"/i/{link.token}/respond",
                data={"rsvp": "yes", "adults_attending": "5", "children_attending": "1"})
    client.post(f"/i/{link.token}/respond", data={"rsvp": "no"})

    assert link.has_headcount is False
    assert party.counts()["attending"] == 0


def test_headcount_can_be_revised(client, party, family):
    link = links_svc.create_link(party, family, restricted=False)
    client.post(f"/i/{link.token}/respond",
                data={"rsvp": "yes", "adults_attending": "4", "children_attending": "2"})
    client.post(f"/i/{link.token}/respond",
                data={"rsvp": "yes", "adults_attending": "2", "children_attending": "0"})

    assert party.counts()["attending"] == 2


def test_negative_and_nonsense_numbers_are_rejected(client, party, family):
    link = links_svc.create_link(party, family, restricted=False)

    client.post(f"/i/{link.token}/respond",
                data={"rsvp": "yes", "adults_attending": "-3"}, follow_redirects=True)
    assert link.has_headcount is False

    client.post(f"/i/{link.token}/respond",
                data={"rsvp": "yes", "adults_attending": "loads"}, follow_redirects=True)
    assert link.has_headcount is False


# --- Switching modes --------------------------------------------------------

def test_switching_to_restricted_discards_the_numbers(client, party, family):
    link = links_svc.create_link(party, family, restricted=False)
    client.post(f"/i/{link.token}/respond",
                data={"rsvp": "yes", "adults_attending": "9", "children_attending": "4"})

    links_svc.set_restricted(link, True)

    assert link.has_headcount is False
    assert party.counts()["attending"] == 3  # back to the named members


def test_reinviting_a_group_updates_its_mode(party, family):
    link = links_svc.create_link(party, family, restricted=True)
    again = links_svc.create_link(party, family, restricted=False)

    assert again.id == link.id and again.token == link.token  # same shared URL
    assert again.restricted is False


def test_mixed_event_totals_combine_both_kinds(client, party, family, db):
    crew = groups_svc.create_group("Climbing Crew", kind="group")
    members_svc.create_member("Mo", group_id=crew.id)

    restricted_link = links_svc.create_link(party, family, restricted=True)
    open_link = links_svc.create_link(party, crew, restricted=False)

    client.post(f"/i/{restricted_link.token}/respond", data={"rsvp": "yes"})
    client.post(f"/i/{open_link.token}/respond",
                data={"rsvp": "yes", "adults_attending": "6", "children_attending": "2"})

    counts = party.counts()
    assert counts["adults"] == 2 + 6
    assert counts["children"] == 1 + 2
    assert counts["attending"] == 11


def test_event_page_shows_the_reported_numbers(client, party, family):
    link = links_svc.create_link(party, family, restricted=False)
    client.post(f"/i/{link.token}/respond",
                data={"rsvp": "yes", "adults_attending": "4", "children_attending": "3"})

    body = client.get(f"/events/{party.id}").get_data(as_text=True)
    assert "4 adults" in body and "3 children" in body
    assert "open" in body


def test_api_can_set_and_read_the_mode(client):
    group = client.post("/api/groups", json={"name": "Crew", "kind": "group"}).get_json()
    client.post("/api/members", json={"first_name": "Mo", "group_id": group["id"]})
    event = client.post("/api/events", json={"name": "Party"}).get_json()

    link = client.post(
        f"/api/events/{event['id']}/links",
        json={"group_id": group["id"], "restricted": False},
    ).get_json()[0]
    assert link["restricted"] is False

    client.post(f"{link['path']}/respond",
                data={"rsvp": "yes", "adults_attending": "5", "children_attending": "2"})

    counts = client.get(f"/api/events/{event['id']}").get_json()["counts"]
    assert counts == {
        "pending": 0, "yes": 1, "no": 0, "maybe": 0,
        "invited": 1, "attending": 7, "adults": 5, "children": 2,
    }

    patched = client.patch(
        f"/api/events/{event['id']}/links/{group['id']}", json={"restricted": True}
    ).get_json()
    assert patched["restricted"] is True and patched["headcount"] is None
