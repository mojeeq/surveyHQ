"""What a KPI tile has to say beyond the number itself.

"467 interviews" answers nothing on its own. "467, 63 ahead of target, rising"
is a management number: it carries the comparison and the direction, so the
reader is not left doing arithmetic against a target printed underneath.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from app.db.session import SessionLocal
from app.models import IndicatorSnapshot
from tests.test_api_analytics import _stata_bytes, _zip_bytes


@pytest.fixture
def surveyed(client, auth_headers, request) -> dict:
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(10)],
            "province": ["Shefa"] * 6 + ["Sanma"] * 4,
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
    return {
        "dataset_id": uploaded["datasets"][0]["id"],
        "board": client.post(
            "/api/v1/dashboards", headers=auth_headers, json={"name": "KPI board"}
        ).json()["id"],
    }


def make_indicator(client, auth_headers, dataset_id: str, **extra) -> dict:
    response = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Interviews",
            "dataset_id": dataset_id,
            "spec": {"measures": [{"agg": "count", "alias": "n"}]},
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def place_tile(client, auth_headers, board: str, indicator_id: str, config: dict) -> None:
    response = client.post(
        f"/api/v1/dashboards/{board}/widgets",
        headers=auth_headers,
        json={
            "title": "Interviews",
            "widget_type": "indicator",
            "indicator_id": indicator_id,
            "config": config,
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


def seed_history(indicator_id: str, values: list[float]) -> None:
    """Daily snapshots ending yesterday, oldest first."""
    with SessionLocal() as session:
        start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=len(values))
        for offset, value in enumerate(values):
            session.add(
                IndicatorSnapshot(
                    indicator_id=indicator_id,
                    value=value,
                    breakdown={},
                    computed_at=start + dt.timedelta(days=offset),
                )
            )
        session.commit()


def test_the_tile_says_how_far_off_target_it_is(client, auth_headers, surveyed):
    indicator = make_indicator(
        client, auth_headers, surveyed["dataset_id"], target_value=8.0
    )
    place_tile(client, auth_headers, surveyed["board"], indicator["id"], {})

    tile = render(client, auth_headers, surveyed["board"])
    assert tile["value"] == 10
    assert tile["variance"] == pytest.approx(2.0)
    assert tile["variance_percent"] == pytest.approx(25.0)


def test_being_behind_reads_as_a_negative_gap(client, auth_headers, surveyed):
    indicator = make_indicator(
        client, auth_headers, surveyed["dataset_id"], target_value=25.0
    )
    place_tile(client, auth_headers, surveyed["board"], indicator["id"], {})

    tile = render(client, auth_headers, surveyed["board"])
    assert tile["variance"] == pytest.approx(-15.0)
    assert tile["variance_percent"] == pytest.approx(-60.0)


def test_with_no_target_there_is_no_gap_to_report(client, auth_headers, surveyed):
    indicator = make_indicator(client, auth_headers, surveyed["dataset_id"])
    place_tile(client, auth_headers, surveyed["board"], indicator["id"], {})

    tile = render(client, auth_headers, surveyed["board"])
    assert tile["variance"] is None
    assert tile["variance_percent"] is None


def test_the_variance_follows_the_filter(client, auth_headers, surveyed):
    """The gap belongs to the number above it, not to the whole survey."""
    indicator = make_indicator(
        client, auth_headers, surveyed["dataset_id"], target_value=8.0
    )
    place_tile(client, auth_headers, surveyed["board"], indicator["id"], {})

    tile = render(
        client,
        auth_headers,
        surveyed["board"],
        {
            "op": "and",
            "conditions": [
                {"variable": "province", "operator": "eq", "value": "Shefa"}
            ],
            "groups": [],
        },
    )
    assert tile["value"] == 6
    assert tile["variance"] == pytest.approx(-2.0)


def test_the_sparkline_is_the_stored_runs_oldest_first(client, auth_headers, surveyed):
    indicator = make_indicator(client, auth_headers, surveyed["dataset_id"])
    seed_history(indicator["id"], [2.0, 5.0, 9.0])
    place_tile(
        client, auth_headers, surveyed["board"], indicator["id"], {"show_trend": True}
    )

    tile = render(client, auth_headers, surveyed["board"])
    # The seeded history, then the run that creating the indicator did, which
    # is the value the tile is showing. Oldest first, so the line reads left to
    # right the way a date axis does.
    assert [point["value"] for point in tile["trend"]] == [2.0, 5.0, 9.0, 10.0]
    ats = [point["at"] for point in tile["trend"]]
    assert ats == sorted(ats)


def test_a_tile_that_did_not_ask_gets_no_history(client, auth_headers, surveyed):
    """Reading a month of runs for every tile on a board is work thrown away."""
    indicator = make_indicator(client, auth_headers, surveyed["dataset_id"])
    seed_history(indicator["id"], [2.0, 5.0, 9.0])
    place_tile(client, auth_headers, surveyed["board"], indicator["id"], {})

    assert render(client, auth_headers, surveyed["board"])["trend"] == []


def test_a_filtered_tile_draws_no_sparkline(client, auth_headers, surveyed):
    """The stored runs counted the whole dataset; the number above them did not."""
    indicator = make_indicator(client, auth_headers, surveyed["dataset_id"])
    seed_history(indicator["id"], [2.0, 5.0, 9.0])
    place_tile(
        client, auth_headers, surveyed["board"], indicator["id"], {"show_trend": True}
    )

    tile = render(
        client,
        auth_headers,
        surveyed["board"],
        {
            "op": "and",
            "conditions": [
                {"variable": "province", "operator": "eq", "value": "Shefa"}
            ],
            "groups": [],
        },
    )
    assert tile["filtered"] is True
    assert tile["trend"] == []
