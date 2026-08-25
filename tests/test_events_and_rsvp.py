"""Events, invitations and RSVP rollups."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import RsvpStatus
from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invitations as invites_svc
from app.services import members as members_svc


@pytest.fixture
def party(db):
    return events_svc.create_event(
        "Summer BBQ",
        location="Back garden",
        starts_at=datetime.now(timezone.utc) + timedelta(days=7),
        capacity=4,
    )


@pytest.fixture
def family(db):
    group = groups_svc.create_group("The Smith Family")
    members_svc.create_member("Jane", "Smith", group_id=group.id)
    members_svc.create_member("Tom", "Smith", group_id=group.id)
    return group


def test_inviting_a_group_invites_every_member(party, family):
    invitations = invites_svc.invite_group(party, family)

    assert len(invitations) == 2
    assert party.counts()["invited"] == 2
    assert all(inv.rsvp == RsvpStatus.PENDING for inv in invitations)


def test_inviting_twice_does_not_duplicate(party, family):
    invites_svc.invite_group(party, family)
    invites_svc.invite_group(party, family)

    assert party.counts()["invited"] == 2


def test_rsvp_for_whole_group(party, family):
    invites_svc.invite_group(party, family)
    invites_svc.set_group_rsvp(party, family, RsvpStatus.YES)

    counts = party.counts()
    assert counts["yes"] == 2
    assert counts["attending"] == 2
    assert all(inv.responded_at is not None for inv in party.invitations)


def test_plus_ones_count_towards_attending(party, family):
    invites_svc.invite_group(party, family)
    jane = family.members[0]
    invitation = invites_svc.get_invitation(party.id, jane.id)

    invites_svc.set_rsvp(invitation, RsvpStatus.YES, plus_ones=2)

    assert party.counts()["attending"] == 3


def test_rejects_unknown_rsvp_status(party, family):
    invites_svc.invite_group(party, family)
    with pytest.raises(ValueError, match="Unknown RSVP status"):
        invites_svc.set_group_rsvp(party, family, "probably")


def test_guest_list_is_grouped_by_family(party, family):
    solo = members_svc.create_member("Solo", "Guest")
    invites_svc.invite_group(party, family)
    invites_svc.invite_member(party, solo)

    summary = invites_svc.group_summary(party)

    assert [b["group_name"] for b in summary] == ["The Smith Family", "Individual guests"]
    assert len(summary[0]["invitations"]) == 2
    assert len(summary[1]["invitations"]) == 1


def test_deleting_an_event_removes_its_invitations(party, family, db):
    from app.models import Invitation

    invites_svc.invite_group(party, family)
    events_svc.delete_event(party)

    assert db.session.query(Invitation).count() == 0
    assert len(members_svc.list_members()) == 2  # people survive


def test_deleting_a_member_removes_their_invitation(party, family, db):
    from app.models import Invitation

    invites_svc.invite_group(party, family)
    members_svc.delete_member(family.members[0])

    assert db.session.query(Invitation).count() == 1


def test_event_cannot_end_before_it_starts(db):
    start = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="cannot end before"):
        events_svc.create_event("Bad", starts_at=start, ends_at=start - timedelta(hours=1))


def test_datetimes_round_trip_as_utc_aware(db):
    """Guards the SQLite-vs-Postgres timezone difference."""
    from datetime import timezone as tz

    naive = datetime(2026, 7, 4, 18, 30)
    event = events_svc.create_event("Naive input", starts_at=naive)
    db.session.expire_all()

    reloaded = events_svc.get_event(event.id)
    assert reloaded.starts_at.tzinfo is not None
    assert reloaded.starts_at == datetime(2026, 7, 4, 18, 30, tzinfo=tz.utc)


def test_aware_non_utc_input_is_normalised(db):
    from datetime import timedelta as td
    from datetime import timezone as tz

    oslo = tz(td(hours=2))
    event = events_svc.create_event("Aware input", starts_at=datetime(2026, 7, 4, 20, 30, tzinfo=oslo))
    db.session.expire_all()

    assert events_svc.get_event(event.id).starts_at == datetime(2026, 7, 4, 18, 30, tzinfo=tz.utc)
