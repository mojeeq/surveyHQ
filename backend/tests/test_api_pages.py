"""Moving and deleting dashboard pages.

A widget records which page it is on as an index into the page list, so both
halves have to move together. Deleting a page used to renumber neither, which
left every widget after the hole on the page that took its old number.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def dashboard(client, auth_headers) -> dict:
    created = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={
            "name": "Three pages",
            "pages": [{"name": "Fieldwork"}, {"name": "Quality"}, {"name": "Coverage"}],
        },
    )
    assert created.status_code == 201, created.text
    detail = created.json()
    # One text widget per page, named for the page it starts on.
    for index, page in enumerate(["Fieldwork", "Quality", "Coverage"]):
        added = client.post(
            f"/api/v1/dashboards/{detail['id']}/widgets",
            headers=auth_headers,
            json={
                "widget_type": "text",
                "title": page,
                "page": index,
                "config": {"text": page},
            },
        )
        assert added.status_code == 201, added.text
    yield client.get(f"/api/v1/dashboards/{detail['id']}", headers=auth_headers).json()
    client.delete(f"/api/v1/dashboards/{detail['id']}", headers=auth_headers)


def _placement(detail: dict) -> dict[str, str]:
    """Which page name each widget sits on, by the widget's own title."""
    pages = [page.get("name") for page in detail["pages"]]
    return {w["title"]: pages[w.get("page") or 0] for w in detail["widgets"]}


def test_a_page_takes_its_widgets_with_it(client, auth_headers, dashboard):
    before = _placement(dashboard)
    assert before == {"Fieldwork": "Fieldwork", "Quality": "Quality", "Coverage": "Coverage"}

    moved = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/pages/move",
        headers=auth_headers,
        json={"from": 0, "to": 2},
    )
    assert moved.status_code == 200, moved.text
    detail = moved.json()
    assert [p["name"] for p in detail["pages"]] == ["Quality", "Coverage", "Fieldwork"]
    # Every widget is still on the page it started on, wherever that page went.
    assert _placement(detail) == before


@pytest.mark.parametrize("source,target", [(0, 1), (2, 0), (1, 2), (0, 2), (2, 1)])
def test_every_move_keeps_every_widget_on_its_own_page(
    client, auth_headers, dashboard, source, target
):
    moved = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/pages/move",
        headers=auth_headers,
        json={"from": source, "to": target},
    )
    assert moved.status_code == 200, moved.text
    assert _placement(moved.json()) == {
        "Fieldwork": "Fieldwork",
        "Quality": "Quality",
        "Coverage": "Coverage",
    }


def test_deleting_a_page_renumbers_the_ones_after_it(client, auth_headers, dashboard):
    """The old bug: the pages closed up and the widgets did not follow."""
    # Empty the middle page so it may be deleted.
    quality = next(w for w in dashboard["widgets"] if w["title"] == "Quality")
    client.delete(
        f"/api/v1/dashboards/{dashboard['id']}/widgets/{quality['id']}", headers=auth_headers
    )

    deleted = client.delete(
        f"/api/v1/dashboards/{dashboard['id']}/pages/1", headers=auth_headers
    )
    assert deleted.status_code == 200, deleted.text
    detail = deleted.json()
    assert [p["name"] for p in detail["pages"]] == ["Fieldwork", "Coverage"]
    assert _placement(detail) == {"Fieldwork": "Fieldwork", "Coverage": "Coverage"}


def test_a_page_with_widgets_on_it_is_not_deleted(client, auth_headers, dashboard):
    refused = client.delete(
        f"/api/v1/dashboards/{dashboard['id']}/pages/1", headers=auth_headers
    )
    assert refused.status_code == 409, refused.text


def test_the_last_page_stays(client, auth_headers):
    created = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "One page"}
    ).json()
    refused = client.delete(
        f"/api/v1/dashboards/{created['id']}/pages/0", headers=auth_headers
    )
    assert refused.status_code == 409, refused.text
    client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)
