"""What the dashboard list sends so a card can draw the board.

The list page draws a thumbnail of each board rather than a row of names, and
it draws it from the shape the list endpoint sends: where the widgets on the
first page are and what kind each one is. The endpoint has to be cheap about
it - one query for the whole list, and the widget's layout rather than its
config - because this runs for every card on the page every time the page is
opened.
"""

from __future__ import annotations

import pytest

from app.api.v1.endpoints.dashboards import SKETCH_LIMIT


def _dashboard(client, auth_headers, name: str, **extra) -> dict:
    created = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": name, **extra}
    )
    assert created.status_code == 201, created.text
    return created.json()


def _widget(client, auth_headers, dashboard_id: str, **body) -> dict:
    added = client.post(
        f"/api/v1/dashboards/{dashboard_id}/widgets",
        headers=auth_headers,
        json={"widget_type": "text", **body},
    )
    assert added.status_code == 201, added.text
    return added.json()


def _card(client, auth_headers, dashboard_id: str) -> dict:
    listed = client.get("/api/v1/dashboards", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    found = [card for card in listed.json() if card["id"] == dashboard_id]
    assert found, f"{dashboard_id} is not in the list"
    return found[0]


@pytest.fixture
def board(client, auth_headers):
    """A board shaped like a real one: a row of tiles over a map and a chart."""
    created = _dashboard(client, auth_headers, "Sketched")
    places = [
        ("indicator", {"x": 0, "y": 0, "w": 3, "h": 3}),
        ("indicator", {"x": 3, "y": 0, "w": 3, "h": 3}),
        ("map", {"x": 0, "y": 3, "w": 6, "h": 6}),
        ("chart", {"x": 6, "y": 3, "w": 6, "h": 4}),
    ]
    for kind, layout in places:
        _widget(client, auth_headers, created["id"], widget_type=kind, layout=layout)
    yield created
    client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)


def test_the_list_sends_each_widget_s_kind_and_place(client, auth_headers, board):
    card = _card(client, auth_headers, board["id"])
    assert [block["kind"] for block in card["sketch"]] == [
        "indicator",
        "indicator",
        "map",
        "chart",
    ]
    assert card["sketch"][2]["layout"] == {"x": 0, "y": 3, "w": 6, "h": 6}


def test_the_list_says_how_many_widgets_there_are(client, auth_headers, board):
    assert _card(client, auth_headers, board["id"])["widget_count"] == 4


def test_a_board_with_no_widgets_has_an_empty_sketch(client, auth_headers):
    created = _dashboard(client, auth_headers, "Nothing on it")
    card = _card(client, auth_headers, created["id"])
    assert card["sketch"] == []
    assert card["widget_count"] == 0
    client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)


def test_an_unnamed_single_page_board_counts_as_one_page(client, auth_headers, board):
    # `pages` is empty until somebody names a page, which is not no pages.
    assert _card(client, auth_headers, board["id"])["page_count"] == 1


def test_the_sketch_is_the_first_page_but_the_count_is_the_whole_board(
    client, auth_headers
):
    created = _dashboard(
        client,
        auth_headers,
        "Two pages",
        pages=[{"name": "Fieldwork"}, {"name": "Quality"}],
    )
    _widget(client, auth_headers, created["id"], page=0, layout={"x": 0, "y": 0, "w": 6, "h": 4})
    _widget(client, auth_headers, created["id"], page=1, layout={"x": 0, "y": 0, "w": 6, "h": 4})
    _widget(client, auth_headers, created["id"], page=1, layout={"x": 6, "y": 0, "w": 6, "h": 4})

    card = _card(client, auth_headers, created["id"])
    # Opening the board shows its first page, so that is what the picture is of.
    assert len(card["sketch"]) == 1
    # But a card saying "1 widget" for a three-widget board would be a lie.
    assert card["widget_count"] == 3
    assert card["page_count"] == 2
    client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)


def test_a_widget_added_without_a_place_arrives_with_the_one_it_was_given(
    client, auth_headers
):
    """Adding a widget places it, so the sketch has a real position to draw.

    Worth pinning because the thumbnail has a fallback for a widget with no
    position, and it would be easy to assume that fallback is what every
    freshly added widget goes through. It is not: this endpoint puts a new
    widget below what is already on its page.
    """
    created = _dashboard(client, auth_headers, "Added, not dragged")
    for kind in ["chart", "map", "table"]:
        _widget(client, auth_headers, created["id"], widget_type=kind)

    card = _card(client, auth_headers, created["id"])
    assert [block["kind"] for block in card["sketch"]] == ["chart", "map", "table"]
    assert [block["layout"]["y"] for block in card["sketch"]] == [0, 4, 8]
    client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)


def test_a_widget_with_no_stored_place_keeps_its_turn_in_the_order(
    client, auth_headers
):
    """The order is the placement, for a widget with no layout of its own.

    The whole-board PATCH the editor sends writes the layout it is given
    verbatim, so a client that sends widgets without one stores nothing - and
    boards that predate the grid have nothing stored either. The grid lays
    those out by their turn in the list, so the sketch has to arrive in the
    same order or it draws a different board.
    """
    created = _dashboard(client, auth_headers, "Never placed")
    patched = client.patch(
        f"/api/v1/dashboards/{created['id']}",
        headers=auth_headers,
        json={
            "widgets": [
                {"widget_type": kind, "title": kind}
                for kind in ["chart", "map", "table", "kpi"]
            ]
        },
    )
    assert patched.status_code == 200, patched.text

    card = _card(client, auth_headers, created["id"])
    assert [block["kind"] for block in card["sketch"]] == ["chart", "map", "table", "kpi"]
    assert all(block["layout"] == {} for block in card["sketch"])
    client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)


def test_a_very_full_page_is_capped_but_still_counted(client, auth_headers):
    created = _dashboard(client, auth_headers, "Too many")
    for index in range(SKETCH_LIMIT + 3):
        _widget(
            client,
            auth_headers,
            created["id"],
            layout={"x": 0, "y": index, "w": 2, "h": 1},
        )

    card = _card(client, auth_headers, created["id"])
    assert len(card["sketch"]) == SKETCH_LIMIT
    # The count is what tells the card there is more than it drew.
    assert card["widget_count"] == SKETCH_LIMIT + 3
    client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)


def test_the_sketch_carries_no_widget_contents(client, auth_headers):
    """A thumbnail needs a shape, and a shape is not an excuse to send a board.

    Config is where a map's columns, an HTML widget's markup and a text note's
    whole body live. Sending it to draw a rectangle would make the list page
    heavier than the boards on it.
    """
    created = _dashboard(client, auth_headers, "Wordy")
    _widget(
        client,
        auth_headers,
        created["id"],
        config={"content": "x" * 5000},
        layout={"x": 0, "y": 0, "w": 6, "h": 4},
    )

    block = _card(client, auth_headers, created["id"])["sketch"][0]
    assert set(block) == {"kind", "layout"}
    client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)


def test_listing_many_boards_does_not_cost_a_query_each(client, auth_headers, board):
    """One query for every board's widgets, not one per board.

    The obvious way to write this is `dashboard.widgets` in the loop, which
    works, passes every test above, and quietly turns a list of thirty boards
    into thirty-one round trips.
    """
    from sqlalchemy import event

    from app.db.session import engine

    made = [_dashboard(client, auth_headers, f"Board {n}") for n in range(4)]
    for created in made:
        _widget(client, auth_headers, created["id"], layout={"x": 0, "y": 0, "w": 6, "h": 4})

    widget_queries: list[str] = []

    def watch(conn, cursor, statement, parameters, context, executemany):
        if "FROM widgets" in statement:
            widget_queries.append(statement)

    event.listen(engine, "before_cursor_execute", watch)
    try:
        listed = client.get("/api/v1/dashboards", headers=auth_headers)
        assert listed.status_code == 200, listed.text
    finally:
        event.remove(engine, "before_cursor_execute", watch)

    assert len(listed.json()) >= 5
    assert len(widget_queries) == 1, widget_queries

    for created in made:
        client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)
