"""Tabulating one variable, without inventing a second to cross it with.

"Tabulate this" usually means the frequencies of a single variable. Requiring
both a row and a column made people pick a second variable they did not want
and then read around it.

A one-way table keeps the two-way shape, with the side that has no variable
standing in as a single row or column named after the measure, so the renderer,
the export and the dashboard widget need to know nothing about it.
"""

from __future__ import annotations

import pytest


def crosstab(client, auth_headers, dataset_id, **payload):
    response = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab",
        headers=auth_headers,
        json={"measure": {"agg": "count"}, **payload},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_row_variable_alone_gives_its_frequencies(client, auth_headers, dataset_id):
    table = crosstab(client, auth_headers, dataset_id, row_variable="region")
    assert sorted(table["row_labels"]) == ["North", "South"]
    # One column, named after the measure rather than after a variable.
    assert table["column_labels"] == ["Count"]
    assert [row[0] for row in table["values"]] == table["row_totals"]
    assert table["grand_total"] == sum(table["row_totals"])


def test_a_column_variable_alone_gives_the_same_the_other_way_round(
    client, auth_headers, dataset_id
):
    table = crosstab(client, auth_headers, dataset_id, column_variable="region")
    assert sorted(table["column_labels"]) == ["North", "South"]
    assert table["row_labels"] == ["Count"]
    assert len(table["values"]) == 1
    assert table["values"][0] == table["column_totals"]


def test_the_two_orientations_agree(client, auth_headers, dataset_id):
    """The same question asked down the page and across it."""
    down = crosstab(client, auth_headers, dataset_id, row_variable="region")
    across = crosstab(client, auth_headers, dataset_id, column_variable="region")
    assert dict(zip(down["row_labels"], down["row_totals"], strict=False)) == dict(
        zip(across["column_labels"], across["column_totals"], strict=False)
    )
    assert down["grand_total"] == across["grand_total"]


def test_both_variables_still_cross_tabulate(client, auth_headers, dataset_id):
    """The two-way table is untouched."""
    table = crosstab(
        client, auth_headers, dataset_id, row_variable="region", column_variable="sex"
    )
    assert len(table["row_labels"]) == 2
    assert len(table["column_labels"]) == 2
    assert len(table["values"]) == 2
    assert len(table["values"][0]) == 2


def test_percentages_on_a_one_way_table_are_shares_of_the_total(
    client, auth_headers, dataset_id
):
    """Asking for "% of row" on a table one column wide would print 100% down it.

    A one-way table has a single meaningful denominator, so every percentage
    basis collapses to the total.
    """
    for basis in ("row", "column", "total"):
        table = crosstab(
            client,
            auth_headers,
            dataset_id,
            row_variable="region",
            percentages=basis,
        )
        shares = [row[0] for row in table["values"]]
        assert all(share is not None for share in shares)
        assert sum(shares) == pytest.approx(100.0, abs=0.05), basis


def test_no_variable_at_all_is_refused(client, auth_headers, dataset_id):
    response = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab",
        headers=auth_headers,
        json={"measure": {"agg": "count"}},
    )
    assert response.status_code == 422


def test_chi_square_is_absent_from_a_one_way_table(client, auth_headers, dataset_id):
    """There is no independence to test between a variable and nothing."""
    one_way = crosstab(client, auth_headers, dataset_id, row_variable="region")
    assert one_way["chi_square"] is None

    two_way = crosstab(
        client, auth_headers, dataset_id, row_variable="region", column_variable="sex"
    )
    assert two_way["chi_square"] is not None


def test_a_measure_other_than_count_names_the_column(
    client, auth_headers, dataset_id
):
    table = crosstab(
        client,
        auth_headers,
        dataset_id,
        row_variable="region",
        measure={"agg": "mean", "variable": "age"},
    )
    assert table["column_labels"] == ["mean of age"]
