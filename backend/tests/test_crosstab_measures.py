"""Several variables in one table, side by side.

Asked for in these words: the sum of rejections by the supervisor and the sum
by headquarters, per interviewer, as columns of the same table. It used to take
one cross-tab per variable and copying the columns together by hand.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.export_tables import crosstab_table
from tests.test_dashboard_export import payload_of

INTERVIEWS = pd.DataFrame(
    {
        "responsible": ["ann", "ann", "ben", "ben", "ben", "cat"],
        "rejections__sup": [1, 2, 0, 3, 1, 0],
        "rejections__hq": [0, 1, 0, 0, 2, 4],
        "minutes": [30.0, 50.0, 20.0, 40.0, 60.0, 10.0],
    }
)


@pytest.fixture
def dataset_id(client, auth_headers) -> str:
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("interviews.csv", INTERVIEWS.to_csv(index=False).encode(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return (body["datasets"][0] if "datasets" in body else body)["id"]


def table(client, auth_headers, dataset_id, **request):
    return client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab",
        headers=auth_headers,
        json={"row_variable": "responsible", **request},
    )


def sums(*names: str) -> list[dict]:
    return [{"agg": "sum", "variable": name} for name in names]


def test_sums_of_several_variables_are_columns_of_one_table(client, auth_headers, dataset_id):
    response = table(
        client, auth_headers, dataset_id, measures=sums("rejections__sup", "rejections__hq")
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["row_labels"] == ["ann", "ben", "cat"]
    assert result["column_labels"] == ["sum of rejections__sup", "sum of rejections__hq"]
    assert result["values"] == [[3, 1], [4, 2], [0, 4]]
    # Sums add along a row: every rejection an interviewer had.
    assert result["row_totals"] == [4, 6, 4]
    assert result["column_totals"] == [7, 7]
    assert result["grand_total"] == 14
    assert result["chi_square"] is None


def test_means_have_the_overall_mean_as_their_total_and_no_row_total(
    client, auth_headers, dataset_id
):
    result = table(
        client,
        auth_headers,
        dataset_id,
        measures=[
            {"agg": "mean", "variable": "minutes"},
            {"agg": "mean", "variable": "rejections__sup"},
        ],
        percentages="row",
    ).json()
    assert result["values"][0] == [40.0, 1.5]
    # The mean of every interview, not the three interviewers' means added up.
    assert result["column_totals"][0] == pytest.approx(35.0)
    assert result["row_totals"] == [None, None, None]
    assert result["grand_total"] is None
    # A share of a row of means is not a share of anything.
    assert result["percentages"] == "none"


def test_percentages_of_sums(client, auth_headers, dataset_id):
    result = table(
        client,
        auth_headers,
        dataset_id,
        measures=sums("rejections__sup", "rejections__hq"),
        percentages="row",
    ).json()
    assert result["values"][0] == [75.0, 25.0]


def test_the_variables_are_the_columns_so_a_column_variable_is_refused(
    client, auth_headers, dataset_id
):
    response = table(
        client,
        auth_headers,
        dataset_id,
        column_variable="responsible",
        measures=sums("rejections__sup", "rejections__hq"),
    )
    assert response.status_code == 422
    assert "leave Columns empty" in response.text


def test_one_variable_in_the_list_is_the_ordinary_table(client, auth_headers, dataset_id):
    result = table(client, auth_headers, dataset_id, measures=sums("rejections__sup")).json()
    assert result["column_labels"] == ["sum of rejections__sup"]
    assert result["values"] == [[3], [4], [0]]


def test_saved_it_draws_on_a_dashboard_and_in_the_exported_files(client, auth_headers, dataset_id):
    request = {
        "row_variable": "responsible",
        "column_variable": "",
        "measures": sums("rejections__sup", "rejections__hq"),
    }
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Rejections",
            "dataset_id": dataset_id,
            "chart_type": "crosstab",
            "spec": {"crosstab": request},
        },
    ).json()
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Rejections board"}
    ).json()
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
    assert widget["result"]["column_labels"] == [
        "sum of rejections__sup",
        "sum of rejections__hq",
    ]
    assert widget["result"]["grand_total"] == 14

    html = client.get(f"/api/v1/dashboards/{board['id']}/export.html", headers=auth_headers)
    assert html.status_code == 200, html.text
    exported = next(
        one for one in payload_of(html.text)["widgets"] if one.get("kind") == "crosstab"
    )
    assert exported["crosstab"]["measure_labels"] == [
        "sum of rejections__sup",
        "sum of rejections__hq",
    ]
    # The Word report lays the same grid out from the same payload.
    heading, rows = crosstab_table(exported)
    assert heading == ["responsible", "sum of rejections__sup", "sum of rejections__hq", "Total"]
    assert rows[0] == ["ann", 3.0, 1.0, 4.0]
    assert rows[-1] == ["Total", 7.0, 7.0, 14.0]

    docx = client.get(f"/api/v1/dashboards/{board['id']}/export.docx", headers=auth_headers)
    assert docx.status_code == 200, docx.text


def test_small_cells_are_withheld_column_by_column(client, auth_headers, dataset_id, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "disclosure_threshold", 2)
    result = table(
        client,
        auth_headers,
        dataset_id,
        measures=[
            {"agg": "mean", "variable": "minutes"},
            {"agg": "sum", "variable": "rejections__hq"},
        ],
    ).json()
    # cat is one interview: their mean is that one interview, so it goes.
    cat = result["row_labels"].index("cat")
    assert result["suppressed"][cat] == [True, True]
    assert result["values"][cat] == [None, None]
    # And one more per column, so cat's cannot be recovered by subtracting the
    # others from the column's total; ben, with three, is still shown.
    ben = result["row_labels"].index("ben")
    assert result["values"][ben] == [40.0, 2.0]
    assert sum(hidden.count(True) for hidden in result["suppressed"]) == 4
