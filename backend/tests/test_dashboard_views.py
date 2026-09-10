"""Saved views: a named filter selection somebody comes back to.

A board is read the same few ways over and over, and setting the filters by
hand every morning is where the reading stops happening. A view stores the
selection, not the board, so it goes on working when a widget is added.
"""

from __future__ import annotations

import pytest

from tests.conftest import sign_in


@pytest.fixture
def board(client, auth_headers) -> str:
    return client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Views board"}
    ).json()["id"]


@pytest.fixture
def viewer(client, auth_headers) -> dict[str, str]:
    """A reader who may open the board but not publish anything on it."""
    email = "view-reader@example.com"
    password = "view-reader-password-1"
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"email": email, "full_name": "Reader", "role": "viewer", "password": password},
    )
    if created.status_code != 201:
        assert created.status_code == 409, created.text
        page = client.get("/api/v1/users", headers=auth_headers, params={"search": email})
        user = next(u for u in page.json()["items"] if u["email"] == email)
        client.patch(
            f"/api/v1/users/{user['id']}",
            headers=auth_headers,
            json={"role": "viewer", "password": password},
        )
    return sign_in(client, email, password)


SELECTION = {
    "page": 1,
    "filters": {"province": "Malampa"},
    "drill": [{"variable": "province", "value": "Malampa", "label": "Malampa"}],
}


def test_a_view_stores_the_selection_and_gives_it_back(client, auth_headers, board):
    created = client.post(
        f"/api/v1/dashboards/{board}/views",
        headers=auth_headers,
        json={"name": "Malampa this week", "state": SELECTION},
    )
    assert created.status_code == 201, created.text
    assert created.json()["state"] == SELECTION

    listed = client.get(f"/api/v1/dashboards/{board}/views", headers=auth_headers).json()
    assert [v["name"] for v in listed] == ["Malampa this week"]
    assert listed[0]["state"]["drill"][0]["value"] == "Malampa"


def test_only_one_view_at_a_time_is_the_default(client, auth_headers, board):
    """The board opens on one view, so claiming it takes it from the other."""
    first = client.post(
        f"/api/v1/dashboards/{board}/views",
        headers=auth_headers,
        json={"name": "First", "state": {}, "is_default": True},
    ).json()
    second = client.post(
        f"/api/v1/dashboards/{board}/views",
        headers=auth_headers,
        json={"name": "Second", "state": {}, "is_default": True},
    ).json()

    listed = {
        v["id"]: v["is_default"]
        for v in client.get(
            f"/api/v1/dashboards/{board}/views", headers=auth_headers
        ).json()
    }
    assert listed[first["id"]] is False
    assert listed[second["id"]] is True


def test_a_reader_keeps_their_own_view_but_cannot_publish_it(
    client, auth_headers, board, viewer
):
    """A shortcut is anybody's to make; what everyone else sees is not."""
    created = client.post(
        f"/api/v1/dashboards/{board}/views",
        headers=viewer,
        json={"name": "My corner", "state": SELECTION, "is_shared": True, "is_default": True},
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_shared"] is False
    assert created.json()["is_default"] is False

    # Theirs to see...
    mine = client.get(f"/api/v1/dashboards/{board}/views", headers=viewer).json()
    assert "My corner" in [v["name"] for v in mine]
    # ...and nobody else's business.
    others = client.get(f"/api/v1/dashboards/{board}/views", headers=auth_headers).json()
    assert "My corner" not in [v["name"] for v in others]


def test_a_reader_cannot_delete_somebody_elses_view(client, auth_headers, board, viewer):
    published = client.post(
        f"/api/v1/dashboards/{board}/views",
        headers=auth_headers,
        json={"name": "Everyone's", "state": {}},
    ).json()
    refused = client.delete(
        f"/api/v1/dashboards/{board}/views/{published['id']}", headers=viewer
    )
    assert refused.status_code == 404


def test_a_shared_link_offers_the_published_views_only(client, auth_headers, board, viewer):
    client.post(
        f"/api/v1/dashboards/{board}/views",
        headers=auth_headers,
        json={"name": "Published", "state": SELECTION},
    )
    client.post(
        f"/api/v1/dashboards/{board}/views",
        headers=viewer,
        json={"name": "Private", "state": {}},
    )
    shared = client.post(
        f"/api/v1/dashboards/{board}/share?enable=true", headers=auth_headers
    ).json()
    token = shared["public_token"]

    listed = client.get(f"/api/v1/public/dashboards/{token}/views")
    assert listed.status_code == 200, listed.text
    assert [v["name"] for v in listed.json()] == ["Published"]


def test_renaming_a_view_keeps_its_selection(client, auth_headers, board):
    view = client.post(
        f"/api/v1/dashboards/{board}/views",
        headers=auth_headers,
        json={"name": "Old name", "state": SELECTION},
    ).json()
    renamed = client.patch(
        f"/api/v1/dashboards/{board}/views/{view['id']}",
        headers=auth_headers,
        json={"name": "New name"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "New name"
    assert renamed.json()["state"] == SELECTION
