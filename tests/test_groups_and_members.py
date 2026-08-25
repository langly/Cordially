"""The core of the request: groups with members belonging to them."""

from __future__ import annotations

import pytest

from app.models import GroupKind
from app.services import groups as groups_svc
from app.services import members as members_svc


def test_create_group_with_members(db):
    family = groups_svc.create_group("The Smith Family", kind=GroupKind.FAMILY)
    members_svc.create_member("Jane", "Smith", group_id=family.id)
    members_svc.create_member("Ada", "Smith", group_id=family.id, is_child=True, age=8)

    assert family.size == 2
    assert {m.full_name for m in family.members} == {"Jane Smith", "Ada Smith"}
    assert all(m.group is family for m in family.members)


def test_group_names_are_unique(db):
    groups_svc.create_group("The Smith Family")
    with pytest.raises(ValueError, match="already exists"):
        groups_svc.create_group("the smith family")


def test_member_requires_a_first_name(db):
    group = groups_svc.create_group("Friends", kind=GroupKind.GROUP)
    with pytest.raises(ValueError, match="First name is required"):
        members_svc.create_member("  ", group_id=group.id)


def test_member_can_move_between_groups(db):
    a = groups_svc.create_group("The Smith Family")
    b = groups_svc.create_group("The Patel Family")
    member = members_svc.create_member("Sam", group_id=a.id)

    members_svc.move_to_group(member, b.id)

    assert member.group_id == b.id
    assert a.size == 0 and b.size == 1


def test_member_can_exist_without_a_group(db):
    member = members_svc.create_member("Solo", "Guest")
    assert member.group is None
    assert members_svc.list_members(group_id=None) == [member]


def test_deleting_a_group_deletes_its_members(db):
    group = groups_svc.create_group("The Smith Family")
    members_svc.create_member("Jane", "Smith", group_id=group.id)

    groups_svc.delete_group(group)

    assert groups_svc.list_groups() == []
    assert members_svc.list_members() == []


def test_search_filters_groups_and_members(db):
    smiths = groups_svc.create_group("The Smith Family")
    groups_svc.create_group("Climbing Crew", kind=GroupKind.GROUP)
    members_svc.create_member("Jane", "Smith", group_id=smiths.id)

    assert [g.name for g in groups_svc.list_groups(search="smith")] == ["The Smith Family"]
    assert [m.first_name for m in members_svc.list_members(search="jane")] == ["Jane"]
