"""Boundary layers, and checking a recorded area against where the point is.

A household listing records the enumeration area the interviewer says they
were in; the device records where they were. Those disagreeing is the most
useful thing a monitoring map can say, because it is an EA code typed wrong,
an interviewer in the wrong area, or a boundary the field read differently
from the office - and each of those costs a census dearly if it surfaces after
fieldwork instead of during it.

The frame arrives as whatever the GIS office exports, so all three formats are
pinned here reading the same two areas to the same result.
"""

from __future__ import annotations

import io
import json
import sqlite3
import struct
import zipfile
from pathlib import Path

import pytest

BASE = "/api/v1/boundaries"

# Two adjacent wards near Port Vila. The first has a hole in it, because a
# lagoon in the middle of an enumeration area is the case that separates real
# point-in-polygon from a bounding-box check.
WARDS = [
    {
        "code": "001",
        "name": "North ward",
        "rings": [
            [(168.0, -17.9), (168.1, -17.9), (168.1, -17.8), (168.0, -17.8), (168.0, -17.9)],
            [
                (168.04, -17.86),
                (168.06, -17.86),
                (168.06, -17.84),
                (168.04, -17.84),
                (168.04, -17.86),
            ],
        ],
    },
    {
        "code": "002",
        "name": "South ward",
        "rings": [
            [(168.1, -17.9), (168.2, -17.9), (168.2, -17.8), (168.1, -17.8), (168.1, -17.9)]
        ],
    },
]


def geojson_bytes() -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"code": ward["code"], "name": ward["name"]},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[list(p) for p in ring] for ring in ward["rings"]],
                    },
                }
                for ward in WARDS
            ],
        }
    ).encode()


def _wkb_polygon(rings) -> bytes:
    body = struct.pack("<BII", 1, 3, len(rings))
    for ring in rings:
        body += struct.pack("<I", len(ring))
        for x, y in ring:
            body += struct.pack("<dd", x, y)
    return body


def geopackage_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "wards.gpkg"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, "
        "geometry_type_name TEXT, srs_id INTEGER, z INTEGER, m INTEGER)"
    )
    con.execute("INSERT INTO gpkg_geometry_columns VALUES ('wards','geom','POLYGON',4326,0,0)")
    con.execute("CREATE TABLE wards (fid INTEGER PRIMARY KEY, geom BLOB, code TEXT, name TEXT)")
    for index, ward in enumerate(WARDS, 1):
        blob = b"GP" + bytes([0, 1]) + struct.pack("<i", 4326) + _wkb_polygon(ward["rings"])
        con.execute("INSERT INTO wards VALUES (?,?,?,?)", (index, blob, ward["code"], ward["name"]))
    con.commit()
    con.close()
    return path.read_bytes()


def shapefile_zip_bytes() -> bytes:
    import shapefile

    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf)
    writer.field("code", "C", size=10)
    writer.field("name", "C", size=40)
    for ward in WARDS:
        # A shapefile's outer ring runs clockwise and its holes anticlockwise,
        # which is the opposite of the GeoJSON above for the outer ring.
        writer.poly(
            [
                [list(p) for p in (reversed(ring) if index == 0 else ring)]
                for index, ring in enumerate(ward["rings"])
            ]
        )
        writer.record(ward["code"], ward["name"])
    writer.close()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("wards/wards.shp", shp.getvalue())
        archive.writestr("wards/wards.shx", shx.getvalue())
        archive.writestr("wards/wards.dbf", dbf.getvalue())
    return buffer.getvalue()


def upload(client, auth_headers, filename: str, raw: bytes, **data):
    return client.post(
        BASE,
        headers=auth_headers,
        files={"file": (filename, raw, "application/octet-stream")},
        data=data or None,
    )


@pytest.fixture
def layer(client, auth_headers):
    response = upload(client, auth_headers, "wards.geojson", geojson_bytes(), name="Wards")
    assert response.status_code == 201, response.text
    return response.json()


# --- Reading the three formats --------------------------------------------


def test_geojson_is_read(client, auth_headers, layer):
    assert layer["feature_count"] == 2
    assert layer["properties"] == ["code", "name"]
    assert [round(v, 3) for v in layer["bbox"]] == [168.0, -17.9, 168.2, -17.8]
    assert layer["source_format"] == "geojson"


def test_a_geopackage_reads_to_the_same_thing(client, auth_headers, tmp_path):
    """A GeoPackage is a SQLite file, read where it sits rather than through GDAL."""
    response = upload(client, auth_headers, "wards.gpkg", geopackage_bytes(tmp_path))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["feature_count"] == 2
    assert body["source_format"] == "geopackage"
    assert [round(v, 3) for v in body["bbox"]] == [168.0, -17.9, 168.2, -17.8]
    assert {"code", "name"} <= set(body["properties"])


def test_a_zipped_shapefile_reads_to_the_same_thing(client, auth_headers):
    response = upload(client, auth_headers, "wards.zip", shapefile_zip_bytes())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["feature_count"] == 2
    assert body["source_format"] == "shapefile"
    assert [round(v, 3) for v in body["bbox"]] == [168.0, -17.9, 168.2, -17.8]
    assert {"code", "name"} <= set(body["properties"])


def test_the_hole_survives_every_format(client, auth_headers, tmp_path):
    """A lagoon inside an area has to still be a lagoon after the round trip."""
    for filename, raw in (
        ("wards.geojson", geojson_bytes()),
        ("wards.gpkg", geopackage_bytes(tmp_path)),
        ("wards.zip", shapefile_zip_bytes()),
    ):
        created = upload(client, auth_headers, filename, raw).json()
        features = client.get(
            f"{BASE}/{created['id']}/geojson", headers=auth_headers
        ).json()["features"]
        north = next(f for f in features if f["properties"]["code"].strip() == "001")
        assert len(north["geometry"]["coordinates"]) == 2, filename


def test_a_file_that_is_not_boundaries_is_refused(client, auth_headers):
    assert upload(client, auth_headers, "notes.txt", b"hello").status_code == 422
    assert upload(client, auth_headers, "empty.geojson", b"{}").status_code == 422
    assert (
        upload(client, auth_headers, "points.geojson", json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {},
                          "geometry": {"type": "Point", "coordinates": [1, 2]}}],
        }).encode()).status_code
        == 422
    )


# --- Point in polygon ------------------------------------------------------


def test_which_area_a_point_falls_in():
    from app.services.boundaries import Areas
    from app.services.geometry import read_geojson

    areas = Areas(read_geojson(geojson_bytes()))
    at = lambda lon, lat: areas.value(areas.locate(lon, lat), "code")  # noqa: E731

    assert at(168.02, -17.87) == "001"
    assert at(168.15, -17.85) == "002"
    # Inside the outer ring but inside the hole, so outside the area.
    assert at(168.05, -17.85) is None
    assert at(167.50, -17.85) is None


def test_a_code_is_the_same_code_however_it_was_written():
    """Codes cross from a questionnaire to a GIS file losing their leading zeros."""
    from app.services.boundaries import same_code

    assert same_code("07", 7)
    assert same_code("007", "7")
    assert same_code(7.0, "07")
    assert not same_code("1", "2")
    assert not same_code(None, "1")
    assert not same_code("", "1")


# --- The check on a map widget --------------------------------------------


@pytest.fixture
def mapped(client, auth_headers, layer):
    """A dataset of four households and a map widget checking them against the wards."""
    rows = [
        # In North ward, and says so: agrees.
        ("h1", "001", -17.87, 168.02),
        # In South ward but says North: the mismatch this whole feature is for.
        ("h2", "001", -17.85, 168.15),
        # In the lagoon inside North ward, so in no area at all.
        ("h3", "001", -17.85, 168.05),
        # Nowhere near the frame.
        ("h4", "002", -17.85, 167.50),
    ]
    body = "key,ea_code,latitude,longitude\n" + "\n".join(
        f"{k},{c},{lat},{lon}" for k, c, lat, lon in rows
    )
    dataset = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("wardcheck.csv", body.encode(), "text/csv")},
    ).json()
    dataset_id = (dataset["datasets"][0] if "datasets" in dataset else dataset)["id"]

    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Field map"}
    ).json()
    widget = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Households",
            "widget_type": "map",
            "dataset_id": dataset_id,
            "config": {
                "dataset_id": dataset_id,
                "latitude": "latitude",
                "longitude": "longitude",
                "boundary_id": layer["id"],
                "boundary_key": "code",
                "boundary_label": "name",
                "area_variable": "ea_code",
            },
        },
    )
    assert widget.status_code == 201, widget.text
    return {"dashboard": dashboard["id"], "layer": layer}


def render(client, auth_headers, dashboard_id) -> dict:
    response = client.post(
        f"/api/v1/dashboards/{dashboard_id}/data", headers=auth_headers, json={}
    )
    assert response.status_code == 200, response.text
    return next(iter(response.json()["widgets"].values()))


def test_a_recorded_area_is_checked_against_where_the_point_is(
    client, auth_headers, mapped
):
    payload = render(client, auth_headers, mapped["dashboard"])
    assert "error" not in payload, payload
    counts = payload["area_check"]["counts"]
    assert counts == {"match": 1, "mismatch": 1, "outside": 2, "unrecorded": 0}


def test_each_point_carries_its_own_verdict(client, auth_headers, mapped):
    """The counts are the summary; the map colours pins from these."""
    payload = render(client, auth_headers, mapped["dashboard"])
    verdicts = {
        round(point["lon"], 2): (point["area_status"], point["area_expected"])
        for point in payload["points"]
    }
    assert verdicts[168.02] == ("match", "001")
    # The one that matters: it says 001, it is standing in 002.
    assert verdicts[168.15] == ("mismatch", "002")
    assert verdicts[168.05] == ("outside", None)
    assert verdicts[167.50] == ("outside", None)


def test_a_point_outside_the_frame_is_not_called_a_mismatch(
    client, auth_headers, mapped
):
    """A frame that does not cover an island yet is not the interviewer's error."""
    payload = render(client, auth_headers, mapped["dashboard"])
    outside = [p for p in payload["points"] if p["area_status"] == "outside"]
    assert len(outside) == 2
    assert all(point["area_expected"] is None for point in outside)


def test_the_map_still_works_with_no_boundary_named(client, auth_headers, mapped):
    """Every existing map widget names no layer, and has to go on drawing."""
    dashboard = client.get(
        f"/api/v1/dashboards/{mapped['dashboard']}", headers=auth_headers
    ).json()
    widget = dashboard["widgets"][0]
    config = dict(widget["config"])
    for key in ("boundary_id", "boundary_key", "area_variable"):
        config.pop(key)
    client.patch(
        f"/api/v1/dashboards/{mapped['dashboard']}/widgets/{widget['id']}",
        headers=auth_headers,
        json={"config": config},
    )
    payload = render(client, auth_headers, mapped["dashboard"])
    assert payload["type"] == "map"
    assert len(payload["points"]) == 4
    assert "area_check" not in payload
    assert "boundary" not in payload


def test_the_boundary_travels_with_the_widget(client, auth_headers, mapped):
    """So the map can draw the outlines without a second round trip to find them."""
    payload = render(client, auth_headers, mapped["dashboard"])
    assert payload["boundary"]["id"] == mapped["layer"]["id"]
    assert payload["boundary"]["label"] == "name"
    assert len(payload["boundary"]["bbox"]) == 4


# --- Housekeeping ----------------------------------------------------------


def test_layers_are_listed_and_deleted(client, auth_headers, layer):
    listed = client.get(BASE, headers=auth_headers).json()
    assert layer["id"] in [item["id"] for item in listed]

    from app.services.boundary_store import path_for

    assert path_for(layer["id"]).exists()
    assert client.delete(f"{BASE}/{layer['id']}", headers=auth_headers).status_code == 200
    assert client.get(f"{BASE}/{layer['id']}", headers=auth_headers).status_code == 404
    # The geometry goes with the record rather than being left on disk.
    assert not path_for(layer["id"]).exists()


def test_a_project_s_layers_and_the_shared_ones_are_both_offered(client, auth_headers):
    """A national frame is uploaded once and used by every survey working to it."""
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Boundary scope"}
    ).json()
    shared = upload(client, auth_headers, "shared.geojson", geojson_bytes(), name="National").json()
    owned = upload(
        client, auth_headers, "own.geojson", geojson_bytes(), name="Survey only",
        project_id=project["id"],
    ).json()

    names = {
        item["id"]
        for item in client.get(
            f"{BASE}?project_id={project['id']}", headers=auth_headers
        ).json()
    }
    assert shared["id"] in names
    assert owned["id"] in names

    shared_only = {
        item["id"]
        for item in client.get(f"{BASE}?project_id=none", headers=auth_headers).json()
    }
    assert shared["id"] in shared_only
    assert owned["id"] not in shared_only
