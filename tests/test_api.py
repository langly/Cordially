"""HTTP-level checks over the JSON API."""

from __future__ import annotations

import pytest
from tests.conftest import sign_in


@pytest.fixture(autouse=True)
def _signed_in_admin(client, admin):
    """These tests exercise features, not authorization, so they run as a site
    admin -- which can also reach events created without an explicit owner.
    Authorization itself is covered in test_auth.py and test_ownership.py.
    """
    sign_in(client, admin)



def test_full_flow_over_the_api(client):
    group = client.post("/api/groups", json={"name": "The Smith Family"}).get_json()
    assert group["kind"] == "family"

    jane = client.post(
        "/api/members", json={"first_name": "Jane", "last_name": "Smith", "group_id": group["id"]}
    ).get_json()
    assert jane["group_name"] == "The Smith Family"

    client.post("/api/members", json={"first_name": "Tom", "group_id": group["id"]})

    event = client.post("/api/events", json={"name": "Summer BBQ"}).get_json()

    invited = client.post(f"/api/events/{event['id']}/invite", json={"group_id": group["id"]})
    assert invited.status_code == 201
    assert len(invited.get_json()) == 2

    client.post(f"/api/events/{event['id']}/rsvp", json={"group_id": group["id"], "rsvp": "yes"})

    counts = client.get(f"/api/events/{event['id']}").get_json()["counts"]
    assert counts == {
        "pending": 0, "yes": 2, "no": 0, "maybe": 0,
        "invited": 2, "attending": 2, "adults": 2, "children": 0,
    }

    guests = client.get(f"/api/events/{event['id']}/guests").get_json()
    assert {g["member_name"] for g in guests} == {"Jane Smith", "Tom"}
    assert all(g["group_name"] == "The Smith Family" for g in guests)


def test_group_detail_includes_members(client):
    group = client.post("/api/groups", json={"name": "Crew", "kind": "group"}).get_json()
    client.post("/api/members", json={"first_name": "Mo", "group_id": group["id"]})

    detail = client.get(f"/api/groups/{group['id']}").get_json()
    assert detail["size"] == 1
    assert detail["members"][0]["first_name"] == "Mo"


def test_validation_errors_return_400(client):
    assert client.post("/api/groups", json={"name": ""}).status_code == 400
    assert client.post("/api/groups", json={"name": "X", "kind": "nope"}).status_code == 400

    event = client.post("/api/events", json={"name": "Party"}).get_json()
    assert client.post(f"/api/events/{event['id']}/invite", json={}).status_code == 400
    bad_rsvp = client.post(f"/api/events/{event['id']}/rsvp", json={"member_id": 1, "rsvp": "eh"})
    assert bad_rsvp.status_code == 400


def test_missing_records_return_404(client):
    assert client.get("/api/groups/999").status_code == 404
    assert client.get("/api/events/999").status_code == 404


def test_web_pages_render(client):
    group = client.post("/api/groups", json={"name": "The Smith Family"}).get_json()
    client.post("/api/members", json={"first_name": "Jane", "group_id": group["id"]})
    event = client.post("/api/events", json={"name": "Summer BBQ"}).get_json()
    client.post(f"/api/events/{event['id']}/invite", json={"group_id": group["id"]})

    for path in ["/", "/groups", f"/groups/{group['id']}", "/events", f"/events/{event['id']}"]:
        response = client.get(path)
        assert response.status_code == 200, path

    assert b"The Smith Family" in client.get(f"/events/{event['id']}").data


def test_invite_link_api_flow(client):
    group = client.post("/api/groups", json={"name": "The Smith Family"}).get_json()
    client.post("/api/members", json={"first_name": "Jane", "group_id": group["id"]})
    client.post("/api/members", json={"first_name": "Tom", "group_id": group["id"]})
    event = client.post("/api/events", json={"name": "Summer BBQ"}).get_json()

    created = client.post(f"/api/events/{event['id']}/links", json={"group_id": group["id"]})
    assert created.status_code == 201
    link = created.get_json()[0]
    assert link["group_name"] == "The Smith Family"
    assert link["url"].endswith(link["path"])

    # The public card is reachable and answering covers the whole group.
    assert client.get(link["path"]).status_code == 200
    client.post(f"{link['path']}/respond", data={"rsvp": "yes", "responded_by": "Jane"})

    counts = client.get(f"/api/events/{event['id']}").get_json()["counts"]
    assert counts["yes"] == 2 and counts["attending"] == 2

    listed = client.get(f"/api/events/{event['id']}/links").get_json()
    assert listed[0]["responded_by"] == "Jane"

    rotated = client.post(
        f"/api/events/{event['id']}/links/{group['id']}/rotate"
    ).get_json()
    assert rotated["token"] != link["token"]
    assert client.get(link["path"]).status_code == 404

    assert client.delete(f"/api/events/{event['id']}/links/{group['id']}").status_code == 204
    assert client.get(rotated["path"]).status_code == 410


def test_link_endpoints_404_for_missing_group_link(client):
    event = client.post("/api/events", json={"name": "Party"}).get_json()
    assert client.delete(f"/api/events/{event['id']}/links/999").status_code == 404
    assert client.post(f"/api/events/{event['id']}/links/999/rotate").status_code == 404
