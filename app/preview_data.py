"""Stand-in guests for previewing an invitation card.

Plain objects rather than database rows: previewing a theme must never create
an invitation, a group, or a link. They carry just the attributes the card
template reads.
"""

from __future__ import annotations

from types import SimpleNamespace


def sample_member(first: str, last: str, is_child: bool = False, diet: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=0,
        first_name=first,
        last_name=last,
        full_name=f"{first} {last}",
        is_child=is_child,
        dietary_notes=diet or None,
        group_id=0,
    )


SAMPLE_MEMBERS = [
    sample_member("Jane", "Smith"),
    sample_member("Tom", "Smith", diet="Vegetarian"),
    sample_member("Ada", "Smith", is_child=True),
]

SAMPLE_GROUP = SimpleNamespace(id=0, name="The Smith Family", kind="family", members=SAMPLE_MEMBERS)

SAMPLE_LINK = SimpleNamespace(
    token="preview",
    restricted=True,
    is_open=False,
    revoked=False,
    has_response=False,
    has_headcount=False,
    headcount=0,
    adults_attending=None,
    children_attending=None,
    responded_by=None,
    responded_at=None,
    response_note=None,
    group=SAMPLE_GROUP,
)
