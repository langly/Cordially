"""Card themes and layouts."""

from __future__ import annotations

import pytest

from app.services import events as events_svc
from app.services import groups as groups_svc
from app.services import invite_links as links_svc
from app.services import members as members_svc
from app.themes import (
    DEFAULT_LAYOUT,
    DEFAULT_THEME,
    LAYOUT_NAMES,
    THEME_NAMES,
    THEMES,
    get_layout,
    get_theme,
    themes_by_mood,
)
from tests.conftest import sign_in


@pytest.fixture(autouse=True)
def _signed_in_admin(client, admin):
    """These tests exercise features, not authorization, so they run as a site
    admin -- which can also reach events created without an explicit owner.
    Authorization itself is covered in test_auth.py and test_ownership.py.
    """
    sign_in(client, admin)


@pytest.fixture
def link(db):
    event = events_svc.create_event("Summer BBQ")
    group = groups_svc.create_group("The Smith Family")
    members_svc.create_member("Jane", "Smith", group_id=group.id)
    return links_svc.create_link(event, group)


# --- The catalogue ----------------------------------------------------------

def test_there_are_both_formal_and_cheerful_themes():
    moods = dict(themes_by_mood())
    assert len(moods["Formal"]) >= 3
    assert len(moods["Cheerful"]) >= 3
    assert len(THEMES) == len(moods["Formal"]) + len(moods["Cheerful"])


def test_theme_names_are_unique_and_complete():
    assert len(set(THEME_NAMES)) == len(THEME_NAMES)
    for theme in THEMES:
        assert theme.label and theme.description
        assert theme.paper.startswith("#") and theme.accent.startswith("#")
        assert theme.preview_font


def test_unknown_names_fall_back_rather_than_failing():
    """A card must always render, even with a stale theme name in the row."""
    assert get_theme("no-such-theme").name == DEFAULT_THEME
    assert get_theme(None).name == DEFAULT_THEME
    assert get_layout("nonsense").name == DEFAULT_LAYOUT


# --- Storing the choice -----------------------------------------------------

def test_events_default_to_the_classic_card(db):
    event = events_svc.create_event("Party")
    assert event.card_theme == DEFAULT_THEME
    assert event.card_layout == DEFAULT_LAYOUT
    assert event.theme.label == "Classic Ivory"


def test_theme_and_layout_can_be_chosen_at_creation(db):
    event = events_svc.create_event("Party", card_theme="confetti", card_layout="banner")
    assert event.theme.label == "Confetti"
    assert event.layout.label == "Banner"


def test_unknown_theme_is_rejected_on_write(db):
    with pytest.raises(ValueError, match="Unknown card theme"):
        events_svc.create_event("Party", card_theme="chartreuse")
    with pytest.raises(ValueError, match="Unknown card layout"):
        events_svc.create_event("Party", card_layout="spiral")


def test_appearance_can_be_changed_later(db):
    event = events_svc.create_event("Party")
    events_svc.set_appearance(event, "midnight", "split")

    assert event.card_theme == "midnight" and event.card_layout == "split"
    with pytest.raises(ValueError, match="Unknown card theme"):
        events_svc.set_appearance(event, "bogus", "split")


# --- Rendering --------------------------------------------------------------

@pytest.mark.parametrize("theme_name", THEME_NAMES)
def test_every_theme_renders_a_card(client, link, theme_name):
    events_svc.set_appearance(link.event, theme_name, DEFAULT_LAYOUT)
    response = client.get(f"/i/{link.token}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'data-theme="{theme_name}"' in body
    assert "Summer BBQ" in body


@pytest.mark.parametrize("layout_name", LAYOUT_NAMES)
def test_every_layout_renders_a_card(client, link, layout_name):
    events_svc.set_appearance(link.event, DEFAULT_THEME, layout_name)
    response = client.get(f"/i/{link.token}")

    assert response.status_code == 200
    assert f'data-layout="{layout_name}"' in response.get_data(as_text=True)


def test_card_requests_only_its_own_typeface(client, link):
    events_svc.set_appearance(link.event, "confetti", "classic")
    body = client.get(f"/i/{link.token}").get_data(as_text=True)

    assert "Baloo+2" in body
    assert "Playfair" not in body  # not every theme's font


def test_every_theme_has_a_stylesheet_block():
    """A theme in the catalogue with no CSS would render as the default."""
    css = (
        pytest.importorskip("pathlib").Path("app/static/css/invite.css").read_text()
    )
    for name in THEME_NAMES:
        if name == DEFAULT_THEME:
            continue  # the default lives in :root
        assert f'[data-theme="{name}"]' in css, f"no CSS for theme {name}"


def test_every_layout_has_a_stylesheet_block():
    from pathlib import Path

    css = Path("app/static/css/invite.css").read_text()
    for name in LAYOUT_NAMES:
        if name == DEFAULT_LAYOUT:
            continue
        assert f'[data-layout="{name}"]' in css, f"no CSS for layout {name}"


# --- The picker and preview -------------------------------------------------

def test_picker_grid_shows_every_theme(client, db):
    body = client.get("/events").get_data(as_text=True)

    for theme in THEMES:
        assert f'value="{theme.name}"' in body
        assert theme.label in body
    assert "picker-grid" in body
    assert 'name="card_theme"' in body and 'name="card_layout"' in body


def test_creating_an_event_through_the_form_keeps_the_choice(client, db):
    client.post(
        "/events",
        data={"name": "Birthday", "card_theme": "confetti", "card_layout": "banner"},
        follow_redirects=True,
    )
    event = events_svc.list_events()[0]
    assert event.card_theme == "confetti" and event.card_layout == "banner"


def test_preview_renders_without_touching_data(client, db):
    from app.models import Group, Invitation, InviteLink

    event = events_svc.create_event("Party", card_theme="garden")
    before = (
        db.session.query(Group).count(),
        db.session.query(Invitation).count(),
        db.session.query(InviteLink).count(),
    )

    body = client.get(f"/events/{event.id}/preview").get_data(as_text=True)

    assert 'data-theme="garden"' in body
    assert "The Smith Family" in body  # sample guests
    after = (
        db.session.query(Group).count(),
        db.session.query(Invitation).count(),
        db.session.query(InviteLink).count(),
    )
    assert before == after == (0, 0, 0)


def test_preview_can_override_theme_for_comparison(client, db):
    event = events_svc.create_event("Party", card_theme="garden")
    body = client.get(f"/events/{event.id}/preview?theme=neon&layout=split").get_data(as_text=True)

    assert 'data-theme="neon"' in body and 'data-layout="split"' in body
    assert event.card_theme == "garden"  # unchanged


def test_appearance_form_updates_the_event(client, db):
    event = events_svc.create_event("Party")
    client.post(
        f"/events/{event.id}/appearance",
        data={"card_theme": "sunset", "card_layout": "minimal"},
        follow_redirects=True,
    )
    assert event.card_theme == "sunset" and event.card_layout == "minimal"


def test_api_exposes_and_accepts_appearance(client):
    created = client.post(
        "/api/events", json={"name": "Party", "card_theme": "bloom", "card_layout": "split"}
    )
    assert created.status_code == 201
    assert created.get_json()["card_theme"] == "bloom"

    event_id = created.get_json()["id"]
    patched = client.patch(f"/api/events/{event_id}", json={"card_theme": "nordic"})
    assert patched.get_json()["card_theme"] == "nordic"

    bad = client.patch(f"/api/events/{event_id}", json={"card_theme": "nope"})
    assert bad.status_code == 400


def test_preview_button_carries_the_selected_theme(client, db):
    """The button submits the picker as GET, so Preview shows what you clicked,
    not what was last saved."""
    event = events_svc.create_event("Party", card_theme="classic", card_layout="classic")

    # Field names as the picker form posts them.
    body = client.get(
        f"/events/{event.id}/preview?card_theme=midnight&card_layout=banner"
    ).get_data(as_text=True)

    assert 'data-theme="midnight"' in body
    assert 'data-layout="banner"' in body
    assert "not saved yet" in body
    assert event.card_theme == "classic"  # previewing saves nothing


def test_preview_says_when_it_matches_the_saved_look(client, db):
    event = events_svc.create_event("Party", card_theme="garden", card_layout="minimal")
    body = client.get(f"/events/{event.id}/preview").get_data(as_text=True)

    assert "this is the saved look" in body
    assert "Garden Party" in body and "Minimal" in body


def test_preview_button_targets_the_preview_url(client, db):
    event = events_svc.create_event("Party")
    body = client.get(f"/events/{event.id}").get_data(as_text=True)

    assert f'formaction="/events/{event.id}/preview"' in body
    assert 'formmethod="get"' in body


def test_real_cards_never_show_preview_chrome(client, db):
    event = events_svc.create_event("Party")
    group = groups_svc.create_group("The Smith Family")
    members_svc.create_member("Jane", "Smith", group_id=group.id)
    link = links_svc.create_link(event, group)

    body = client.get(f"/i/{link.token}").get_data(as_text=True)
    assert "preview-bar" not in body
