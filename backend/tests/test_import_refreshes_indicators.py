"""An import has to move the numbers it was imported to move.

An indicator tile on a dashboard shows the value the last scheduled evaluation
stored, rather than querying the data as a chart does, because opening a board
must not set a query going for every tile on it. The consequence nobody wanted:
a fresh export landed, the charts moved, and every tile went on showing
yesterday's figure until the quarter-hour monitoring tick came round. From the
outside that is an import that did nothing.

So whatever route data arrives on, the indicators reading that dataset are
recomputed as part of it.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.models import IndicatorSnapshot
from tests.test_api_analytics import _stata_bytes, _zip_bytes


def _frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(rows)],
            "province": ["Northern" if i % 2 else "Highland" for i in range(rows)],
        }
    )


@pytest.fixture
def survey(client, auth_headers, request) -> dict:
    """Two interviews in a dataset of this test's own, plus a board and a tile."""
    name = request.node.name[:40]
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                f"{name}.zip",
                _zip_bytes({f"{name}.dta": _stata_bytes(_frame(2))}),
                "application/zip",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    dataset_id = uploaded.json()["datasets"][0]["id"]
    indicator = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Interviews",
            "dataset_id": dataset_id,
            "spec": {"measures": [{"agg": "count", "alias": "n"}]},
        },
    )
    assert indicator.status_code == 201, indicator.text
    assert indicator.json()["last_value"] == 2
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": f"Board {name}"}
    ).json()
    tile = client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Interviews",
            "widget_type": "indicator",
            "indicator_id": indicator.json()["id"],
        },
    )
    assert tile.status_code == 201, tile.text
    return {
        "name": name,
        "dataset_id": dataset_id,
        "indicator_id": indicator.json()["id"],
        "board": board["id"],
    }


def _import(client, auth_headers, survey: dict, rows: int):
    """A later export of the same questionnaire, which replaces the data."""
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                f"{survey['name']}.zip",
                _zip_bytes({f"{survey['name']}.dta": _stata_bytes(_frame(rows))}),
                "application/zip",
            )
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["datasets"][0]["id"] == survey["dataset_id"], "replaced, not created beside"
    assert body["datasets"][0]["row_count"] == rows
    return body


def _tile(client, auth_headers, board: str) -> dict:
    response = client.post(f"/api/v1/dashboards/{board}/data", headers=auth_headers, json={})
    assert response.status_code == 200, response.text
    return next(w for w in response.json()["widgets"].values() if w.get("type") == "indicator")


def test_the_tile_shows_the_new_number_without_waiting_for_the_tick(
    client, auth_headers, survey
):
    assert _tile(client, auth_headers, survey["board"])["value"] == 2

    _import(client, auth_headers, survey, 6)

    # No refresh called, no tick run: this is what the dashboard shows the
    # moment the import finishes.
    assert _tile(client, auth_headers, survey["board"])["value"] == 6
    # And the monitoring page, which reads the same stored value.
    values = client.get("/api/v1/monitoring/indicators/values", headers=auth_headers)
    assert values.status_code == 200, values.text
    mine = next(
        one for one in values.json() if one["indicator_id"] == survey["indicator_id"]
    )
    assert mine["value"] == 6


def test_the_import_leaves_the_trend_to_the_schedule(client, auth_headers, survey, db_session):
    """The snapshots are a record of the number at each scheduled moment.

    Five questionnaire versions importing one after another would otherwise
    punch five points into the trend inside a minute, four of them describing a
    dataset half way through being written.
    """
    def snapshots() -> int:
        return db_session.scalar(
            select(func.count())
            .select_from(IndicatorSnapshot)
            .where(IndicatorSnapshot.indicator_id == survey["indicator_id"])
        )

    before = snapshots()
    _import(client, auth_headers, survey, 8)
    assert snapshots() == before
    assert _tile(client, auth_headers, survey["board"])["value"] == 8


def test_an_indicator_that_cannot_be_computed_does_not_fail_the_import(
    client, auth_headers, survey
):
    """An expression somebody mistyped is not a reason to refuse the data."""
    broken = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Mean of a variable that is not there",
            "dataset_id": survey["dataset_id"],
            "spec": {"measures": [{"agg": "mean", "variable": "no_such_column"}]},
        },
    )
    assert broken.status_code == 201, broken.text

    _import(client, auth_headers, survey, 4)

    assert _tile(client, auth_headers, survey["board"])["value"] == 4


def test_only_the_indicators_on_the_dataset_that_changed_are_recomputed(
    client, auth_headers, survey, request, db_session
):
    """An import is not a reason to re-query every dataset in the instance.

    One census import would otherwise set a query going for every indicator
    anybody has ever defined, on datasets it did not touch.
    """
    from app.models import Indicator

    other = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                f"{survey['name']}-other.zip",
                _zip_bytes({f"{survey['name']}-other.dta": _stata_bytes(_frame(3))}),
                "application/zip",
            )
        },
    )
    assert other.status_code == 201, other.text
    elsewhere = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Interviews elsewhere",
            "dataset_id": other.json()["datasets"][0]["id"],
            "spec": {"measures": [{"agg": "count", "alias": "n"}]},
        },
    )
    assert elsewhere.status_code == 201, elsewhere.text
    untouched = db_session.get(Indicator, elsewhere.json()["id"])
    db_session.refresh(untouched)
    was = untouched.last_computed_at

    _import(client, auth_headers, survey, 5)

    db_session.expire_all()
    assert db_session.get(Indicator, elsewhere.json()["id"]).last_computed_at == was
    assert _tile(client, auth_headers, survey["board"])["value"] == 5


def test_an_indicator_somebody_switched_off_stays_off(client, auth_headers, survey, db_session):
    """Inactive is inactive: the scheduled run skips it and so does this."""
    from app.models import Indicator

    switched_off = db_session.get(Indicator, survey["indicator_id"])
    switched_off.is_active = False
    db_session.commit()

    _import(client, auth_headers, survey, 7)

    db_session.expire_all()
    assert db_session.get(Indicator, survey["indicator_id"]).last_value == 2


def test_an_indicator_that_blows_up_does_not_take_the_import_with_it(
    client, auth_headers, survey, monkeypatch
):
    """The data has already landed; a failure recomputing a tile cannot undo it.

    The scheduled run has always isolated one bad indicator from the rest, and
    this path has more to lose: the exception would travel up through the
    ingest that is writing the dataset.
    """
    from app.services import monitoring

    def explode(db, indicator, store_snapshot=True):
        raise RuntimeError("the query engine fell over")

    monkeypatch.setattr(monitoring, "refresh_indicator", explode)

    _import(client, auth_headers, survey, 9)
