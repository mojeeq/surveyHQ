"""Tabulating a variable with a category per interview.

The platform offers this on purpose: a table of 5,000 rows is how somebody
reads a whole listing and exports it, and the README says so. It was
quadratic. Collecting the keys of the result tested membership against a
list of everything seen so far, which costs nothing for twelve education
levels and everything for two hundred thousand interview keys - measured at
50.5 seconds through the API, against under a tenth of a second in DuckDB.

The bound below is deliberately loose. It is there to catch a return to
quadratic, which on this many keys is tens of seconds, not to measure a
machine: the fixed version answers in a fraction of a second on the slowest
runner this has been near.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

ROWS = 40_000
# Measured here: 8.0s the old way against 0.26s for the single pass that
# replaced it. The bound sits between the two rather than against either, so
# a slow runner has fifteen times the headroom it needs and the quadratic
# shape is twice over the line.
SECONDS = 4.0


@pytest.fixture(scope="module")
def listing(client, auth_headers) -> str:
    """One row per interview, and a column to cross it with."""
    frame = pd.DataFrame(
        {
            "interview__key": [f"k-{index:06d}" for index in range(ROWS)],
            "province": [["Shefa", "Sanma", "Malampa"][index % 3] for index in range(ROWS)],
        }
    )
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[("file", ("listing.csv", frame.to_csv(index=False), "text/csv"))],
        data={"name": "Listing"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return (body["datasets"][0] if "datasets" in body else body)["id"]


def test_a_table_with_a_category_per_interview_comes_back_quickly(
    client, auth_headers, listing
):
    started = time.perf_counter()
    response = client.post(
        f"/api/v1/analytics/datasets/{listing}/crosstab",
        headers=auth_headers,
        json={"row_variable": "interview__key", "column_variable": "province"},
    )
    took = time.perf_counter() - started
    assert response.status_code == 200, response.text
    table = response.json()
    # Every interview is a row, and the table says what it had to leave out.
    assert len(table["row_labels"]) == min(ROWS, 5000)
    assert table["column_labels"] == ["Malampa", "Sanma", "Shefa"]
    assert took < SECONDS, f"the table took {took:.1f}s, which is the quadratic shape"


def test_the_rows_are_the_interviews_they_say_they_are(client, auth_headers, listing):
    """Order and content, so the speed is not bought with the wrong answer."""
    response = client.post(
        f"/api/v1/analytics/datasets/{listing}/crosstab",
        headers=auth_headers,
        json={"row_variable": "interview__key", "column_variable": "province"},
    )
    table = response.json()
    assert table["row_labels"][:3] == ["k-000000", "k-000001", "k-000002"]
    # k-000000 is in Shefa, and in no other province - where a cell is blank
    # rather than zero, because no record is not the same as none counted.
    first = dict(zip(table["column_labels"], table["values"][0], strict=True))
    assert first["Shefa"] == 1
    assert not first["Sanma"] and not first["Malampa"]
