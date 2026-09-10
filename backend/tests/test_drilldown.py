"""Drilling a board down a hierarchy, and the views that remember where.

A monitoring board is read top down: the country, then the province that is
behind, then the district inside it. Doing that by hand means changing a filter
and rebuilding every chart's grouping, so nobody does it. A hierarchy declared
once on the dashboard lets a click do both - narrow to what was clicked, and
regroup every chart on the page one level deeper.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.test_api_analytics import _stata_bytes, _zip_bytes


@pytest.fixture
def geography(client, auth_headers, request) -> dict:
    """Two provinces, four districts, uneven counts at both levels.

    Uneven on purpose: if every group were the same size, a chart drawn at the
    wrong level would still look right.
    """
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(12)],
            "province": ["Malampa"] * 7 + ["Sanma"] * 5,
            "district": (
                ["Central"] * 4 + ["North"] * 3 + ["Luganville"] * 2 + ["West"] * 3
            ),
            "sex": ["Male", "Female"] * 6,
        }
    )
    name = request.node.name[:40]
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                f"{name}.zip",
                _zip_bytes({f"{name}.dta": _stata_bytes(frame)}),
                "application/zip",
            )
        },
    ).json()
    dataset_id = uploaded["datasets"][0]["id"]

    board = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={
            "name": "Drill board",
            "drilldown": [
                {"variable": "province", "label": "Province"},
                {"variable": "district", "label": "District"},
            ],
        },
    ).json()
    return {"dataset_id": dataset_id, "board": board["id"]}


def add_chart(client, auth_headers, board: str, dataset_id: str, variable: str) -> str:
    response = client.post(
        f"/api/v1/dashboards/{board}/widgets",
        headers=auth_headers,
        json={
            "title": f"Interviews by {variable}",
            "widget_type": "chart",
            "dataset_id": dataset_id,
            "config": {
                "chart_type": "bar",
                "query": {
                    "dimensions": [{"variable": variable}],
                    "measures": [{"agg": "count", "alias": "Interviews"}],
                },
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["widgets"][-1]["id"]


def render(client, auth_headers, board: str, level: int = 0, filters: dict | None = None):
    response = client.post(
        f"/api/v1/dashboards/{board}/data?drill_level={level}",
        headers=auth_headers,
        json=filters or {},
    )
    assert response.status_code == 200, response.text
    return response.json()["widgets"]


def categories(widget: dict) -> list:
    return [row[0] for row in widget["result"]["rows"]]


def in_malampa() -> dict:
    return {
        "op": "and",
        "conditions": [
            {"variable": "province", "operator": "eq", "value": "Malampa",
             "use_label": True}
        ],
        "groups": [],
    }


def test_at_the_top_a_chart_groups_where_it_was_built(client, auth_headers, geography):
    widget_id = add_chart(
        client, auth_headers, geography["board"], geography["dataset_id"], "province"
    )
    widget = render(client, auth_headers, geography["board"])[widget_id]
    assert sorted(categories(widget)) == ["Malampa", "Sanma"]
    assert widget["grouped_on"] == ["province"]


def test_drilling_regroups_the_chart_one_level_down(client, auth_headers, geography):
    """The click narrows to Malampa and the bars become its districts."""
    widget_id = add_chart(
        client, auth_headers, geography["board"], geography["dataset_id"], "province"
    )
    widget = render(
        client, auth_headers, geography["board"], level=1, filters=in_malampa()
    )[widget_id]
    assert sorted(categories(widget)) == ["Central", "North"]
    # Clicking again has to filter by what is now on the axis, not by province.
    assert widget["grouped_on"] == ["district"]
    # And only Malampa's rows are counted: 4 Central plus 3 North.
    assert sum(row[1] for row in widget["result"]["rows"]) == 7


def test_every_chart_on_the_page_follows(client, auth_headers, geography):
    """Drilling is a question asked of the board, not of one visual."""
    first = add_chart(
        client, auth_headers, geography["board"], geography["dataset_id"], "province"
    )
    second = add_chart(
        client, auth_headers, geography["board"], geography["dataset_id"], "province"
    )
    widgets = render(
        client, auth_headers, geography["board"], level=1, filters=in_malampa()
    )
    assert sorted(categories(widgets[first])) == ["Central", "North"]
    assert sorted(categories(widgets[second])) == ["Central", "North"]


def test_a_chart_outside_the_hierarchy_is_left_alone(client, auth_headers, geography):
    """A chart of sex stays a chart of sex; it only narrows."""
    widget_id = add_chart(
        client, auth_headers, geography["board"], geography["dataset_id"], "sex"
    )
    widget = render(
        client, auth_headers, geography["board"], level=1, filters=in_malampa()
    )[widget_id]
    assert sorted(categories(widget)) == ["Female", "Male"]
    assert widget["grouped_on"] == ["sex"]
    assert sum(row[1] for row in widget["result"]["rows"]) == 7


def test_a_deeper_chart_does_not_climb_back_up(client, auth_headers, geography):
    """A district chart stays on districts while the board looks at a province."""
    widget_id = add_chart(
        client, auth_headers, geography["board"], geography["dataset_id"], "district"
    )
    widget = render(
        client, auth_headers, geography["board"], level=1, filters=in_malampa()
    )[widget_id]
    assert sorted(categories(widget)) == ["Central", "North"]


def test_drilling_past_the_last_level_stops_there(client, auth_headers, geography):
    widget_id = add_chart(
        client, auth_headers, geography["board"], geography["dataset_id"], "province"
    )
    widget = render(
        client, auth_headers, geography["board"], level=9, filters=in_malampa()
    )[widget_id]
    assert widget["grouped_on"] == ["district"]


def test_a_board_with_no_hierarchy_ignores_the_level(client, auth_headers, geography):
    """Nothing declared, nothing to drill: the level is quietly meaningless."""
    plain = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Plain board"}
    ).json()["id"]
    widget_id = add_chart(client, auth_headers, plain, geography["dataset_id"], "province")
    widget = render(client, auth_headers, plain, level=2)[widget_id]
    assert sorted(categories(widget)) == ["Malampa", "Sanma"]
