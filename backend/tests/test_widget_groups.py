"""Named groups of widgets on a dashboard page.

A group is a box drawn behind the widgets that belong to it. The box lives on
the dashboard, the membership lives on the widget, and the two have to agree:
a frame drawn on a page whose widgets are somewhere else is a label pointing
at nothing.
"""

from __future__ import annotations

import html
import json
import re

import pytest


def _payload(page: str) -> dict:
    """The board data the exported page carries, out of its script tag."""
    found = re.search(
        r'<script type="application/json" id="board-data">(.*?)</script>', page, re.S
    )
    assert found, "the exported page carries no board data"
    raw = html.unescape(found.group(1)).strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return json.loads(raw.encode().decode("unicode_escape"))


@pytest.fixture
def board(client, auth_headers) -> dict:
    created = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={
            "name": "Grouped",
            "pages": [{"name": "Fieldwork"}, {"name": "Quality"}],
            "groups": [
                {"id": "g1", "name": "Coverage", "page": 0},
                {"id": "g2", "name": "Interviewers", "page": 1},
            ],
        },
    )
    assert created.status_code == 201, created.text
    detail = created.json()
    for title, page in [("Done so far", 0), ("By team", 0), ("Refusals", 1)]:
        added = client.post(
            f"/api/v1/dashboards/{detail['id']}/widgets",
            headers=auth_headers,
            json={"widget_type": "text", "title": title, "page": page, "config": {}},
        )
        assert added.status_code == 201, added.text
    yield client.get(f"/api/v1/dashboards/{detail['id']}", headers=auth_headers).json()
    client.delete(f"/api/v1/dashboards/{detail['id']}", headers=auth_headers)


def _by_title(detail: dict) -> dict[str, dict]:
    return {w["title"]: w for w in detail["widgets"]}


def _widget(detail: dict, title: str) -> str:
    return _by_title(detail)[title]["id"]


def test_a_dashboard_remembers_its_groups(board):
    assert [g["name"] for g in board["groups"]] == ["Coverage", "Interviewers"]
    # Nothing belongs to one until it is put there.
    assert all(w["group_id"] == "" for w in board["widgets"])


def test_a_widget_joins_and_leaves_a_group(client, auth_headers, board):
    widget = _widget(board, "Done so far")
    joined = client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{widget}",
        headers=auth_headers,
        json={"group_id": "g1"},
    )
    assert joined.status_code == 200, joined.text
    assert _by_title(joined.json())["Done so far"]["group_id"] == "g1"

    left = client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{widget}",
        headers=auth_headers,
        json={"group_id": ""},
    )
    assert left.status_code == 200, left.text
    assert _by_title(left.json())["Done so far"]["group_id"] == ""


def test_a_group_that_does_not_exist_is_refused(client, auth_headers, board):
    response = client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{_widget(board, 'By team')}",
        headers=auth_headers,
        json={"group_id": "nope"},
    )
    assert response.status_code == 422, response.text


def test_joining_a_group_on_another_page_takes_the_widget_there(
    client, auth_headers, board
):
    """The frame is drawn on one page, so its members have to be on it.

    Otherwise the group's box on page 2 is drawn around a widget still sitting
    on page 1, and neither page shows what it says it shows.
    """
    response = client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{_widget(board, 'By team')}",
        headers=auth_headers,
        json={"group_id": "g2"},
    )
    assert response.status_code == 200, response.text
    moved = _by_title(response.json())["By team"]
    assert moved["group_id"] == "g2"
    assert moved["page"] == 1


def test_moving_a_widget_to_another_page_takes_it_out_of_its_group(
    client, auth_headers, board
):
    widget = _widget(board, "Done so far")
    client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{widget}",
        headers=auth_headers,
        json={"group_id": "g1"},
    )
    response = client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{widget}",
        headers=auth_headers,
        json={"page": 1},
    )
    assert response.status_code == 200, response.text
    assert _by_title(response.json())["Done so far"]["group_id"] == ""


def test_deleting_a_group_sets_its_widgets_loose(client, auth_headers, board):
    """A widget naming a group that is gone is in no frame and on no menu."""
    client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{_widget(board, 'Done so far')}",
        headers=auth_headers,
        json={"group_id": "g1"},
    )
    response = client.patch(
        f"/api/v1/dashboards/{board['id']}",
        headers=auth_headers,
        json={"groups": [{"id": "g2", "name": "Interviewers", "page": 1}]},
    )
    assert response.status_code == 200, response.text
    assert _by_title(response.json())["Done so far"]["group_id"] == ""


def test_renaming_a_group_keeps_its_members(client, auth_headers, board):
    client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{_widget(board, 'Done so far')}",
        headers=auth_headers,
        json={"group_id": "g1"},
    )
    response = client.patch(
        f"/api/v1/dashboards/{board['id']}",
        headers=auth_headers,
        json={
            "groups": [
                {"id": "g1", "name": "Coverage so far", "page": 0, "collapsed": True},
                {"id": "g2", "name": "Interviewers", "page": 1},
            ]
        },
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["groups"][0]["name"] == "Coverage so far"
    assert detail["groups"][0]["collapsed"] is True
    assert _by_title(detail)["Done so far"]["group_id"] == "g1"


def test_moving_a_page_carries_its_groups(client, auth_headers, board):
    """A group names its page by index, exactly as a widget does."""
    response = client.post(
        f"/api/v1/dashboards/{board['id']}/pages/move",
        headers=auth_headers,
        json={"from_index": 0, "to_index": 1},
    )
    assert response.status_code == 200, response.text
    pages = [p["name"] for p in response.json()["pages"]]
    groups = {g["name"]: int(g.get("page", 0)) for g in response.json()["groups"]}
    assert pages == ["Quality", "Fieldwork"]
    assert pages[groups["Coverage"]] == "Fieldwork"
    assert pages[groups["Interviewers"]] == "Quality"


def test_deleting_a_page_takes_its_groups_with_it(client, auth_headers, board):
    """An empty frame on a page that is gone is reachable from nowhere."""
    for title in ("Refusals",):
        client.delete(
            f"/api/v1/dashboards/{board['id']}/widgets/{_widget(board, title)}",
            headers=auth_headers,
        )
    response = client.delete(
        f"/api/v1/dashboards/{board['id']}/pages/1", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert [g["name"] for g in detail["groups"]] == ["Coverage"]
    assert int(detail["groups"][0].get("page", 0)) == 0


def test_the_exported_file_carries_the_groups(client, auth_headers, board):
    """A group is what says why these widgets are together.

    The exported page flows its widgets rather than pinning them to
    coordinates, so the box becomes a band - but a file that dropped the names
    would read as a looser board than the one it came from.
    """
    client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{_widget(board, 'Done so far')}",
        headers=auth_headers,
        json={"group_id": "g1"},
    )
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/export.html", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    payload = _payload(response.text)

    groups = {g["id"]: g for g in payload["groups"]}
    assert groups["g1"]["name"] == "Coverage"
    assert groups["g1"]["page"] == 0
    # And the membership, or the band would be drawn around nothing.
    inside = [w["title"] for w in payload["widgets"] if w.get("group_id") == "g1"]
    assert inside == ["Done so far"]


def test_creating_a_widget_in_a_group_is_checked_too(client, auth_headers, board):
    """The invariant is the group's, not one endpoint's.

    An API client creating a widget can name a group that does not exist, or
    one on another page, exactly as easily as one moving a widget can.
    """
    refused = client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"widget_type": "text", "title": "Nowhere", "config": {}, "group_id": "nope"},
    )
    assert refused.status_code == 422, refused.text

    # A group on page 1 puts the new widget on page 1, whatever it asked for.
    created = client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={
            "widget_type": "text",
            "title": "Joined at birth",
            "config": {},
            "page": 0,
            "group_id": "g2",
        },
    )
    assert created.status_code == 201, created.text
    made = _by_title(created.json())["Joined at birth"]
    assert made["group_id"] == "g2"
    assert made["page"] == 1
