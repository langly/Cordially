"""Shareable per-group invitation cards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import RsvpStatus
from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invitations as invites_svc
from app.services import invite_links as links_svc
from app.services import members as members_svc


@pytest.fixture
def party(db):
    return events_svc.create_event(
        "Summer BBQ",
        location="Back garden",
        description="Bring something for the grill.",
        starts_at=datetime.now(timezone.utc) + timedelta(days=7),
    )


@pytest.fixture
def family(db):
    group = groups_svc.create_group("The Smith Family")
    members_svc.create_member("Jane", "Smith", group_id=group.id)
    members_svc.create_member("Tom", "Smith", group_id=group.id)
    members_svc.create_member("Ada", "Smith", group_id=group.id, is_child=True, age=8)
    return group


@pytest.fixture
def link(party, family):
    return links_svc.create_link(party, family)


# --- The core rule: one reply covers the whole group ------------------------

def test_one_acceptance_accepts_everyone(client, link, party, family):
    response = client.post(
        f"/i/{link.token}/respond",
        data={"rsvp": "yes", "responded_by": "Jane", "note": "We'll bring dessert"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert party.counts()["yes"] == 3
    assert all(inv.rsvp == RsvpStatus.YES for inv in party.invitations)
    assert link.responded_by == "Jane"
    assert link.response_note == "We'll bring dessert"
    assert link.responded_at is not None


def test_declining_declines_everyone(client, link, party):
    client.post(f"/i/{link.token}/respond", data={"rsvp": "no", "responded_by": "Tom"})
    assert party.counts()["no"] == 3
    assert party.counts()["attending"] == 0


def test_a_later_reply_overrides_the_earlier_one(client, link, party):
    client.post(f"/i/{link.token}/respond", data={"rsvp": "yes", "responded_by": "Jane"})
    client.post(f"/i/{link.token}/respond", data={"rsvp": "no", "responded_by": "Tom"})

    assert party.counts()["no"] == 3
    assert link.responded_by == "Tom"


def test_members_added_after_sharing_are_included_in_the_reply(client, link, party, family):
    client.post(f"/i/{link.token}/respond", data={"rsvp": "yes"})
    members_svc.create_member("Baby", "Smith", group_id=family.id)

    client.post(f"/i/{link.token}/respond", data={"rsvp": "yes"})

    assert party.counts()["invited"] == 4
    assert party.counts()["yes"] == 4


def test_one_person_can_be_adjusted_after_the_group_answer(client, link, party, family):
    client.post(f"/i/{link.token}/respond", data={"rsvp": "yes"})
    ada = [m for m in family.members if m.first_name == "Ada"][0]

    client.post(
        f"/i/{link.token}/member/{ada.id}",
        data={"rsvp": "no", "dietary_notes": "Nut allergy"},
    )

    counts = party.counts()
    assert counts["yes"] == 2 and counts["no"] == 1
    assert ada.dietary_notes == "Nut allergy"


# --- Link lifecycle and access control --------------------------------------

def test_link_is_stable_and_unique_per_group(party, family, link):
    other = groups_svc.create_group("The Patel Family")
    members_svc.create_member("Riya", "Patel", group_id=other.id)
    other_link = links_svc.create_link(party, other)

    assert links_svc.create_link(party, family).token == link.token  # idempotent
    assert other_link.token != link.token
    assert len(link.token) >= 40  # ~256 bits of entropy


def test_creating_a_link_invites_the_group(party, family):
    links_svc.create_link(party, family)
    assert party.counts()["invited"] == 3


def test_card_shows_event_and_group_but_not_other_groups(client, link, party, db):
    outsiders = groups_svc.create_group("The Patel Family")
    members_svc.create_member("Riya", "Patel", group_id=outsiders.id)
    invites_svc.invite_group(party, outsiders)

    body = client.get(f"/i/{link.token}").get_data(as_text=True)

    assert "Summer BBQ" in body
    assert "The Smith Family" in body and "Jane Smith" in body
    assert "Patel" not in body  # never leak another group's guests


def test_unknown_token_is_404(client):
    assert client.get("/i/not-a-real-token").status_code == 404


def test_revoked_link_is_gone_and_cannot_respond(client, link, party):
    links_svc.revoke(link)

    assert client.get(f"/i/{link.token}").status_code == 410
    assert client.post(f"/i/{link.token}/respond", data={"rsvp": "yes"}).status_code == 410
    assert party.counts()["yes"] == 0


def test_rotating_invalidates_the_old_link(client, link):
    old_token = link.token
    links_svc.rotate(link)

    assert client.get(f"/i/{old_token}").status_code == 404
    assert client.get(f"/i/{link.token}").status_code == 200


def test_revoked_link_can_be_restored(client, link):
    links_svc.revoke(link)
    links_svc.restore(link)
    assert client.get(f"/i/{link.token}").status_code == 200


def test_cannot_adjust_someone_from_another_group(client, link, party, db):
    outsiders = groups_svc.create_group("The Patel Family")
    riya = members_svc.create_member("Riya", "Patel", group_id=outsiders.id)
    invites_svc.invite_group(party, outsiders)

    with pytest.raises(ValueError, match="not part of this group"):
        links_svc.set_member_rsvp(link, riya.id, "yes")


def test_invalid_rsvp_is_rejected(client, link, party):
    client.post(f"/i/{link.token}/respond", data={"rsvp": "definitely"}, follow_redirects=True)
    assert party.counts()["pending"] == 3


def test_views_are_tracked(client, link):
    client.get(f"/i/{link.token}")
    client.get(f"/i/{link.token}")

    assert link.view_count == 2
    assert link.opened_at is not None


def test_card_is_not_indexable(client, link):
    body = client.get(f"/i/{link.token}").get_data(as_text=True)
    assert 'name="robots"' in body and "noindex" in body


def test_deleting_the_event_removes_its_links(db, party, link):
    from app.models import InviteLink

    events_svc.delete_event(party)
    assert db.session.query(InviteLink).count() == 0


def test_links_for_all_groups(party, family, db):
    other = groups_svc.create_group("Climbing Crew", kind="group")
    members_svc.create_member("Mo", group_id=other.id)
    invites_svc.invite_group(party, family)
    invites_svc.invite_group(party, other)

    links = links_svc.create_links_for_all_groups(party)

    assert len(links) == 2
    assert len({link.token for link in links}) == 2
