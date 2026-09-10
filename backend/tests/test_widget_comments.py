"""Comments on widgets, and the reading each one belongs to.

Monitoring is a conversation. "This district looks wrong" said while the board
is narrowed to Malampa is a statement about Malampa, and showing it beside
Sanma's numbers would misattribute it - so a comment carries the view it was
made under, and a note made of the board itself is shown under every view.
"""

from __future__ import annotations

import pytest

from tests.conftest import sign_in


@pytest.fixture
def board(client, auth_headers) -> dict:
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Comment board"}
    ).json()
    widget = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "A note goes here", "widget_type": "text", "config": {"content": "hi"}},
    ).json()["widgets"][-1]
    views = {}
    for name in ("Malampa", "Sanma"):
        views[name] = client.post(
            f"/api/v1/dashboards/{dashboard['id']}/views",
            headers=auth_headers,
            json={"name": name, "state": {"filters": {"province": name}}},
        ).json()["id"]
    return {"id": dashboard["id"], "widget": widget["id"], "views": views}


@pytest.fixture
def reader(client, auth_headers) -> dict[str, str]:
    email = "commenter@example.com"
    password = "commenter-password-12"
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"email": email, "full_name": "Ada Reader", "role": "viewer", "password": password},
    )
    if created.status_code != 201:
        assert created.status_code == 409, created.text
        page = client.get("/api/v1/users", headers=auth_headers, params={"search": email})
        user = next(u for u in page.json()["items"] if u["email"] == email)
        client.patch(
            f"/api/v1/users/{user['id']}",
            headers=auth_headers,
            json={"role": "viewer", "password": password, "full_name": "Ada Reader"},
        )
    return sign_in(client, email, password)


def say(client, headers, board, text: str, **extra) -> dict:
    response = client.post(
        f"/api/v1/dashboards/{board['id']}/comments",
        headers=headers,
        json={"widget_id": board["widget"], "body": text, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def listed(client, headers, board, view_id: str = "") -> list[str]:
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/comments",
        headers=headers,
        params={"view_id": view_id} if view_id else {},
    )
    assert response.status_code == 200, response.text
    return [c["body"] for c in response.json()]


def test_a_comment_comes_back_with_who_said_it(client, auth_headers, board):
    said = say(client, auth_headers, board, "The Torba figure looks low")
    assert said["author_name"]
    assert listed(client, auth_headers, board) == ["The Torba figure looks low"]


def test_a_comment_belongs_to_the_view_it_was_made_under(client, auth_headers, board):
    say(client, auth_headers, board, "Malampa is behind", view_id=board["views"]["Malampa"])
    assert listed(client, auth_headers, board, board["views"]["Malampa"]) == [
        "Malampa is behind"
    ]
    # Not shown beside another province's numbers, which it is not about.
    assert listed(client, auth_headers, board, board["views"]["Sanma"]) == []


def test_a_note_on_the_board_itself_is_shown_under_every_view(client, auth_headers, board):
    """A general remark is true whatever is selected, so it is never hidden."""
    say(client, auth_headers, board, "This chart excludes allowances")
    for view_id in board["views"].values():
        assert "This chart excludes allowances" in listed(client, auth_headers, board, view_id)


def test_the_board_view_does_not_show_one_view_s_comments(client, auth_headers, board):
    say(client, auth_headers, board, "Only about Malampa", view_id=board["views"]["Malampa"])
    say(client, auth_headers, board, "About the whole board")
    assert listed(client, auth_headers, board) == ["About the whole board"]


def test_a_reply_joins_the_thread_and_its_reading(client, auth_headers, board):
    """An answer belongs to the question's view, not the answerer's selection."""
    asked = say(
        client, auth_headers, board, "Why is this low?", view_id=board["views"]["Malampa"]
    )
    answered = say(
        client,
        auth_headers,
        board,
        "Two teams were on leave",
        parent_id=asked["id"],
        view_id=board["views"]["Sanma"],
    )
    assert answered["parent_id"] == asked["id"]
    assert answered["view_id"] == board["views"]["Malampa"]


def test_a_reply_to_a_reply_stays_at_one_level(client, auth_headers, board):
    asked = say(client, auth_headers, board, "Why is this low?")
    answered = say(client, auth_headers, board, "Leave", parent_id=asked["id"])
    third = say(client, auth_headers, board, "Which teams?", parent_id=answered["id"])
    assert third["parent_id"] == asked["id"]


def test_anybody_who_can_read_the_board_can_comment(client, auth_headers, board, reader):
    said = say(client, reader, board, "Is this the final round?")
    assert said["author_name"] == "Ada Reader"


def test_only_the_author_can_change_what_a_comment_says(client, auth_headers, board, reader):
    said = say(client, reader, board, "Typo here")
    refused = client.patch(
        f"/api/v1/dashboards/{board['id']}/comments/{said['id']}",
        headers=auth_headers,
        json={"body": "Something they never wrote"},
    )
    assert refused.status_code == 403


def test_anyone_reading_can_mark_a_thread_dealt_with(client, auth_headers, board, reader):
    """Resolving is not editing: it says the question was answered."""
    said = say(client, reader, board, "Please check Torba")
    done = client.patch(
        f"/api/v1/dashboards/{board['id']}/comments/{said['id']}",
        headers=auth_headers,
        json={"is_resolved": True},
    )
    assert done.status_code == 200, done.text
    assert done.json()["is_resolved"] is True
    assert done.json()["body"] == "Please check Torba"


def test_a_reader_cannot_delete_somebody_elses_comment(client, auth_headers, board, reader):
    said = say(client, auth_headers, board, "Mine to withdraw")
    refused = client.delete(
        f"/api/v1/dashboards/{board['id']}/comments/{said['id']}", headers=reader
    )
    assert refused.status_code == 403


def test_an_analyst_can_take_down_anything_on_their_board(client, auth_headers, board, reader):
    said = say(client, reader, board, "Posted by mistake")
    removed = client.delete(
        f"/api/v1/dashboards/{board['id']}/comments/{said['id']}", headers=auth_headers
    )
    assert removed.status_code == 200, removed.text
    assert listed(client, auth_headers, board) == []


def test_a_comment_cannot_be_attached_to_another_board_s_widget(client, auth_headers, board):
    other = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Somewhere else"}
    ).json()["id"]
    elsewhere = client.post(
        f"/api/v1/dashboards/{other}/widgets",
        headers=auth_headers,
        json={"title": "Not yours", "widget_type": "text", "config": {}},
    ).json()["widgets"][-1]["id"]
    refused = client.post(
        f"/api/v1/dashboards/{board['id']}/comments",
        headers=auth_headers,
        json={"widget_id": elsewhere, "body": "Wrong board"},
    )
    assert refused.status_code == 404


def test_deleting_a_view_keeps_its_comments_as_board_wide(client, auth_headers, board):
    """A fortnight of discussion should not vanish with a renamed shortcut."""
    say(client, auth_headers, board, "Said under Malampa", view_id=board["views"]["Malampa"])
    client.delete(
        f"/api/v1/dashboards/{board['id']}/views/{board['views']['Malampa']}",
        headers=auth_headers,
    )
    assert listed(client, auth_headers, board) == ["Said under Malampa"]


def test_comments_can_be_asked_for_one_widget_at_a_time(client, auth_headers, board):
    second = client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "Another", "widget_type": "text", "config": {}},
    ).json()["widgets"][-1]["id"]
    say(client, auth_headers, board, "About the first")
    client.post(
        f"/api/v1/dashboards/{board['id']}/comments",
        headers=auth_headers,
        json={"widget_id": second, "body": "About the second"},
    )
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/comments",
        headers=auth_headers,
        params={"widget_id": board["widget"]},
    )
    assert [c["body"] for c in response.json()] == ["About the first"]
