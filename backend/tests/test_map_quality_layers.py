"""A data quality map's layers: duplicates, a second location, lines, coverage.

The map widget checked one thing - whether a record's enumeration area agrees
with where its GPS reading falls. A field office's own quality map shows more:
GPS readings shared by two households, the location typed or picked by hand
beside the GPS and checked on its own, a line between the two wherever they
are far apart, and which areas the fieldwork has reached at all. Each of these
is asked of the records as recorded, before any pins are grouped.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.api.v1.endpoints.dashboards import _metres
from app.services import geo
from app.services.boundaries import Areas
from app.services.query_engine import DatasetContext, QueryError, VariableInfo
from tests.test_boundaries import layer, render  # noqa: F401 - `layer` is a fixture

# Two enumeration areas side by side near the equator, where 0.001 degrees is
# about 111 metres either way.
EAS = [
    ("01", [[166.90, -0.55], [166.91, -0.55], [166.91, -0.54], [166.90, -0.54], [166.90, -0.55]]),
    ("02", [[166.91, -0.55], [166.92, -0.55], [166.92, -0.54], [166.91, -0.54], [166.91, -0.55]]),
]
AREAS = Areas(
    [
        {"type": "Feature", "properties": {"code": code}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
        for code, ring in EAS
    ]
)

# key, recorded EA, GPS lat, GPS lon, manual lat, manual lon
HOUSEHOLDS = [
    # In 01, says 01, entered by hand where the GPS put it.
    ("h1", "01", -0.5450, 166.9050, -0.5450, 166.9050),
    # 33 m from h1, says 01 - and its hand-entered location is in 02, a
    # kilometre away.
    ("h2", "01", -0.5450, 166.9053, -0.5450, 166.9150),
    # In 02, says 02, nothing entered by hand.
    ("h3", "02", -0.5452, 166.9150, np.nan, np.nan),
    # The device never got a fix; the location was picked by hand, in 02.
    ("h4", "02", np.nan, np.nan, -0.5435, 166.9165),
    # In 02 but says 01; picked by hand 11 m away.
    ("h5", "01", -0.5410, 166.9180, -0.5411, 166.9180),
    # Outside both areas.
    ("h6", "02", -0.5600, 166.9500, np.nan, np.nan),
]


@pytest.fixture
def island(tmp_path) -> DatasetContext:
    frame = pd.DataFrame(
        HOUSEHOLDS, columns=["key", "ea", "lat", "lon", "man_lat", "man_lon"]
    )
    path = tmp_path / "households.parquet"
    frame.to_parquet(path, index=False)
    kinds = {"key": "text", "ea": "categorical"}
    return DatasetContext(
        dataset_id="island",
        parquet_path=str(path),
        variables={
            name: VariableInfo(name, name, kinds.get(name, "numeric"), storage_type=str(frame[name].dtype))
            for name in frame.columns
        },
    )


def draw(ctx: DatasetContext, **extra) -> dict:
    return geo.points(
        ctx,
        latitude="lat",
        longitude="lon",
        area_variable="ea",
        areas=AREAS,
        boundary_key="code",
        **extra,
    )


def at(points: list[dict], lat: float, lon: float) -> dict:
    return next(p for p in points if abs(p["lat"] - lat) < 1e-9 and abs(p["lon"] - lon) < 1e-9)


def test_nothing_new_is_sent_unless_asked_for(island):
    found = draw(island)
    assert found["duplicates"] is None and found["manual"] is None and found["lines"] is None
    assert found["coverage"] is None
    assert "duplicates" not in found["points"][0]


def test_readings_within_the_distance_are_flagged_as_duplicates(island):
    found = draw(island, duplicate_metres=100)
    assert found["duplicates"] == {"metres": 100.0, "places": 2}
    assert at(found["points"], -0.5450, 166.9050)["duplicates"] == 1
    assert at(found["points"], -0.5450, 166.9053)["duplicates"] == 1
    assert at(found["points"], -0.5452, 166.9150)["duplicates"] == 0
    # 33 m apart is not a duplicate at 20 m.
    assert draw(island, duplicate_metres=20)["duplicates"]["places"] == 0


def test_two_records_at_one_reading_are_duplicates_of_each_other(tmp_path):
    frame = pd.DataFrame({"lat": [-0.545, -0.545, -0.546], "lon": [166.905, 166.905, 166.915]})
    path = tmp_path / "same.parquet"
    frame.to_parquet(path, index=False)
    ctx = DatasetContext(
        "same", str(path), {name: VariableInfo(name, name, "numeric") for name in frame.columns}
    )
    found = geo.points(ctx, latitude="lat", longitude="lon", duplicate_metres=10)
    shared = at(found["points"], -0.545, 166.905)
    assert shared["rows"] == 2 and shared["duplicates"] == 1
    assert found["duplicates"]["places"] == 1


def test_the_second_location_is_checked_on_its_own(island):
    manual = draw(island, manual_latitude="man_lat", manual_longitude="man_lon")["manual"]
    # h1 and h4 agree; h2 and h5 were entered in 02 while saying 01. h4 is
    # there although its GPS is blank: that is the record this layer is for.
    assert manual["counts"] == {"match": 2, "mismatch": 2, "outside": 0, "unrecorded": 0}
    assert manual["records"] == 4
    picked = at(manual["points"], -0.5435, 166.9165)
    assert picked["area_status"] == "match" and picked["rows"] == 1
    assert at(manual["points"], -0.5450, 166.9150)["area_status"] == "mismatch"


def test_a_line_is_drawn_where_the_two_locations_are_far_apart(island):
    lines = draw(island, manual_latitude="man_lat", manual_longitude="man_lon")["lines"]
    assert lines["metres"] == 100.0 and lines["total"] == 1
    (line,) = lines["lines"]
    assert line["gps"] == [-0.545, 166.9053] and line["manual"] == [-0.545, 166.915]
    assert 1060 < line["metres"] < 1090
    # Down to 5 m, h5's 11 m gap is a line too; h1, entered where the GPS
    # said, never is.
    closer = draw(island, manual_latitude="man_lat", manual_longitude="man_lon", line_metres=5)
    assert closer["lines"]["total"] == 2
    assert closer["lines"]["lines"][0]["metres"] > closer["lines"]["lines"][1]["metres"]


def test_coverage_counts_the_records_in_each_area(island):
    assert draw(island, coverage=True)["coverage"] == {"0": 2, "1": 2}
    # Without the area check as well, the points are located for coverage alone.
    plain = geo.points(island, latitude="lat", longitude="lon", areas=AREAS, coverage=True)
    assert plain["coverage"] == {"0": 2, "1": 2}
    assert "area_status" not in plain["points"][0]


def test_half_a_second_location_is_refused(island):
    with pytest.raises(QueryError, match="both a latitude and a longitude"):
        draw(island, manual_latitude="man_lat")


def test_a_grouped_map_keeps_the_findings_it_was_given(tmp_path):
    """Past a few thousand places the pins are cells, flagged from the places in them."""
    rng = np.random.default_rng(5)
    rows = 6_000
    lat = (-17.7 + rng.normal(0, 0.15, rows)).round(6)
    lon = (168.3 + rng.normal(0, 0.15, rows)).round(6)
    # Ten households share the first one's reading exactly.
    lat[1:11], lon[1:11] = lat[0], lon[0]
    frame = pd.DataFrame({"lat": lat, "lon": lon})
    path = tmp_path / "census.parquet"
    frame.to_parquet(path, index=False)
    ctx = DatasetContext(
        "census", str(path), {name: VariableInfo(name, name, "numeric") for name in frame.columns}
    )
    found = geo.points(ctx, latitude="lat", longitude="lon", duplicate_metres=1)
    assert found["grouped"] is not None
    assert sum(int(point["rows"]) for point in found["points"]) == rows
    flagged = [point for point in found["points"] if point.get("duplicate_places")]
    assert flagged and sum(point["rows"] for point in flagged) >= 11
    assert all("area_status" not in point for point in found["points"])


def test_a_distance_from_the_settings_form():
    assert _metres("250", 100.0) == 250.0
    assert _metres(None, 100.0) == 100.0
    assert _metres("", 0.0) == 0.0
    assert _metres("far", 100.0) == 100.0
    assert _metres(-5, 100.0) == 0.0


# --- Through the dashboard, as the widget's settings are saved -----------------


def test_a_widget_turns_the_layers_on(client, auth_headers, layer):  # noqa: F811 - the fixture
    body = (
        "key,ea_code,latitude,longitude,man_lat,man_lon\n"
        # In North ward; picked by hand in South, kilometres away.
        "h1,001,-12.87,34.02,-12.85,34.15\n"
        # 40 m from h1, entered by hand where the GPS said.
        "h2,001,-12.8703,34.0202,-12.8703,34.0202\n"
        # In South ward, nothing entered by hand.
        "h3,002,-12.85,34.15,,\n"
    )
    dataset = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("quality.csv", body.encode(), "text/csv")},
    ).json()
    dataset_id = (dataset["datasets"][0] if "datasets" in dataset else dataset)["id"]
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Quality map"}
    ).json()
    created = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Locations",
            "widget_type": "map",
            "dataset_id": dataset_id,
            "config": {
                "dataset_id": dataset_id,
                "latitude": "latitude",
                "longitude": "longitude",
                "boundary_id": layer["id"],
                "boundary_key": "code",
                "area_variable": "ea_code",
                "manual_latitude": "man_lat",
                "manual_longitude": "man_lon",
                # As a settings form may send it.
                "duplicate_metres": "100",
                "coverage": True,
            },
        },
    )
    assert created.status_code == 201, created.text

    payload = render(client, auth_headers, dashboard["id"])
    assert "error" not in payload, payload
    assert payload["duplicates"] == {"metres": 100.0, "places": 2}
    assert payload["manual"]["counts"]["mismatch"] == 1
    assert payload["manual"]["counts"]["match"] == 1
    assert payload["lines"]["total"] == 1 and payload["lines"]["metres"] == 100.0
    assert payload["coverage"] == {"0": 2, "1": 1}
