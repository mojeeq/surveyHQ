"""A data quality panel has to answer the question the page is asking.

The panel reports what the last run of each check found, which is right when
the dashboard shows everything: running eight full-table scans because somebody
opened a page is not. But a filtered page is asking about a subset that no run
ever counted, and a panel that goes on reporting the whole dataset beside
widgets that have narrowed is answering a question nobody asked.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.test_api_analytics import _stata_bytes, _zip_bytes


@pytest.fixture
def graded(client, auth_headers, request) -> dict:
    """A dataset where the failures are all in one province.

    Shefa's four rows are all out of range; Sanma's four are all inside it. So
    the whole dataset fails half its rows, Shefa fails all of them, and Sanma
    fails none - three different answers, which is what makes the filter
    visible rather than merely plausible.
    """
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(8)],
            "province": ["Shefa"] * 4 + ["Sanma"] * 4,
            "age": [200.0, 201.0, 202.0, 203.0, 30.0, 31.0, 32.0, 33.0],
        }
    )
    # Named after the test: uploading the same name twice replaces the dataset,
    # so a shared name would leave every test after the first one looking at a
    # dataset carrying the previous tests' rules as well as its own.
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

    rule = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "name": "Age within range",
            "dataset_id": dataset_id,
            "check_type": "value_range",
            "config": {"variable": "age", "min": 0, "max": 120},
            "threshold": 0.0,
        },
    )
    assert rule.status_code == 201, rule.text
    ran = client.post(
        f"/api/v1/monitoring/quality-rules/{rule.json()['id']}/run", headers=auth_headers
    )
    assert ran.status_code == 200, ran.text

    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Quality board"}
    ).json()
    widget = client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Data quality",
            "widget_type": "quality",
            "dataset_id": dataset_id,
            "config": {"dataset_id": dataset_id},
        },
    )
    assert widget.status_code == 201, widget.text
    return {"dataset_id": dataset_id, "board": board["id"]}


def render(client, auth_headers, board: str, filters: dict | None = None) -> dict:
    response = client.post(
        f"/api/v1/dashboards/{board}/data", headers=auth_headers, json=filters or {}
    )
    assert response.status_code == 200, response.text
    panel = next(
        w for w in response.json()["widgets"].values() if w.get("type") == "quality"
    )
    return panel


def only(province: str) -> dict:
    return {
        "op": "and",
        "conditions": [{"variable": "province", "operator": "eq", "value": province}],
        "groups": [],
    }


def test_unfiltered_it_still_reports_the_stored_run(client, auth_headers, graded):
    """The cheap path stays cheap: no filter, no scans, and a timestamp."""
    panel = render(client, auth_headers, graded["board"])
    check = panel["checks"][0]
    assert panel["filtered"] is False
    assert check["total_rows"] == 8
    assert check["failed_rows"] == 4
    # It came from a stored run, so it can say when.
    assert check["run_at"]


def test_a_filter_narrows_what_the_panel_counts(client, auth_headers, graded):
    """Shefa is where the bad ages are: every one of its rows should fail."""
    panel = render(client, auth_headers, graded["board"], only("Shefa"))
    check = panel["checks"][0]
    assert panel["filtered"] is True
    assert check["total_rows"] == 4
    assert check["failed_rows"] == 4
    assert check["failure_rate"] == pytest.approx(1.0)
    assert check["passed"] is False
    # Counted for this request, so there is no "last run at" to show.
    assert check["run_at"] is None


def test_a_filter_can_make_the_panel_pass(client, auth_headers, graded):
    """The other half of it: Sanma's rows are all fine, so the check passes."""
    panel = render(client, auth_headers, graded["board"], only("Sanma"))
    check = panel["checks"][0]
    assert check["total_rows"] == 4
    assert check["failed_rows"] == 0
    assert check["passed"] is True
    assert panel["failing"] == 0
    assert panel["passing"] == 1


def test_a_filter_on_a_variable_the_dataset_lacks_is_reported_not_applied(
    client, auth_headers, graded
):
    """The same courtesy every other widget gets: say so rather than go blank."""
    panel = render(
        client,
        auth_headers,
        graded["board"],
        {
            "op": "and",
            "conditions": [{"variable": "not_here", "operator": "eq", "value": "x"}],
            "groups": [],
        },
    )
    assert panel["filters_ignored"] == ["not_here"]
    # Nothing could be narrowed, so the stored run is what it reports.
    assert panel["filtered"] is False
    assert panel["checks"][0]["total_rows"] == 8
