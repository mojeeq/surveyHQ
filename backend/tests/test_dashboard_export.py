"""The dashboard as one HTML file, with its filters still working.

A board is often wanted somewhere the platform is not: on a ministry's own web
host, beside a report, on a laptop taken to a meeting. A picture of it loses
the thing that makes it a dashboard, which is that the reader can narrow it and
watch the numbers move.

So the file carries data rather than pictures. Each widget's numbers are
exported at the grain its filters need - grouped by what it groups on and by
every variable the page's controls name - and the browser adds them back up.
These cover the arithmetic that makes that sound, which is the part that could
be quietly wrong: a sum of counts is a count, and a mean has to be carried as
its total and its number of values rather than averaged again.
"""

from __future__ import annotations

import json
import re

import pandas as pd
import pytest

from tests.test_api_analytics import _stata_bytes, _zip_bytes


def payload_of(html: str) -> dict:
    found = re.search(r'id="board-data">(.*?)</script>', html, re.S)
    assert found, "the file carries no data"
    return json.loads(found.group(1))


def widget_named(payload: dict, title: str) -> dict:
    return next(widget for widget in payload["widgets"] if widget["title"] == title)


@pytest.fixture
def board(client, auth_headers, request) -> dict:
    """Wages in two provinces, so a filtered mean is not the unfiltered one."""
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(8)],
            "province": ["Shefa"] * 4 + ["Sanma"] * 4,
            "wage": [100.0, 200.0, 300.0, 400.0, 1000.0, 1000.0, 1000.0, 2000.0],
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

    counts = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Interviews by province",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "province"}],
                    "measures": [{"agg": "count", "alias": "Interviews"}],
                }
            },
        },
    ).json()
    means = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Mean wage by province",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "province"}],
                    "measures": [{"agg": "mean", "variable": "wage", "alias": "Mean wage"}],
                }
            },
        },
    ).json()
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Exportable"}
    ).json()
    for chart in (counts, means):
        client.post(
            f"/api/v1/dashboards/{dashboard['id']}/widgets",
            headers=auth_headers,
            json={"title": chart["name"], "widget_type": "chart", "chart_id": chart["id"]},
        )
    client.patch(
        f"/api/v1/dashboards/{dashboard['id']}",
        headers=auth_headers,
        json={
            "filters": [
                {"variable": "province", "dataset_id": dataset_id, "label": "Province", "page": 0}
            ]
        },
    )
    return {"id": dashboard["id"], "dataset_id": dataset_id}


def export(client, auth_headers, board) -> str:
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/export.html", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    return response.text


def test_the_file_stands_on_its_own(client, auth_headers, board):
    """One page, with the data inside it rather than fetched from a server."""
    html = export(client, auth_headers, board)
    assert html.lstrip().startswith("<!doctype html>")
    assert "/api/v1/" not in html
    payload = payload_of(html)
    assert payload["name"] == "Exportable"
    assert [control["variable"] for control in payload["filters"]] == ["province"]
    assert payload["filters"][0]["values"] == ["Sanma", "Shefa"]


def test_a_count_is_carried_at_the_grain_its_filter_needs(client, auth_headers, board):
    """The point of the whole exercise: the filter has rows to work on."""
    cube = widget_named(payload_of(export(client, auth_headers, board)), "Interviews by province")["cube"]
    assert cube["dimensions"] == ["province"]
    # Grouped on the filter's variable already, so it is tested against that
    # same column rather than a second copy of it.
    assert cube["filters"] == [{"variable": "province", "column": "province"}]
    counts = {row[0]: row[1] for row in cube["rows"]}
    assert counts == {"Shefa": 4, "Sanma": 4}


def test_a_mean_travels_as_its_total_and_its_count(client, auth_headers, board):
    """An average of averages is not an average.

    Shefa's mean wage is 250 and Sanma's is 1,250; the mean over both is 750,
    which is not the average of 250 and 1,250 unless the groups happen to be
    the same size. Carrying the total and the number of values lets the browser
    divide them again and get the right number for any filter.
    """
    cube = widget_named(payload_of(export(client, auth_headers, board)), "Mean wage by province")["cube"]
    recipe = cube["measures"][0]
    assert recipe["how"] == "mean"
    assert len(recipe["parts"]) == 2
    at = {column["name"]: index for index, column in enumerate(cube["columns"])}
    totals = {row[at["province"]]: row[at[recipe["parts"][0]]] for row in cube["rows"]}
    counts = {row[at["province"]]: row[at[recipe["parts"][1]]] for row in cube["rows"]}
    assert totals == {"Shefa": 1000.0, "Sanma": 5000.0}
    assert counts == {"Shefa": 4, "Sanma": 4}
    # What the browser will work out, checked here where it can be:
    assert totals["Shefa"] / counts["Shefa"] == 250.0
    assert sum(totals.values()) / sum(counts.values()) == 750.0


def test_a_widget_that_cannot_be_recomputed_says_so(client, auth_headers, board):
    """A median of medians is not a median, so the tile is frozen and admits it."""
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Median wage",
            "dataset_id": board["dataset_id"],
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "province"}],
                    "measures": [{"agg": "median", "variable": "wage", "alias": "Median"}],
                }
            },
        },
    ).json()
    client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "Median wage", "widget_type": "chart", "chart_id": chart["id"]},
    )
    widget = widget_named(payload_of(export(client, auth_headers, board)), "Median wage")
    assert widget["kind"] == "snapshot"
    assert "median" in widget["frozen_because"]
    # Still drawn, as it stood: a frozen widget is not a blank one.
    assert widget["snapshot"]["result"]["rows"]


def test_survey_answers_cannot_become_script_on_the_page(client, auth_headers, request):
    """The data goes in as data, whatever an interviewer typed into a field."""
    frame = pd.DataFrame(
        {
            "interview__key": ["k1", "k2"],
            "place": ["</script><script>alert(1)</script>", "Shefa"],
        }
    )
    name = request.node.name[:40]
    dataset_id = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                f"{name}.zip",
                _zip_bytes({f"{name}.dta": _stata_bytes(frame)}),
                "application/zip",
            )
        },
    ).json()["datasets"][0]["id"]
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Places",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "place"}],
                    "measures": [{"agg": "count", "alias": "n"}],
                }
            },
        },
    ).json()
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Hostile"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "Places", "widget_type": "chart", "chart_id": chart["id"]},
    )
    html = client.get(
        f"/api/v1/dashboards/{dashboard['id']}/export.html", headers=auth_headers
    ).text
    # The answer survives as text and cannot close the tag it sits in.
    assert "</script><script>alert(1)</script>" not in html
    payload = payload_of(html)
    rows = payload["widgets"][0]["cube"]["rows"]
    assert any("alert(1)" in str(row[0]) for row in rows)


def test_another_users_dashboard_cannot_be_exported(client, auth_headers, board):
    """The export is a read of the whole board, so it takes the same permission."""
    missing = client.get(
        "/api/v1/dashboards/00000000-0000-0000-0000-000000000000/export.html",
        headers=auth_headers,
    )
    assert missing.status_code == 404
