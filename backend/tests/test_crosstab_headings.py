"""Renaming the columns of a table.

"sum of rejections__sup" is what the data calls a column; "Rejected by
supervisor" is what a reader should see. Only the heading changes: the label
underneath is what a click on the heading filters by, and that must not move.
"""

from __future__ import annotations

from app.services.export_tables import crosstab_table
from tests.test_crosstab_measures import dataset_id, sums  # noqa: F401 - fixture
from tests.test_dashboard_export import payload_of

RENAMED = {
    "column_headings": {
        "sum of rejections__sup": "Rejected by supervisor",
        "sum of rejections__hq": "Rejected by HQ",
        "a column that is not there": "Ignored",
    },
    "row_heading": "Interviewer",
}


def request(**extra) -> dict:
    return {
        "row_variable": "responsible",
        "column_variable": "",
        "measures": sums("rejections__sup", "rejections__hq"),
        **RENAMED,
        **extra,
    }


def test_the_headings_change_and_the_labels_do_not(client, auth_headers, dataset_id):  # noqa: F811
    result = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab", headers=auth_headers, json=request()
    ).json()
    assert result["column_headings"] == ["Rejected by supervisor", "Rejected by HQ"]
    assert result["row_heading"] == "Interviewer"
    # What a click filters by, unchanged.
    assert result["column_labels"] == ["sum of rejections__sup", "sum of rejections__hq"]


def test_a_blank_name_keeps_the_heading_the_data_gives(client, auth_headers, dataset_id):  # noqa: F811
    result = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab",
        headers=auth_headers,
        json=request(column_headings={"sum of rejections__sup": "  "}, row_heading=""),
    ).json()
    assert result["column_headings"] == []
    assert result["row_heading"] == ""


def test_a_category_column_can_be_renamed_too(client, auth_headers, dataset_id):  # noqa: F811
    result = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab",
        headers=auth_headers,
        json={
            "row_variable": "",
            "column_variable": "responsible",
            "column_headings": {"ann": "Ann Kalo"},
        },
    ).json()
    assert result["column_labels"] == ["ann", "ben", "cat"]
    assert result["column_headings"] == ["Ann Kalo", "ben", "cat"]


def test_the_csv_the_dashboard_and_the_exported_files_use_them(
    client,
    auth_headers,
    dataset_id,  # noqa: F811
):
    csv = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab/export",
        headers=auth_headers,
        json=request(),
    )
    assert csv.status_code == 200, csv.text
    assert csv.content.decode("utf-8-sig").splitlines()[0] == (
        "Interviewer,Rejected by supervisor,Rejected by HQ,Total"
    )

    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Rejections",
            "dataset_id": dataset_id,
            "chart_type": "crosstab",
            "spec": {"crosstab": request()},
        },
    ).json()
    board = client.post("/api/v1/dashboards", headers=auth_headers, json={"name": "Renamed"}).json()
    client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "Rejections", "widget_type": "chart", "chart_id": chart["id"]},
    )
    rendered = client.post(
        f"/api/v1/dashboards/{board['id']}/data",
        headers=auth_headers,
        json={"op": "and", "conditions": [], "groups": []},
    ).json()
    widget = next(iter(rendered["widgets"].values()))
    assert widget["result"]["column_headings"] == ["Rejected by supervisor", "Rejected by HQ"]

    html = client.get(f"/api/v1/dashboards/{board['id']}/export.html", headers=auth_headers)
    exported = next(
        one for one in payload_of(html.text)["widgets"] if one.get("kind") == "crosstab"
    )
    assert exported["crosstab"]["row_heading"] == "Interviewer"
    heading, _ = crosstab_table(exported)
    assert heading == ["Interviewer", "Rejected by supervisor", "Rejected by HQ", "Total"]
