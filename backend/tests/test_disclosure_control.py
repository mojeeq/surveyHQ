"""Weighted tables, and the floor below which a cell is not published.

Two things a statistics office cannot publish without. A cross-tabulation of a
labour force survey with no weights is a count of interviews wearing the name
of a population estimate. And a cell resting on two households identifies them
- which matters more here than in most places, because a dashboard share link
is public and a standalone export is a copy nobody can withdraw.

The floor is a deployment setting rather than a control in the interface: it is
a rule of the office, and a rule anybody can switch off to get a prettier table
is not one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.core.config import settings
from tests.test_api_analytics import _stata_bytes, _zip_bytes


@pytest.fixture
def floor(monkeypatch):
    """The office publishes nothing resting on fewer than five records."""
    monkeypatch.setattr(settings, "disclosure_threshold", 5)


@pytest.fixture
def tiny(client, auth_headers, request) -> str:
    """Two large provinces, one with two households and one with a single one.

    Tafea's single household is the interesting case: it is one record split
    across two cells, so one cell holds it and the other holds nobody. Only the
    first is small enough to withhold on its own, and withholding only that one
    would leave it recoverable from the row total.
    """
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(23)],
            "province": ["Shefa"] * 10 + ["Sanma"] * 10 + ["Torba"] * 2 + ["Tafea"],
            "sex": (["M", "F"] * 5) + (["M", "F"] * 5) + ["M", "F"] + ["M"],
            "wage": [100.0] * 23,
            "wt": [12.5] * 23,
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
    return uploaded["datasets"][0]["id"]


def table(client, auth_headers, dataset: str, **body: object) -> dict:
    response = client.post(
        f"/api/v1/analytics/datasets/{dataset}/crosstab", headers=auth_headers, json=body
    )
    assert response.status_code == 200, response.text
    return response.json()


def cells(result: dict) -> dict[str, list]:
    return dict(zip(result["row_labels"], result["values"], strict=True))


def hidden(result: dict) -> dict[str, list]:
    return dict(zip(result["row_labels"], result["suppressed"], strict=True))


# --- survey weights ---------------------------------------------------------


def test_a_weighted_cell_estimates_a_population(client, auth_headers, tiny):
    """Without this the cells are a count of interviews under another name."""
    plain = table(client, auth_headers, tiny, row_variable="province")
    weighted = table(
        client,
        auth_headers,
        tiny,
        row_variable="province",
        measure={"agg": "count", "weight": "wt"},
    )
    assert cells(plain)["Shefa"] == [10]
    # Ten interviews, each standing for 12.5 people.
    assert cells(weighted)["Shefa"] == [125]


def test_a_weighted_count_is_not_called_a_count(client, auth_headers, tiny):
    """A column headed "Count" invites the reader to quote 125 interviews."""
    weighted = table(
        client,
        auth_headers,
        tiny,
        row_variable="province",
        measure={"agg": "count", "weight": "wt"},
    )
    assert weighted["column_labels"] == ["Estimated total (wt)"]
    plain = table(client, auth_headers, tiny, row_variable="province")
    assert plain["column_labels"] == ["Count"]


def test_row_percentages_still_add_up_when_weighted(client, auth_headers, tiny):
    weighted = table(
        client,
        auth_headers,
        tiny,
        row_variable="province",
        column_variable="sex",
        measure={"agg": "count", "weight": "wt"},
        percentages="row",
    )
    for row in weighted["values"]:
        assert abs(sum(v for v in row if v is not None) - 100) < 0.05


def test_a_weighted_table_reports_no_chi_square(client, auth_headers, tiny):
    """Pearson's test counts observations.

    Weighted cells estimate a population, so feeding them in claims a sample
    the size of the country and calls anything significant. A design-based test
    is not arithmetic on the finished table, so nothing is reported rather than
    something confident and wrong.
    """
    weighted = table(
        client,
        auth_headers,
        tiny,
        row_variable="province",
        column_variable="sex",
        measure={"agg": "count", "weight": "wt"},
    )
    assert weighted["chi_square"] is None

    unweighted = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    assert unweighted["chi_square"] is not None


def test_a_weight_on_a_calculation_that_cannot_carry_one_is_refused(
    client, auth_headers, tiny
):
    """A weighted median is a different calculation, not the same one times w."""
    response = client.post(
        f"/api/v1/analytics/datasets/{tiny}/crosstab",
        headers=auth_headers,
        json={
            "row_variable": "province",
            "measure": {"agg": "median", "variable": "wage", "weight": "wt"},
        },
    )
    assert response.status_code == 422


# --- the floor --------------------------------------------------------------


def test_nothing_is_withheld_when_no_floor_is_set(client, auth_headers, tiny):
    """Every deployment that has not asked for this sees exactly what it did."""
    plain = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    assert plain["disclosure_threshold"] == 0
    assert not any(any(row) for row in plain["suppressed"])
    # The cells the floor would have taken are published in full. Tafea's
    # female cell is null either way, because no woman lives there - that is an
    # absence rather than a withholding, which is exactly the distinction the
    # mask above exists to carry.
    assert cells(plain)["Torba"] == [1, 1]
    assert cells(plain)["Tafea"] == [None, 1]


def test_a_cell_below_the_floor_is_withheld(client, auth_headers, tiny, floor):
    result = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    assert hidden(result)["Torba"] == [True, True]
    assert cells(result)["Torba"] == [None, None]
    # The large provinces are untouched.
    assert hidden(result)["Shefa"] == [False, False]
    assert cells(result)["Shefa"] == [5, 5]


def test_a_zero_is_not_withheld(client, auth_headers, tiny, floor):
    """An absence identifies nobody, and blanking it would only announce that
    somebody is being protected where nobody is."""
    result = table(client, auth_headers, tiny, row_variable="sex", column_variable="sex")
    # Every off-diagonal cell is a structural zero and every diagonal one is
    # large, so nothing here needs protecting.
    assert not any(any(row) for row in result["suppressed"])


def test_a_lone_withheld_cell_takes_a_second_one_with_it(
    client, auth_headers, tiny, floor
):
    """Otherwise the withholding is decorative.

    Tafea is one household, a man. The male cell rests on one record and is
    withheld; the female cell rests on none and is not small. Published beside
    a row total of 1, the withheld cell is simply 1 minus the other - so the
    other goes too.
    """
    result = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    assert hidden(result)["Tafea"] == [True, True]


def test_the_totals_are_the_true_ones(client, auth_headers, tiny, floor):
    """Totals are published; cells are not. That is the whole shape of the
    rule, and it is why the second cell above has to go."""
    result = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    assert result["grand_total"] == 23
    assert dict(zip(result["row_labels"], result["row_totals"], strict=True))["Tafea"] == 1


def test_a_withheld_table_reports_no_chi_square(client, auth_headers, tiny, floor):
    """A statistic computed over cells the reader has been refused."""
    result = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    assert result["chi_square"] is None


def test_a_floor_with_nothing_small_under_it_still_reports_chi_square(
    client, auth_headers, dataset_id, floor
):
    """Merely having the rule is not a reason to withhold the statistic."""
    result = table(
        client, auth_headers, dataset_id, row_variable="region", column_variable="sex"
    )
    assert not any(any(row) for row in result["suppressed"])
    assert result["chi_square"] is not None


def test_disclosure_is_judged_on_records_not_on_what_the_cell_shows(
    client, auth_headers, tiny, floor
):
    """The number that matters is how many people are behind the cell.

    Weighted, Torba's cells read 12.5 and 12.5, which look like plenty. They
    rest on one household each.
    """
    weighted = table(
        client,
        auth_headers,
        tiny,
        row_variable="province",
        column_variable="sex",
        measure={"agg": "count", "weight": "wt"},
    )
    assert hidden(weighted)["Torba"] == [True, True]

    # Same for a mean, where the displayed value says nothing about how many
    # incomes it averages.
    means = table(
        client,
        auth_headers,
        tiny,
        row_variable="province",
        column_variable="sex",
        measure={"agg": "mean", "variable": "wage"},
    )
    assert hidden(means)["Torba"] == [True, True]


def test_a_category_too_small_to_name_is_not_listed(client, auth_headers, tiny, floor):
    """A table with no cell values has no cell to blank.

    Naming a category that two households are in still says those two exist
    and where they are, so the category is left out of the list instead.
    """
    listing = table(client, auth_headers, tiny, row_variable="province", measure=None)
    assert listing["row_labels"] == ["Sanma", "Shefa"]
    assert listing["rows_withheld"] == 2

    everything = table(client, auth_headers, tiny, row_variable="province")
    assert len(everything["row_labels"]) == 4


def test_a_one_way_table_is_protected_down_its_single_column(
    client, auth_headers, tiny, floor
):
    """The only direction a reader can subtract along is the column."""
    result = table(client, auth_headers, tiny, row_variable="province")
    assert hidden(result)["Tafea"] == [True]
    assert hidden(result)["Torba"] == [True]
    # Two withheld cells sharing a known remainder cannot be told apart.
    assert sum(1 for row in result["suppressed"] if row[0]) >= 2


def test_the_csv_marks_a_withheld_cell_rather_than_leaving_it_blank(
    client, auth_headers, tiny, floor
):
    """Blank already means no data. A file cannot say both with one symbol."""
    response = client.post(
        f"/api/v1/analytics/datasets/{tiny}/crosstab/export",
        headers=auth_headers,
        json={"row_variable": "province", "column_variable": "sex"},
    )
    assert response.status_code == 200, response.text
    body = response.content.decode("utf-8-sig")
    torba = next(line for line in body.splitlines() if line.startswith("Torba"))
    assert torba.split(",")[1:3] == ["*", "*"]
    # The row total is still the true one.
    assert torba.split(",")[3] == "2.0"


# --- the standalone export --------------------------------------------------
#
# This is the copy that leaves the building. The ordinary export carries a cube
# - the cell values at their finest grain - so the browser can re-add them as
# the reader filters. Under a floor that cube is the withheld numbers written
# into a file nobody can withdraw, so the table is finished server-side instead
# and travels without them.


def dashboard_with(client, auth_headers, dataset: str, spec: dict) -> str:
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Province by sex",
            "dataset_id": dataset,
            "chart_type": "crosstab",
            "spec": {"crosstab": spec},
        },
    ).json()
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Published"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Province by sex",
            "widget_type": "chart",
            "chart_id": chart["id"],
        },
    )
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/export.html", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    return response.text


def test_the_exported_file_does_not_carry_the_withheld_numbers(
    client, auth_headers, tiny, floor
):
    """The point of the whole exercise.

    Torba is two households, one cell each. The ordinary export would write
    those two cells into the file as cube rows, so anyone opening it in a text
    editor would read exactly what the screen refused to show.
    """
    html = dashboard_with(
        client, auth_headers, tiny, {"row_variable": "province", "column_variable": "sex"}
    )
    payload = _payload(html)
    widget = payload["widgets"][0]
    assert widget["crosstab"]["fixed"], "the table must travel finished, not as a cube"
    assert widget["cube"]["rows"] == []

    fixed = widget["crosstab"]["fixed"]
    rows = dict(zip(fixed["row_labels"], fixed["values"], strict=True))
    masks = dict(zip(fixed["row_labels"], fixed["suppressed"], strict=True))
    assert masks["Torba"] == [True, True]
    assert rows["Torba"] == [None, None]
    assert masks["Tafea"] == [True, True]
    # The totals still reach the file, which is what makes the secondary
    # withholding above necessary rather than fussy.
    assert fixed["grand_total"] == 23


def test_a_dashboard_with_no_floor_still_exports_a_filterable_cube(
    client, auth_headers, tiny
):
    """Nothing about the existing export changes for a deployment without one."""
    html = dashboard_with(
        client, auth_headers, tiny, {"row_variable": "province", "column_variable": "sex"}
    )
    widget = _payload(html)["widgets"][0]
    assert "fixed" not in widget["crosstab"]
    assert widget["cube"]["rows"], "the browser needs the cells to re-add"


def test_the_file_says_a_withheld_table_cannot_be_narrowed(
    client, auth_headers, tiny, floor
):
    """A reader who filters and sees nothing move deserves to know why."""
    html = dashboard_with(
        client, auth_headers, tiny, {"row_variable": "province", "column_variable": "sex"}
    )
    assert "does not respond to the filters above" in html


def _payload(html: str) -> dict:
    import json
    import re

    found = re.search(r'id="board-data">(.*?)</script>', html, re.S)
    assert found, "the file carries no data"
    return json.loads(found.group(1))
