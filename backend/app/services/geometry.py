"""Reading boundary files without a GIS stack.

The boundaries a census works to - enumeration areas, districts, villages -
arrive from a national statistics office in whatever their GIS people export:
a GeoPackage, a shapefile in a zip, or GeoJSON. All three end up here as the
same thing, a list of features with a geometry and an attribute table, so
nothing downstream has to know which one it came from.

None of this needs GDAL or a DuckDB extension. That is deliberate: both want a
download or a system package at the moment they are first used, and a field
office server behind a ministry firewall is exactly where this platform is
supposed to run. A GeoPackage is a SQLite file and a shapefile is a documented
binary format, so both can be read where they sit.
"""

from __future__ import annotations

import io
import json
import sqlite3
import struct
import tempfile
import zipfile
from pathlib import Path
from typing import Any

# A boundary file describes areas, so these are what a layer may contain. A
# file of points or lines is a different thing that happens to be geographic,
# and letting one in would only produce a layer that draws nothing.
AREA_TYPES = {"Polygon", "MultiPolygon"}

# Enough for a national frame at enumeration-area detail; past this the browser
# is drawing more outlines than a screen has pixels for.
MAX_FEATURES = 20_000


class BoundaryError(ValueError):
    """A boundary file that cannot be read, said in words a user can act on."""


class Feature(dict):
    """One area: its geometry as GeoJSON, and the attributes recorded against it."""


def _bbox_of(coordinates: Any, box: list[float]) -> None:
    """Grow box to hold every coordinate in a nested ring structure."""
    if not coordinates:
        return
    first = coordinates[0]
    if isinstance(first, (int, float)):
        x, y = float(coordinates[0]), float(coordinates[1])
        box[0] = min(box[0], x)
        box[1] = min(box[1], y)
        box[2] = max(box[2], x)
        box[3] = max(box[3], y)
        return
    for item in coordinates:
        _bbox_of(item, box)


def bounds(features: list[dict[str, Any]]) -> list[float] | None:
    """The rectangle holding every feature, for framing the map on it."""
    box = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    for feature in features:
        geometry = feature.get("geometry") or {}
        _bbox_of(geometry.get("coordinates"), box)
    return None if box[0] == float("inf") else box


def property_names(features: list[dict[str, Any]]) -> list[str]:
    """Every attribute any feature carries, in the order first seen.

    Read from the features rather than from a schema, because the schema is
    the one thing the three formats disagree about and the attributes are the
    one thing they agree on.
    """
    names: list[str] = []
    for feature in features:
        for name in (feature.get("properties") or {}):
            if name not in names:
                names.append(name)
    return names


# --- GeoJSON ---------------------------------------------------------------


def _clean(geometry: Any) -> dict[str, Any] | None:
    """Keep a geometry only if it describes an area."""
    if not isinstance(geometry, dict):
        return None
    kind = geometry.get("type")
    if kind in AREA_TYPES:
        return {"type": kind, "coordinates": geometry.get("coordinates") or []}
    if kind == "GeometryCollection":
        # One area out of a collection is still an area; several are merged,
        # since a collection is how some exporters spell a multipolygon.
        parts = [_clean(part) for part in geometry.get("geometries") or []]
        rings = [
            ring
            for part in parts
            if part
            for ring in (
                part["coordinates"] if part["type"] == "MultiPolygon" else [part["coordinates"]]
            )
        ]
        return {"type": "MultiPolygon", "coordinates": rings} if rings else None
    return None


def read_geojson(raw: bytes) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BoundaryError(f"This is not readable GeoJSON: {exc}") from exc

    if isinstance(parsed, dict) and parsed.get("type") == "FeatureCollection":
        raw_features = parsed.get("features") or []
    elif isinstance(parsed, dict) and parsed.get("type") == "Feature":
        raw_features = [parsed]
    elif isinstance(parsed, dict) and parsed.get("type") in AREA_TYPES:
        raw_features = [{"type": "Feature", "geometry": parsed, "properties": {}}]
    else:
        raise BoundaryError("This JSON is not a GeoJSON feature collection")

    features = []
    for item in raw_features:
        geometry = _clean((item or {}).get("geometry"))
        if geometry is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": dict(item.get("properties") or {}),
            }
        )
    return features


# --- Well-known binary, which is how both other formats store a geometry ----

_WKB_TYPES = {1: "Point", 2: "LineString", 3: "Polygon", 6: "MultiPolygon"}


class _Reader:
    """A cursor over WKB bytes, tracking the byte order each geometry declares."""

    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.at = offset
        self.order = "<"

    def take(self, fmt: str) -> tuple:
        size = struct.calcsize(self.order + fmt)
        if self.at + size > len(self.data):
            raise BoundaryError("A geometry in this file ends before it should")
        values = struct.unpack_from(self.order + fmt, self.data, self.at)
        self.at += size
        return values

    def header(self) -> int:
        (byte_order,) = struct.unpack_from("B", self.data, self.at)
        self.at += 1
        self.order = "<" if byte_order == 1 else ">"
        (code,) = self.take("I")
        # The thousands digit carries Z/M dimensions and the SRID flag; the
        # shape itself is the remainder, and a 3D polygon is still a polygon.
        return code % 1000

    def coordinates(self, dimensions: int) -> list[float]:
        values = self.take(f"{dimensions}d")
        return [values[0], values[1]]


def _wkb_geometry(reader: _Reader, dimensions: int = 2) -> dict[str, Any] | None:
    code = reader.header()
    kind = _WKB_TYPES.get(code)
    if kind == "Polygon":
        (ring_count,) = reader.take("I")
        rings = []
        for _ in range(ring_count):
            (point_count,) = reader.take("I")
            rings.append([reader.coordinates(dimensions) for _ in range(point_count)])
        return {"type": "Polygon", "coordinates": rings}
    if kind == "MultiPolygon":
        (part_count,) = reader.take("I")
        parts = []
        for _ in range(part_count):
            part = _wkb_geometry(reader, dimensions)
            if part and part["type"] == "Polygon":
                parts.append(part["coordinates"])
        return {"type": "MultiPolygon", "coordinates": parts}
    # A point or a line in a boundary file is not an area, and skipping it is
    # not an error - but the cursor has to be left somewhere valid, so this
    # gives up on the rest of the blob rather than guessing its length.
    return None


def _geopackage_geometry(blob: bytes) -> dict[str, Any] | None:
    """Unwrap a GeoPackage binary blob: its own header, then plain WKB."""
    if len(blob) < 8 or blob[:2] != b"GP":
        return None
    flags = blob[3]
    envelope = (flags >> 1) & 0x07
    # The envelope is 0, 4, 6 or 8 doubles depending on which dimensions it
    # covers, and the geometry starts after it.
    doubles = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}.get(envelope)
    if doubles is None:
        return None
    start = 8 + doubles * 8
    if start >= len(blob):
        return None
    try:
        return _wkb_geometry(_Reader(blob, start))
    except (struct.error, BoundaryError):
        return None


# --- GeoPackage ------------------------------------------------------------


def read_geopackage(path: Path, layer: str = "") -> list[dict[str, Any]]:
    """Features from one table of a GeoPackage, which is a SQLite database."""
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BoundaryError(f"This GeoPackage cannot be opened: {exc}") from exc

    try:
        connection.row_factory = sqlite3.Row
        try:
            tables = connection.execute(
                "SELECT table_name, column_name FROM gpkg_geometry_columns"
            ).fetchall()
        except sqlite3.Error as exc:
            raise BoundaryError(
                "This file is not a GeoPackage: it has no geometry columns table"
            ) from exc
        if not tables:
            raise BoundaryError("This GeoPackage holds no spatial layers")

        chosen = next((row for row in tables if row["table_name"] == layer), tables[0])
        table, geometry_column = chosen["table_name"], chosen["column_name"]
        # The table name comes from the file's own catalogue, not from a
        # request, and is quoted anyway: a layer called "my table" is legal.
        quoted = '"' + table.replace('"', '""') + '"'
        rows = connection.execute(f"SELECT * FROM {quoted}").fetchall()  # noqa: S608
    finally:
        connection.close()

    features = []
    for row in rows:
        record = dict(row)
        geometry = _geopackage_geometry(record.pop(geometry_column, None) or b"")
        if geometry is None:
            continue
        properties = {
            key: value
            for key, value in record.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        features.append({"type": "Feature", "geometry": geometry, "properties": properties})
    return features


def geopackage_layers(path: Path) -> list[str]:
    """The spatial layers a GeoPackage offers, so one can be chosen."""
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute("SELECT table_name FROM gpkg_geometry_columns").fetchall()
        return [row[0] for row in rows]
    except sqlite3.Error:
        return []
    finally:
        connection.close()


# --- Shapefile -------------------------------------------------------------


def read_shapefile_zip(raw: bytes) -> list[dict[str, Any]]:
    """Features from a zipped shapefile, the usual handover from an NSO."""
    import shapefile  # pyshp, imported here so the rest works without it

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise BoundaryError("This is not a readable zip archive") from exc

    names = archive.namelist()
    shp = next((name for name in names if name.lower().endswith(".shp")), None)
    if shp is None:
        raise BoundaryError("This zip holds no .shp file")
    stem = shp[: -len(".shp")]

    with tempfile.TemporaryDirectory() as workspace:
        room = Path(workspace)
        for suffix in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
            member = next(
                (name for name in names if name.lower() == (stem + suffix).lower()), None
            )
            if member is None:
                continue
            # Flattened onto one name, so a zip whose entries carry directory
            # paths cannot write outside the workspace.
            (room / ("layer" + suffix)).write_bytes(archive.read(member))
        if not (room / "layer.shp").exists():
            raise BoundaryError("This zip holds no .shp file")
        if not (room / "layer.dbf").exists():
            raise BoundaryError("This shapefile has no .dbf, so it carries no area names")
        try:
            reader = shapefile.Reader(str(room / "layer"))
            records = reader.shapeRecords()
        except Exception as exc:  # pyshp raises several unrelated types
            raise BoundaryError(f"This shapefile cannot be read: {exc}") from exc

        features = []
        for item in records:
            geometry = _clean(item.shape.__geo_interface__)
            if geometry is None:
                continue
            properties = {
                key: (value.isoformat() if hasattr(value, "isoformat") else value)
                for key, value in item.record.as_dict().items()
            }
            features.append(
                {"type": "Feature", "geometry": geometry, "properties": properties}
            )
        return features


# --- The one door in ------------------------------------------------------


def read(filename: str, raw: bytes, layer: str = "") -> list[dict[str, Any]]:
    """Features from whichever of the three formats this file turns out to be."""
    name = (filename or "").lower()
    if name.endswith((".geojson", ".json")):
        features = read_geojson(raw)
    elif name.endswith(".gpkg"):
        with tempfile.TemporaryDirectory() as workspace:
            path = Path(workspace) / "layer.gpkg"
            path.write_bytes(raw)
            features = read_geopackage(path, layer)
    elif name.endswith(".zip"):
        features = read_shapefile_zip(raw)
    else:
        raise BoundaryError(
            "Boundaries can be read from GeoJSON, a GeoPackage, or a zipped shapefile"
        )

    if not features:
        raise BoundaryError("No areas were found in this file")
    if len(features) > MAX_FEATURES:
        raise BoundaryError(
            f"This layer has {len(features):,} areas, more than the {MAX_FEATURES:,} "
            "a map can draw. Load a level above it, or split it by region."
        )
    return features
