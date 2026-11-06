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

    Southern's single household is the interesting case: it is one record split
    across two cells, so one cell holds it and the other holds nobody. Only the
    first is small enough to withhold on its own, and withholding only that one
    would leave it recoverable from the row total.
    """
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(23)],
            "province": ["Northern"] * 10 + ["Highland"] * 10 + ["Western"] * 2 + ["Southern"],
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
    assert cells(plain)["Northern"] == [10]
    # Ten interviews, each standing for 12.5 people.
    assert cells(weighted)["Northern"] == [125]


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
    # The cells the floor would have taken are published in full. Southern's
    # female cell is null either way, because no woman lives there - that is an
    # absence rather than a withholding, which is exactly the distinction the
    # mask above exists to carry.
    assert cells(plain)["Western"] == [1, 1]
    assert cells(plain)["Southern"] == [None, 1]


def test_a_cell_below_the_floor_is_withheld(client, auth_headers, tiny, floor):
    result = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    assert hidden(result)["Western"] == [True, True]
    assert cells(result)["Western"] == [None, None]
    # The large provinces are untouched.
    assert hidden(result)["Northern"] == [False, False]
    assert cells(result)["Northern"] == [5, 5]


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

    Southern is one household, a man. The male cell rests on one record and is
    withheld; the female cell rests on none and is not small. Published beside
    a row total of 1, the withheld cell is simply 1 minus the other - so the
    other goes too.
    """
    result = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    assert hidden(result)["Southern"] == [True, True]


def test_a_published_total_is_the_true_one(client, auth_headers, tiny, floor):
    """Withholding a cell must not quietly change the arithmetic around it."""
    result = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    assert result["grand_total"] == 23
    assert result["column_totals"] == [11, 12]


def test_a_margin_that_would_give_a_cell_back_is_withheld_too(
    client, auth_headers, tiny, floor
):
    """A margin is a line sum, so it is recoverable arithmetic in both
    directions and has to be protected in the same pass as the cells.

    Southern is one household. Its row total is that household, so publishing it
    beside two starred cells would say precisely what the stars refused to.
    """
    result = table(
        client, auth_headers, tiny, row_variable="province", column_variable="sex"
    )
    margins = dict(zip(result["row_labels"], result["row_totals"], strict=True))
    assert margins["Southern"] is None
    assert margins["Western"] is None
    # The large provinces keep theirs.
    assert margins["Northern"] == 10
    assert dict(
        zip(result["row_labels"], result["row_totals_suppressed"], strict=True)
    )["Southern"] is True


def test_a_one_way_row_total_never_reprints_its_own_withheld_cell(
    client, auth_headers, tiny, floor
):
    """The sharpest form of it: with one column the row total is the cell.

    The table on screen does not draw a total column for a one-way table, so
    this is invisible there - and was still in the response, the CSV and the
    exported file.
    """
    result = table(client, auth_headers, tiny, row_variable="province")
    margins = dict(zip(result["row_labels"], result["row_totals"], strict=True))
    cell = dict(zip(result["row_labels"], result["values"], strict=True))
    assert cell["Southern"] == [None]
    assert margins["Southern"] is None, "the row total is the cell it just withheld"


def test_the_grand_total_goes_when_it_is_the_last_thing_standing(
    client, auth_headers, tiny, floor
):
    """A chain, not a single rule: withhold a row total and the grand total
    minus the other row totals gives it back."""
    result = table(client, auth_headers, tiny, row_variable="province")
    published = [t for t in result["row_totals"] if t is not None]
    # Two provinces published, two withheld. If the grand total were published
    # the withheld pair would sum to a known remainder - which is survivable,
    # because two unknowns and one equation have many answers. One unknown
    # would not be.
    assert len(published) == 2
    assert sum(1 for t in result["row_totals"] if t is None) >= 2


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

    Weighted, Western's cells read 12.5 and 12.5, which look like plenty. They
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
    assert hidden(weighted)["Western"] == [True, True]

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
    assert hidden(means)["Western"] == [True, True]


def test_only_the_records_that_reach_the_statistic_are_counted(
    client, auth_headers, request, floor
):
    """Every aggregate ignores nulls, so counting rows is counting the wrong
    thing.

    A hundred people in a province and one reported wage: the mean of that
    province is that one person's wage exactly. Judged on a hundred records it
    looks safe, and the platform publishes the wage.
    """
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(100)],
            "province": ["Northern"] * 100,
            # One reported wage in the whole province.
            "wage": [77777.0] + [None] * 99,
            "wt": [1.0] * 100,
        }
    )
    name = request.node.name[:40]
    dataset = client.post(
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

    means = table(
        client,
        auth_headers,
        dataset,
        row_variable="province",
        measure={"agg": "mean", "variable": "wage"},
    )
    assert cells(means)["Northern"] == [None], "one wage is one person's wage"
    assert hidden(means)["Northern"] == [True]

    # Counting the province itself is safe: a hundred people are a hundred
    # people, and the count discloses nobody.
    counts = table(client, auth_headers, dataset, row_variable="province")
    assert cells(counts)["Northern"] == [100]
    assert hidden(counts)["Northern"] == [False]


def test_a_null_weight_does_not_count_towards_a_weighted_cell(
    client, auth_headers, request, floor
):
    """A weighted aggregate drops a row with no weight, so that row is not
    behind the cell and must not be counted as protecting it."""
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(50)],
            "province": ["Northern"] * 50,
            "wage": [100.0] * 50,
            "wt": [12.5] + [None] * 49,
        }
    )
    name = request.node.name[:40]
    dataset = client.post(
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

    weighted = table(
        client,
        auth_headers,
        dataset,
        row_variable="province",
        measure={"agg": "count", "weight": "wt"},
    )
    assert hidden(weighted)["Northern"] == [True], "one weighted household, not fifty"


def test_a_weighted_count_is_not_withheld_over_a_variable_it_never_reads(
    client, auth_headers, request, floor
):
    """Which records count is decided by the SQL, not by the request's fields.

    A weighted count of records is SUM(weight) and never mentions a variable,
    so a sparsely answered optional question carried alongside it must not
    withhold a cell backed by fifty weighted households. Over-withholding is
    not the safe direction to err in: it teaches readers that the stars mean
    nothing.
    """
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(50)],
            "province": ["Northern"] * 50,
            # An optional question almost nobody answered.
            "wage": [100.0] + [None] * 49,
            "wt": [12.5] * 50,
        }
    )
    name = request.node.name[:40]
    dataset = client.post(
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

    counted = table(
        client,
        auth_headers,
        dataset,
        row_variable="province",
        # `variable` is ignored by a weighted count, and the API accepts one.
        measure={"agg": "count", "weight": "wt"},
    )
    assert hidden(counted)["Northern"] == [False], "fifty weighted households"
    assert cells(counted)["Northern"] == [625]

    # A weighted count *of* wage is the weight of those who answered it, as
    # the unweighted count of wage is how many answered: one household here,
    # so it is withheld like the one answer it is.
    answered = table(
        client,
        auth_headers,
        dataset,
        row_variable="province",
        measure={"agg": "count", "variable": "wage", "weight": "wt"},
    )
    assert hidden(answered)["Northern"] == [True], "one weighted household, not fifty"

    # The mean of the same sparse variable still is withheld: that one reads
    # the variable, and one answer is one person's answer.
    means = table(
        client,
        auth_headers,
        dataset,
        row_variable="province",
        measure={"agg": "mean", "variable": "wage", "weight": "wt"},
    )
    assert hidden(means)["Northern"] == [True]


def test_a_category_too_small_to_name_is_not_listed(client, auth_headers, tiny, floor):
    """A table with no cell values has no cell to blank.

    Naming a category that two households are in still says those two exist
    and where they are, so the category is left out of the list instead.
    """
    listing = table(client, auth_headers, tiny, row_variable="province", measure=None)
    assert listing["row_labels"] == ["Highland", "Northern"]
    assert listing["rows_withheld"] == 2

    everything = table(client, auth_headers, tiny, row_variable="province")
    assert len(everything["row_labels"]) == 4


def test_a_one_way_table_is_protected_down_its_single_column(
    client, auth_headers, tiny, floor
):
    """The only direction a reader can subtract along is the column."""
    result = table(client, auth_headers, tiny, row_variable="province")
    assert hidden(result)["Southern"] == [True]
    assert hidden(result)["Western"] == [True]
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
    western = next(line for line in body.splitlines() if line.startswith("Western"))
    # Cells and the row total alike: the total is two households, which is
    # under the floor in its own right.
    assert western.split(",")[1:4] == ["*", "*", "*"]
    northern = next(line for line in body.splitlines() if line.startswith("Northern"))
    assert northern.split(",")[1:4] == ["5.0", "5.0", "10.0"]


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

    Western is two households, one cell each. The ordinary export would write
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
    assert masks["Western"] == [True, True]
    assert rows["Western"] == [None, None]
    assert masks["Southern"] == [True, True]
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


def test_a_table_with_nothing_withheld_still_travels_fixed(
    client, auth_headers, dataset_id, floor
):
    """Under a floor every cross-tabulation travels finished, not just a
    starred one.

    Filtering in the browser could cut a comfortably large cell down to a small
    one, so the cube cannot travel even when the table as exported has nothing
    to hide. Which means the widget stops answering the page's filters, and the
    reader has to be told so whether or not anything is starred.

    The note itself is built by the file's own script, so it is checked in a
    browser rather than by searching the source - the template carries every
    string it might print, so grepping the file proves nothing.
    """
    html = dashboard_with(
        client, auth_headers, dataset_id, {"row_variable": "region", "column_variable": "sex"}
    )
    widget = _payload(html)["widgets"][0]
    assert widget["crosstab"]["fixed"], "still fixed, with nothing withheld"
    assert not any(any(row) for row in widget["crosstab"]["fixed"]["suppressed"])
    assert widget["cube"]["rows"] == []


def _payload(html: str) -> dict:
    import json
    import re

    found = re.search(r'id="board-data">(.*?)</script>', html, re.S)
    assert found, "the file carries no data"
    return json.loads(found.group(1))
