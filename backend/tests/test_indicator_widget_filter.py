"""An indicator tile has to answer the question the page is asking.

A tile reports the value the last scheduled evaluation stored, which is right
when the dashboard shows everything: opening a board should not set a query
going for every tile on it. But a filtered page is asking about a subset that
no run ever counted, and a tile that goes on showing the whole survey next to
charts that have narrowed to one province is reporting a number for rows the
reader is not looking at.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.test_api_analytics import _stata_bytes, _zip_bytes


@pytest.fixture
def surveyed(client, auth_headers, request) -> dict:
    """Ten interviews, unevenly completed, in two provinces.

    Shefa has 6 rows of which 3 are complete; Sanma has 4 of which 1 is. So the
    count, the completion rate and the breakdown all differ between the two
    provinces and from the whole - which is what makes a filter visible rather
    than merely plausible.
    """
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(10)],
            "province": ["Shefa"] * 6 + ["Sanma"] * 4,
            "status": ["done", "done", "done", "open", "open", "open",
                       "done", "open", "open", "open"],
        }
    )
    # Named after the test: uploading the same name twice replaces the dataset,
    # so a shared name would have the tests treading on each other.
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
    return {
        "dataset_id": uploaded["datasets"][0]["id"],
        "board": client.post(
            "/api/v1/dashboards", headers=auth_headers, json={"name": "Indicator board"}
        ).json()["id"],
    }


def make_indicator(client, auth_headers, dataset_id: str, **extra) -> dict:
    body = {
        "name": "Interviews",
        "dataset_id": dataset_id,
        "spec": {"measures": [{"agg": "count", "alias": "n"}]},
        **extra,
    }
    response = client.post("/api/v1/monitoring/indicators", headers=auth_headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def place_tile(client, auth_headers, board: str, indicator_id: str, config: dict | None = None):
    response = client.post(
        f"/api/v1/dashboards/{board}/widgets",
        headers=auth_headers,
        json={
            "title": "Interviews",
            "widget_type": "indicator",
            "indicator_id": indicator_id,
            "config": config or {},
        },
    )
    assert response.status_code == 201, response.text


def render(client, auth_headers, board: str, filters: dict | None = None) -> dict:
    response = client.post(
        f"/api/v1/dashboards/{board}/data", headers=auth_headers, json=filters or {}
    )
    assert response.status_code == 200, response.text
    return next(
        w for w in response.json()["widgets"].values() if w.get("type") == "indicator"
    )


def only(province: str) -> dict:
    return {
        "op": "and",
        "conditions": [{"variable": "province", "operator": "eq", "value": province}],
        "groups": [],
    }


def test_unfiltered_it_still_reports_the_stored_value(client, auth_headers, surveyed):
    """The cheap path stays cheap: no filter, no query, and a timestamp."""
    indicator = make_indicator(client, auth_headers, surveyed["dataset_id"])
    place_tile(client, auth_headers, surveyed["board"], indicator["id"])

    tile = render(client, auth_headers, surveyed["board"])
    assert tile["filtered"] is False
    assert tile["value"] == 10
    # It came from a stored evaluation, so it can say when.
    assert tile["computed_at"]


def test_a_filter_narrows_what_the_tile_counts(client, auth_headers, surveyed):
    indicator = make_indicator(client, auth_headers, surveyed["dataset_id"])
    place_tile(client, auth_headers, surveyed["board"], indicator["id"])

    shefa = render(client, auth_headers, surveyed["board"], only("Shefa"))
    assert shefa["filtered"] is True
    assert shefa["value"] == 6

    sanma = render(client, auth_headers, surveyed["board"], only("Sanma"))
    assert sanma["value"] == 4


def test_progress_against_the_target_follows_the_filter(client, auth_headers, surveyed):
    """The tile's bar is what people read, so it has to move with the number."""
    indicator = make_indicator(
        client, auth_headers, surveyed["dataset_id"], target_value=10.0
    )
    place_tile(client, auth_headers, surveyed["board"], indicator["id"])

    tile = render(client, auth_headers, surveyed["board"], only("Shefa"))
    assert tile["value"] == 6
    assert tile["progress_percent"] == pytest.approx(60.0)


def test_a_percentage_is_a_share_of_the_filtered_rows(client, auth_headers, surveyed):
    """Both halves of the fraction narrow, or the rate is not a rate.

    3 of Shefa's 6 interviews are complete and 1 of Sanma's 4, against 4 of 10
    overall. Narrowing only the numerator would report Shefa as 30% - its three
    completions over everybody's ten - which is not a completion rate for
    anywhere.
    """
    indicator = make_indicator(
        client,
        auth_headers,
        surveyed["dataset_id"],
        name="Completion rate",
        spec={
            "measures": [{"agg": "count", "alias": "n"}],
            "filters": {
                "op": "and",
                "conditions": [{"variable": "status", "operator": "eq", "value": "done"}],
                "groups": [],
            },
        },
        percent_of="all_rows",
    )
    place_tile(client, auth_headers, surveyed["board"], indicator["id"])

    assert render(client, auth_headers, surveyed["board"])["value"] == pytest.approx(40.0)
    assert render(client, auth_headers, surveyed["board"], only("Shefa"))["value"] == (
        pytest.approx(50.0)
    )
    assert render(client, auth_headers, surveyed["board"], only("Sanma"))["value"] == (
        pytest.approx(25.0)
    )


def test_the_breakdown_is_counted_over_the_filtered_rows_too(
    client, auth_headers, surveyed
):
    """Headline and breakdown have to add up, filtered as much as unfiltered."""
    indicator = make_indicator(
        client, auth_headers, surveyed["dataset_id"], breakdown_variable="status"
    )
    place_tile(
        client, auth_headers, surveyed["board"], indicator["id"], {"show_breakdown": True}
    )

    tile = render(client, auth_headers, surveyed["board"], only("Shefa"))
    assert tile["breakdown"] == {"done": 3, "open": 3}
    assert sum(tile["breakdown"].values()) == tile["value"] == 6


def test_a_tile_without_a_breakdown_is_not_given_one(client, auth_headers, surveyed):
    """Filtering recomputes the tile; it does not change what the tile shows."""
    indicator = make_indicator(
        client, auth_headers, surveyed["dataset_id"], breakdown_variable="status"
    )
    place_tile(client, auth_headers, surveyed["board"], indicator["id"])

    tile = render(client, auth_headers, surveyed["board"], only("Shefa"))
    assert tile["value"] == 6
    assert tile["breakdown"] == {}
    assert tile["breakdown_variable"] == ""


def test_a_filter_on_a_variable_the_dataset_lacks_is_reported_not_applied(
    client, auth_headers, surveyed
):
    """The same courtesy every other widget gets: say so rather than go blank."""
    indicator = make_indicator(client, auth_headers, surveyed["dataset_id"])
    place_tile(client, auth_headers, surveyed["board"], indicator["id"])

    tile = render(
        client,
        auth_headers,
        surveyed["board"],
        {
            "op": "and",
            "conditions": [{"variable": "not_here", "operator": "eq", "value": "x"}],
            "groups": [],
        },
    )
    assert tile["filters_ignored"] == ["not_here"]
    # Nothing could be narrowed, so the stored value is what it reports.
    assert tile["filtered"] is False
    assert tile["value"] == 10
