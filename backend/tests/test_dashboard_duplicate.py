"""Copying a board, so the copy can be changed without touching the original.

"Keep a copy" already existed and is a different thing: it writes the board as
it stands into a dated snapshot, for showing what the numbers were in March.
This is the other sense of the words - give me another board like this one,
with a link of its own, that I can rearrange.

Two things are worth holding to. The copy must be a copy: its widgets are its
own, so moving one does not move the original's. And it must not inherit the
original's identity: a public link handed to people who were sent the original
must not follow the copy, or the first edit silently changes what they see.
"""

from __future__ import annotations

import pytest

from app.models import Dashboard, Widget


@pytest.fixture
def board(client, auth_headers, request) -> dict:
    made = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={
            "name": f"Fieldwork {request.node.name[:24]}",
            "description": "How collection is going",
            "pages": [{"name": "Coverage"}, {"name": "Quality"}],
            "groups": [{"id": "g1", "name": "Response", "page": 0, "collapsed": False}],
            "theme": "default",
            "refresh_interval_seconds": 300,
        },
    )
    assert made.status_code == 201, made.text
    dashboard = made.json()
    for index, title in enumerate(["Interviews", "Households"]):
        widget = client.post(
            f"/api/v1/dashboards/{dashboard['id']}/widgets",
            headers=auth_headers,
            json={
                "title": title,
                "widget_type": "text",
                "config": {"text": f"{title} today"},
                "layout": {"x": index * 4, "y": 0, "w": 4, "h": 3},
                "page": 0,
                "position": index,
                "group_id": "g1",
            },
        )
        assert widget.status_code == 201, widget.text
    return dashboard


def duplicate(client, auth_headers, dashboard_id: str):
    return client.post(
        f"/api/v1/dashboards/{dashboard_id}/duplicate", headers=auth_headers
    )


def test_the_copy_is_a_new_board_with_its_own_link(board, client, auth_headers):
    made = duplicate(client, auth_headers, board["id"])
    assert made.status_code == 201, made.text
    copy = made.json()

    assert copy["id"] != board["id"]
    assert copy["slug"] != board["slug"]
    assert copy["name"] == f"{board['name']} (copy)"


def test_the_copy_carries_what_the_board_looks_like(board, client, auth_headers):
    copy = duplicate(client, auth_headers, board["id"]).json()

    assert copy["description"] == board["description"]
    assert copy["pages"] == board["pages"]
    assert copy["groups"] == board["groups"]
    assert copy["theme"] == board["theme"]
    assert copy["refresh_interval_seconds"] == board["refresh_interval_seconds"]


def test_every_widget_comes_across_where_it_was(board, client, auth_headers):
    copy = duplicate(client, auth_headers, board["id"]).json()

    was = {(w["title"], w["page"], w["group_id"]) for w in board["widgets"]} or {
        (w["title"], w["page"], w["group_id"])
        for w in client.get(
            f"/api/v1/dashboards/{board['id']}", headers=auth_headers
        ).json()["widgets"]
    }
    now = {(w["title"], w["page"], w["group_id"]) for w in copy["widgets"]}
    assert now == was
    assert len(copy["widgets"]) == 2
    layouts = {w["title"]: w["layout"] for w in copy["widgets"]}
    assert layouts["Interviews"]["w"] == 4


def test_the_copys_widgets_are_its_own(board, client, auth_headers, db_session):
    """The point of copying: moving one board's widget leaves the other alone."""
    copy = duplicate(client, auth_headers, board["id"]).json()
    mine = copy["widgets"][0]

    moved = client.patch(
        f"/api/v1/dashboards/{copy['id']}/widgets/{mine['id']}",
        headers=auth_headers,
        json={"title": "Moved on the copy"},
    )
    assert moved.status_code == 200, moved.text
    db_session.expire_all()

    original = client.get(
        f"/api/v1/dashboards/{board['id']}", headers=auth_headers
    ).json()
    assert "Moved on the copy" not in [w["title"] for w in original["widgets"]]
    assert len({w["id"] for w in original["widgets"]} & {w["id"] for w in copy["widgets"]}) == 0


def test_a_widgets_config_is_copied_rather_than_shared(board, client, auth_headers, db_session):
    """JSON columns share their object unless they are copied, and then a change
    to one board's widget turns up on the other's."""
    copy = duplicate(client, auth_headers, board["id"]).json()
    first = copy["widgets"][0]

    client.patch(
        f"/api/v1/dashboards/{copy['id']}/widgets/{first['id']}",
        headers=auth_headers,
        json={"config": {"text": "changed on the copy"}},
    )
    db_session.expire_all()

    original = client.get(
        f"/api/v1/dashboards/{board['id']}", headers=auth_headers
    ).json()
    assert all(
        w["config"].get("text") != "changed on the copy" for w in original["widgets"]
    )


def test_the_copy_is_not_published_under_the_originals_link(
    board, client, auth_headers, db_session
):
    """The original's public token must not follow the copy: it was handed to
    people, and the first edit to the copy would change what they see."""
    published = client.post(
        f"/api/v1/dashboards/{board['id']}/share",
        headers=auth_headers,
        json={"is_public": True},
    )
    if published.status_code not in (200, 201):
        pytest.skip(f"sharing works differently here: {published.status_code}")
    db_session.expire_all()

    copy = duplicate(client, auth_headers, board["id"]).json()
    db_session.expire_all()

    made = db_session.get(Dashboard, copy["id"])
    assert made.is_public is False
    assert made.public_token is None


def test_copying_a_board_that_is_not_there_is_a_404(client, auth_headers):
    missing = duplicate(client, auth_headers, "no-such-dashboard")
    assert missing.status_code == 404


def test_the_original_keeps_its_widgets(board, client, auth_headers, db_session):
    duplicate(client, auth_headers, board["id"])
    db_session.expire_all()

    still = db_session.query(Widget).filter(Widget.dashboard_id == board["id"]).count()
    assert still == 2
