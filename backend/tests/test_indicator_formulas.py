"""An indicator defined as arithmetic over named parts.

One aggregate and a switch saying "as a share of every row" answers "how many"
and "what share of everything". A survey office's real indicators are mostly
ratios between two different counts - refusals per completed interview, the
share among those who answered one question rather than among every row, the
gap between households visited and households interviewed - and none of those
can be written that way. So an indicator can be parts and a sum over them.

These cover the whole path: that the parts are counted separately with their
own filters, that the breakdown is the same sum asked of each group, that a
group where the bottom of the fraction is nought reports nothing rather than
an infinity, and that a page filter narrows every part alike so a filtered
rate is still a rate.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.test_api_analytics import _stata_bytes, _zip_bytes
from tests.test_indicator_widget_filter import place_tile, render


@pytest.fixture
def fieldwork(client, auth_headers, request) -> dict:
    """Ten interviews in two provinces, unevenly complete, two refused.

    Shefa: 6 issued, 3 done, 1 refused. Sanma: 4 issued, 1 done, 1 refused.
    So every rate differs between the provinces and from the whole, which is
    what makes a wrong denominator visible rather than merely possible.
    """
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(10)],
            "province": ["Shefa"] * 6 + ["Sanma"] * 4,
            "status": ["done", "done", "done", "open", "refused", "open",
                       "done", "refused", "open", "open"],
            "visits": [2, 1, 3, 1, 1, 2, 4, 1, 1, 1],
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


def where(variable: str, value: str) -> dict:
    return {
        "op": "and",
        "conditions": [{"variable": variable, "operator": "eq", "value": value}],
        "groups": [],
    }


def counting(name: str, filters: dict | None = None) -> dict:
    return {
        "name": name,
        "measure": {"agg": "count", "variable": None},
        "filters": filters or {"op": "and", "conditions": [], "groups": []},
    }


def make(client, auth_headers, dataset_id: str, **extra) -> dict:
    body = {
        "name": "Completion rate",
        "dataset_id": dataset_id,
        "spec": {"measures": [{"agg": "count", "alias": "value"}]},
        **extra,
    }
    response = client.post("/api/v1/monitoring/indicators", headers=auth_headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def value_of(client, auth_headers, indicator_id: str) -> dict:
    values = client.get(
        "/api/v1/monitoring/indicators/values?refresh=true", headers=auth_headers
    ).json()
    return next(one for one in values if one["indicator_id"] == indicator_id)


RATE = {
    "expression": "done / issued * 100",
    "parts": [counting("done", where("status", "done")), counting("issued")],
}


def test_a_rate_is_counted_from_its_own_two_parts(client, auth_headers, fieldwork):
    indicator = make(client, auth_headers, fieldwork["dataset_id"], formula=RATE)

    assert value_of(client, auth_headers, indicator["id"])["value"] == pytest.approx(40.0)


def test_the_breakdown_asks_the_same_sum_of_each_group(client, auth_headers, fieldwork):
    """Each province against its own issued count, not against the national
    one: Shefa is 3 of its own 6, which is 50%, not 3 of 10."""
    indicator = make(
        client,
        auth_headers,
        fieldwork["dataset_id"],
        formula=RATE,
        breakdown_variable="province",
    )

    reported = value_of(client, auth_headers, indicator["id"])["breakdown"]
    assert reported == {"Shefa": pytest.approx(50.0), "Sanma": pytest.approx(25.0)}


def test_a_part_that_matched_nothing_in_a_group_is_nought_rather_than_missing(
    client, auth_headers, fieldwork
):
    """No refusal in a province is nought refusals, which is a real rate. A
    group dropped instead would read as "no data from there"."""
    indicator = make(
        client,
        auth_headers,
        fieldwork["dataset_id"],
        formula={
            "expression": "refused / issued * 100",
            "parts": [counting("refused", where("status", "refused")), counting("issued")],
        },
        breakdown_variable="province",
    )

    reported = value_of(client, auth_headers, indicator["id"])["breakdown"]
    # Rounded to four places on the way out: a breakdown is up to five
    # thousand groups, and nobody reads the ninth decimal of a percentage.
    assert reported["Shefa"] == pytest.approx(16.6667)
    assert reported["Sanma"] == pytest.approx(25.0)


def test_nothing_on_the_bottom_of_the_fraction_is_no_value_at_all(
    client, auth_headers, fieldwork
):
    """A rate whose denominator counts nothing cannot be reported. Nought
    would be a claim about work that was never issued."""
    indicator = make(
        client,
        auth_headers,
        fieldwork["dataset_id"],
        formula={
            "expression": "done / verified * 100",
            "parts": [
                counting("done", where("status", "done")),
                counting("verified", where("status", "verified")),
            ],
        },
    )

    assert value_of(client, auth_headers, indicator["id"])["value"] is None


def test_a_part_can_total_a_variable_rather_than_count_rows(
    client, auth_headers, fieldwork
):
    """Visits per interview: 17 visits over 10 interviews."""
    indicator = make(
        client,
        auth_headers,
        fieldwork["dataset_id"],
        formula={
            "expression": "visits / interviews",
            "parts": [
                {
                    "name": "visits",
                    "measure": {"agg": "sum", "variable": "visits"},
                    "filters": {"op": "and", "conditions": [], "groups": []},
                },
                counting("interviews"),
            ],
        },
    )

    assert value_of(client, auth_headers, indicator["id"])["value"] == pytest.approx(1.7)


def test_the_single_measure_is_not_consulted_when_a_formula_is_set(
    client, auth_headers, fieldwork
):
    """The formula is the definition, not an adjustment to one. A leftover
    spec from before it was written must not leak into the number."""
    indicator = make(
        client,
        auth_headers,
        fieldwork["dataset_id"],
        spec={
            "measures": [{"agg": "count", "alias": "value"}],
            "filters": where("province", "Sanma"),
        },
        percent_of="all_rows",
        formula=RATE,
    )

    assert value_of(client, auth_headers, indicator["id"])["value"] == pytest.approx(40.0)


def test_a_formula_is_kept_and_can_be_taken_away_again(client, auth_headers, fieldwork):
    indicator = make(client, auth_headers, fieldwork["dataset_id"], formula=RATE)
    assert indicator["formula"]["expression"] == "done / issued * 100"

    cleared = client.patch(
        f"/api/v1/monitoring/indicators/{indicator['id']}",
        headers=auth_headers,
        json={"formula": {"expression": "", "parts": []}},
    )

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["formula"] == {}
    # Back to its own single measure: ten rows, counted.
    assert value_of(client, auth_headers, indicator["id"])["value"] == pytest.approx(10.0)


def test_an_indicator_without_a_formula_is_unaffected(client, auth_headers, fieldwork):
    indicator = make(client, auth_headers, fieldwork["dataset_id"])

    assert indicator["formula"] == {}
    assert value_of(client, auth_headers, indicator["id"])["value"] == pytest.approx(10.0)


@pytest.mark.parametrize(
    ("formula", "says"),
    [
        ({"expression": "done / issued", "parts": [counting("done")]}, "not one of its parts"),
        ({"expression": "done /", "parts": [counting("done")]}, "stops in the middle"),
        ({"expression": "done", "parts": []}, "at least one part"),
        (
            {"expression": "done", "parts": [counting("done"), counting("done")]},
            "both called",
        ),
    ],
)
def test_a_formula_that_does_not_add_up_is_refused_on_the_way_in(
    client, auth_headers, fieldwork, formula: dict, says: str
):
    """Refused when it is written, not reported as a broken tile later."""
    response = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Bad",
            "dataset_id": fieldwork["dataset_id"],
            "spec": {"measures": [{"agg": "count", "alias": "value"}]},
            "formula": formula,
        },
    )

    assert response.status_code == 422, response.text
    assert says in response.text


def test_a_page_filter_narrows_every_part_alike(client, auth_headers, fieldwork):
    """A filtered rate has to stay a rate. Narrowing only the top of the
    fraction would turn "half of Shefa is done" into "Shefa holds three
    tenths of the country's completed work", which is a different question
    and is already answered by a share-of-total chart."""
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Fieldwork"}
    ).json()["id"]
    indicator = make(client, auth_headers, fieldwork["dataset_id"], formula=RATE)
    place_tile(client, auth_headers, board, indicator["id"])

    whole = render(client, auth_headers, board)
    shefa = render(client, auth_headers, board, where("province", "Shefa"))

    assert whole["value"] == pytest.approx(40.0)
    assert shefa["filtered"] is True
    assert shefa["value"] == pytest.approx(50.0)


def preview(client, auth_headers, dataset_id: str, formula: dict) -> dict:
    response = client.post(
        "/api/v1/monitoring/formula-preview",
        headers=auth_headers,
        json={"dataset_id": dataset_id, "formula": formula},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_formula_can_be_tried_before_it_is_saved(client, auth_headers, fieldwork):
    answer = preview(client, auth_headers, fieldwork["dataset_id"], RATE)

    assert answer["value"] == pytest.approx(40.0)
    # The parts beside the answer: which half of the fraction is wrong is the
    # question somebody staring at a blank tile is actually asking.
    assert answer["parts"] == {"done": 4.0, "issued": 10.0}
    assert answer["error"] is None


def test_a_preview_names_the_half_that_counts_nothing(client, auth_headers, fieldwork):
    answer = preview(
        client,
        auth_headers,
        fieldwork["dataset_id"],
        {
            "expression": "done / verified",
            "parts": [
                counting("done", where("status", "done")),
                counting("verified", where("status", "verified")),
            ],
        },
    )

    assert answer["value"] is None
    assert answer["parts"] == {"done": 4.0, "verified": 0.0}


def test_a_preview_of_a_formula_naming_a_variable_that_is_not_there_says_so(
    client, auth_headers, fieldwork
):
    answer = preview(
        client,
        auth_headers,
        fieldwork["dataset_id"],
        {
            "expression": "done / issued",
            "parts": [counting("done", where("outcome", "done")), counting("issued")],
        },
    )

    assert answer["value"] is None
    assert answer["error"]
