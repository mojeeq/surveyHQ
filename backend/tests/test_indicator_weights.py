"""An indicator measured with the survey weight.

Explore and the cross-tabulation could be weighted; an indicator could not, so
a published headline - a weighted unemployment rate, an estimated number of
households - could not be tracked, targeted or put on a board except by
building it in a script first. These cover the weighted measure, a weighted
share whose bottom half is weighted too, a formula whose parts all are, and the
exported page rebuilding a weighted mean for whatever filter its reader picks.

The weights are chosen so every weighted answer differs from its unweighted
one: a figure that came out the same either way would prove nothing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.schemas.query import Aggregation, Measure
from app.services.static_export import _recipe
from tests.test_api_analytics import _stata_bytes, _zip_bytes
from tests.test_indicator_formulas import counting, make, value_of, where

# Northern: households 0-3, each standing for 10. Highland: 4-5, each for 40.
WEIGHTS = [10.0, 10.0, 10.0, 10.0, 40.0, 40.0]


@pytest.fixture
def weighted_survey(client, auth_headers, request) -> dict:
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(6)],
            "province": ["Northern"] * 4 + ["Highland"] * 2,
            "status": ["done", "open", "open", "open", "done", "open"],
            # Income missing for one Highland household: "of those who
            # answered" has to leave its weight out of the bottom half.
            "income": [100.0, 200.0, 300.0, 400.0, 1000.0, None],
            "wt": WEIGHTS,
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
    return {"dataset_id": uploaded["datasets"][0]["id"]}


def measured(agg: str, variable: str | None = None, weight: str | None = "wt") -> dict:
    return {"measures": [{"agg": agg, "variable": variable, "alias": "value", "weight": weight}]}


def test_a_weighted_count_estimates_the_population(client, auth_headers, weighted_survey):
    indicator = make(client, auth_headers, weighted_survey["dataset_id"], spec=measured("count"))
    # 4 x 10 + 2 x 40, where the unweighted count is 6.
    assert value_of(client, auth_headers, indicator["id"])["value"] == pytest.approx(120.0)


def test_a_weighted_mean(client, auth_headers, weighted_survey):
    indicator = make(
        client, auth_headers, weighted_survey["dataset_id"], spec=measured("mean", "income")
    )
    # (100+200+300+400) x 10 + 1000 x 40, over the weight of the five that
    # answered: 50000 / 80 = 625. Unweighted it is 400.
    assert value_of(client, auth_headers, indicator["id"])["value"] == pytest.approx(625.0)


def test_a_weighted_share_is_weighted_on_both_halves(client, auth_headers, weighted_survey):
    spec = measured("count")
    spec["filters"] = where("status", "done")
    indicator = make(
        client, auth_headers, weighted_survey["dataset_id"], spec=spec,
        percent_of="all_rows", breakdown_variable="province",
    )
    value = value_of(client, auth_headers, indicator["id"])
    # Done: one Northern household and one Highland one, 10 + 40 of 120. Two
    # of six unweighted would be 33.3%; a weighted top over an unweighted
    # bottom would be 50 of 6, over 800%.
    assert value["value"] == pytest.approx(41.6667, abs=0.01)
    # Each province against its own weight: 10 of 40, 40 of 80.
    assert value["breakdown"] == {
        "Northern": pytest.approx(25.0),
        "Highland": pytest.approx(50.0),
    }


def test_a_weighted_share_of_those_who_answered(client, auth_headers, weighted_survey):
    """Counted as "answered income", the top half is the weight of the rows
    with an income and the bottom half is the same rows - 100%. Before the
    weighted count of a variable left out the rows that did not answer, the
    top half was the weight of every row, and this came out at 150%."""
    indicator = make(
        client, auth_headers, weighted_survey["dataset_id"],
        spec=measured("count", "income"), percent_of="answered",
    )
    assert value_of(client, auth_headers, indicator["id"])["value"] == pytest.approx(100.0)


def test_a_weighted_count_of_a_variable_leaves_out_those_who_did_not_answer(
    client, auth_headers, weighted_survey
):
    indicator = make(
        client, auth_headers, weighted_survey["dataset_id"], spec=measured("count", "income")
    )
    # Everyone but the Highland household with no income: 120 - 40.
    assert value_of(client, auth_headers, indicator["id"])["value"] == pytest.approx(80.0)


def test_a_formula_whose_parts_are_all_weighted(client, auth_headers, weighted_survey):
    done = counting("done", where("status", "done"))
    issued = counting("issued")
    for part in (done, issued):
        part["measure"]["weight"] = "wt"
    indicator = make(
        client, auth_headers, weighted_survey["dataset_id"],
        formula={"expression": "done / issued * 100", "parts": [done, issued]},
        breakdown_variable="province",
    )
    value = value_of(client, auth_headers, indicator["id"])
    assert value["value"] == pytest.approx(41.6667, abs=0.01)
    assert value["breakdown"]["Highland"] == pytest.approx(50.0)


def test_a_formula_cannot_mix_weighted_and_unweighted_parts(
    client, auth_headers, weighted_survey
):
    done = counting("done", where("status", "done"))
    done["measure"]["weight"] = "wt"
    response = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Mixed",
            "dataset_id": weighted_survey["dataset_id"],
            "spec": {"measures": [{"agg": "count", "alias": "value"}]},
            "formula": {"expression": "done / issued", "parts": [done, counting("issued")]},
        },
    )
    assert response.status_code == 422
    assert "weighted the same way" in response.text


def test_a_weight_is_refused_on_a_median(client, auth_headers, weighted_survey):
    response = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Median income",
            "dataset_id": weighted_survey["dataset_id"],
            "spec": measured("median", "income"),
        },
    )
    assert response.status_code == 422
    assert "not supported for median" in response.text


def test_the_exported_page_can_rebuild_a_weighted_mean():
    """It used to refuse one. The weighted total and the weight of the rows
    that answered are two sums like any others, and their ratio is the
    weighted mean for whichever groups the reader filters to."""
    asked, recipes = _recipe([Measure(agg=Aggregation.mean, variable="income", weight="wt")])
    assert [(one.agg, one.weight) for one in asked] == [
        (Aggregation.sum, "wt"),
        (Aggregation.count, "wt"),
    ]
    assert recipes[0]["how"] == "mean"
