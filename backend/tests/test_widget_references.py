"""Changing what one widget points at must not disturb the others.

The reported fault: change the chart on a dashboard widget and every other
widget vanishes. The editor sent the change through the whole-dashboard PATCH,
whose contract is "here is the complete widget list" - so a list holding the
one widget being edited deleted all the rest, on every page.

That contract is right for the board editor, which really does send the whole
list after a drag. It is the wrong endpoint for editing a single widget, so a
widget's references now travel on the per-widget PATCH, which touches nothing
else. Both behaviours are pinned below so a later change cannot quietly swap
one for the other.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def board(client, auth_headers, dataset_id):
    """A dashboard with three widgets, one of them on a second page."""

    def chart(name: str, variable: str) -> str:
        response = client.post(
            "/api/v1/dashboards/charts",
            headers=auth_headers,
            json={
                "name": name,
                "dataset_id": dataset_id,
                "chart_type": "bar",
                "spec": {
                    "query": {
                        "dataset_id": dataset_id,
                        "dimensions": [{"variable": variable}],
                        "measures": [{"agg": "count"}],
                    }
                },
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    by_region = chart("By region", "region")
    by_sex = chart("By sex", "sex")

    dashboard = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": "Board", "pages": [{"name": "One"}, {"name": "Two"}]},
    ).json()

    ids = []
    for title, chart_id, page in (
        ("First", by_region, 0),
        ("Second", by_region, 0),
        ("Elsewhere", by_region, 1),
    ):
        detail = client.post(
            f"/api/v1/dashboards/{dashboard['id']}/widgets",
            headers=auth_headers,
            json={
                "title": title,
                "widget_type": "chart",
                "chart_id": chart_id,
                "page": page,
            },
        )
        assert detail.status_code == 201, detail.text
        ids = {w["title"]: w["id"] for w in detail.json()["widgets"]}

    return {"id": dashboard["id"], "widgets": ids, "by_region": by_region, "by_sex": by_sex}


def widgets_of(client, auth_headers, dashboard_id) -> dict[str, str]:
    response = client.get(f"/api/v1/dashboards/{dashboard_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    return {w["title"]: w["chart_id"] for w in response.json()["widgets"]}


def test_changing_one_widgets_chart_keeps_every_other_widget(
    client, auth_headers, board
):
    """The exact fault: swap the chart on one widget, lose the whole board."""
    response = client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{board['widgets']['First']}",
        headers=auth_headers,
        json={"chart_id": board["by_sex"]},
    )
    assert response.status_code == 200, response.text

    after = widgets_of(client, auth_headers, board["id"])
    assert sorted(after) == ["Elsewhere", "First", "Second"]
    assert after["First"] == board["by_sex"]
    # The others are untouched, including the one on the other page.
    assert after["Second"] == board["by_region"]
    assert after["Elsewhere"] == board["by_region"]


def test_a_widget_reference_can_be_cleared(client, auth_headers, board):
    """Sent as null it is cleared, rather than read as "not mentioned"."""
    response = client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{board['widgets']['Second']}",
        headers=auth_headers,
        json={"chart_id": None},
    )
    assert response.status_code == 200, response.text
    assert widgets_of(client, auth_headers, board["id"])["Second"] is None


def test_a_patch_that_does_not_mention_a_reference_leaves_it_alone(
    client, auth_headers, board
):
    """Editing only the title must not blank the chart it points at."""
    client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{board['widgets']['First']}",
        headers=auth_headers,
        json={"title": "Renamed"},
    )
    after = widgets_of(client, auth_headers, board["id"])
    assert after["Renamed"] == board["by_region"]
    assert len(after) == 3


def test_the_whole_dashboard_patch_still_replaces_the_list(
    client, auth_headers, board
):
    """The board editor's contract, kept deliberately.

    It sends the complete list after a drag, and a widget removed from the
    board has to be removed from the dashboard. This is the behaviour that made
    the bug above so damaging, so it is pinned here: the fix was to stop
    routing single-widget edits through it, not to weaken it.
    """
    keep = board["widgets"]["First"]
    response = client.patch(
        f"/api/v1/dashboards/{board['id']}",
        headers=auth_headers,
        json={
            "widgets": [
                {
                    "id": keep,
                    "title": "First",
                    "widget_type": "chart",
                    "chart_id": board["by_region"],
                    "config": {},
                    "layout": {},
                    "position": 0,
                    "page": 0,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert sorted(widgets_of(client, auth_headers, board["id"])) == ["First"]
