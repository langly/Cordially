"""Event operations."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Event, Invitation, Member
from app.themes import (
    DEFAULT_LAYOUT,
    DEFAULT_THEME,
    LAYOUT_NAMES,
    THEME_NAMES,
)


def list_events() -> List[Event]:
    stmt = (
        select(Event)
        .options(
            # counts() walks each invitation's member and the event's links,
            # so eager-load both rather than firing a query per row.
            selectinload(Event.invitations).joinedload(Invitation.member),
            selectinload(Event.invite_links),
        )
        .order_by(Event.starts_at.is_(None), Event.starts_at.desc())
    )
    return list(db.session.scalars(stmt))


def get_event(event_id: int) -> Optional[Event]:
    return db.session.get(Event, event_id)


def get_event_or_404(event_id: int) -> Event:
    return db.get_or_404(Event, event_id)


def create_event(
    name: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
    starts_at: Optional[datetime] = None,
    ends_at: Optional[datetime] = None,
    capacity: Optional[int] = None,
    card_theme: str = DEFAULT_THEME,
    card_layout: str = DEFAULT_LAYOUT,
) -> Event:
    name = (name or "").strip()
    if not name:
        raise ValueError("Event name is required")
    if starts_at and ends_at and ends_at < starts_at:
        raise ValueError("Event cannot end before it starts")
    _check_appearance(card_theme, card_layout)

    event = Event(
        name=name,
        description=description or None,
        location=location or None,
        starts_at=starts_at,
        ends_at=ends_at,
        capacity=capacity,
        card_theme=card_theme,
        card_layout=card_layout,
    )
    db.session.add(event)
    db.session.commit()
    return event


def _check_appearance(card_theme: Optional[str], card_layout: Optional[str]) -> None:
    if card_theme is not None and card_theme not in THEME_NAMES:
        raise ValueError(f"Unknown card theme: {card_theme!r}")
    if card_layout is not None and card_layout not in LAYOUT_NAMES:
        raise ValueError(f"Unknown card layout: {card_layout!r}")


def set_appearance(event: Event, card_theme: str, card_layout: str) -> Event:
    """Change the look of this event's invitation cards."""
    _check_appearance(card_theme, card_layout)
    event.card_theme = card_theme
    event.card_layout = card_layout
    db.session.commit()
    return event


def update_event(event: Event, **fields) -> Event:
    allowed = {
        "name", "description", "location", "starts_at", "ends_at", "capacity",
        "card_theme", "card_layout",
    }
    _check_appearance(fields.get("card_theme"), fields.get("card_layout"))
    for key, value in fields.items():
        if key in allowed:
            setattr(event, key, value)
    if event.starts_at and event.ends_at and event.ends_at < event.starts_at:
        db.session.rollback()
        raise ValueError("Event cannot end before it starts")
    db.session.commit()
    return event


def delete_event(event: Event) -> None:
    db.session.delete(event)
    db.session.commit()


def guest_list(event_id: int) -> List[Invitation]:
    """Invitations for an event, ordered so families stay together."""
    stmt = (
        select(Invitation)
        .join(Invitation.member)
        .options(
            selectinload(Invitation.member).selectinload(Member.group),
        )
        .where(Invitation.event_id == event_id)
        .order_by(Member.group_id.is_(None), Member.group_id, Member.first_name)
    )
    return list(db.session.scalars(stmt))
