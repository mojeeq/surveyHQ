"""Reading survey files and deriving metadata."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.ingest import (
    IngestError,
    _deduplicate,
    detect_monitoring_fields,
    ingest_file,
)


def test_stata_ingest_preserves_labels(stata_file, tmp_path):
    result = ingest_file(stata_file, tmp_path / "out")
    assert result.row_count == 200
    assert result.parquet_path.exists()

    by_name = {v.name: v for v in result.variables}
    assert by_name["sex"].value_labels == {"1": "Male", "2": "Female"}
    assert by_name["age"].label == "Age of respondent"
    # 10 incomes were set to NaN in the fixture
    assert by_name["income"].n_missing == 10


def test_csv_ingest_infers_types(tmp_path):
    source = tmp_path / "data.csv"
    source.write_text(
        "name,score,joined,active\n"
        "ana,10.5,2026-01-01,true\n"
        "ben,,2026-01-02,false\n"
        "cara,8.25,2026-01-03,true\n"
    )
    result = ingest_file(source, tmp_path / "out")
    types = {v.name: v.var_type for v in result.variables}
    assert types["score"] == "numeric"
    assert types["joined"] == "datetime"
    assert result.row_count == 3


def test_unsupported_extension_is_rejected(tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4")
    with pytest.raises(IngestError, match="Unsupported file type"):
        ingest_file(source, tmp_path / "out")


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(IngestError, match="File not found"):
        ingest_file(tmp_path / "absent.dta", tmp_path / "out")


def test_duplicate_column_names_are_made_unique():
    assert _deduplicate(["a", "a", "b", "a"]) == ["a", "a_1", "b", "a_2"]


def test_duplicate_columns_survive_ingestion(tmp_path):
    source = tmp_path / "dupes.csv"
    source.write_text("q1,q1\n1,2\n3,4\n")
    result = ingest_file(source, tmp_path / "out")
    names = [v.name for v in result.variables]
    assert len(names) == len(set(names))


def test_monitoring_field_detection(stata_file, tmp_path):
    result = ingest_file(stata_file, tmp_path / "out")
    fields = detect_monitoring_fields(result.variables)
    assert fields["interview_key"] == "interview__key"
    assert fields["status"] == "interview__status"
    assert fields["interviewer"] == "interviewer"
    assert fields["date"] == "interview__date"


def test_empty_file_produces_a_warning(tmp_path):
    source = tmp_path / "empty.csv"
    source.write_text("a,b\n")
    result = ingest_file(source, tmp_path / "out")
    assert result.row_count == 0
    assert any("no data rows" in w for w in result.warnings)


def test_streaming_a_large_file_gives_the_same_metadata_as_reading_it_whole(
    tmp_path, monkeypatch
):
    """The two ingest paths must agree, or a file behaves differently by size.

    Getting this wrong is invisible: the data lands either way, and only the
    variable types, ranges and missing counts quietly differ. Both paths run
    here over one file and every field of every column is compared.
    """
    pyreadstat = pytest.importorskip("pyreadstat")
    from app.services import ingest as ingest_module

    rng = np.random.default_rng(7)
    size = 4_000
    frame = pd.DataFrame(
        {
            # A code set with a gap in it, which is float64 in pandas and DOUBLE
            # in Parquet, and is still a code set
            "sex": rng.choice([1.0, 2.0, np.nan], size),
            "age": rng.integers(15, 80, size).astype(float),
            "region": rng.choice(["North", "South", "East"], size),
            # Dates crowded into the first chunk and scattered one per chunk
            # after it. Detection needs three values in its sample, so the first
            # chunk recognises the column and the later ones do not - unless the
            # set of date columns is settled once and reused. When they do not,
            # those stragglers are cast to the first chunk's timestamp type and
            # become nulls, which shows up as a missing count that disagrees.
            "visited": [
                f"2026-0{1 + i % 9}-1{i % 9}"
                if (i < 200 or i % 1000 == 500)
                else None
                for i in range(size)
            ],
            # Entirely empty, as survey exports are full of
            "never_asked": [None] * size,
        }
    )
    path = tmp_path / "wide.dta"
    pyreadstat.write_dta(
        frame, str(path), variable_value_labels={"sex": {1: "Male", 2: "Female"}}
    )

    # Force the streaming path on a small file, and make it span several chunks
    monkeypatch.setattr(ingest_module, "STREAM_ABOVE_CELLS", 1)
    monkeypatch.setattr(ingest_module, "STREAM_CHUNK_CELLS", 2_000)

    streamed = ingest_module.ingest_file(path, tmp_path / "streamed")
    assert any("chunks" in w for w in streamed.warnings), streamed.warnings

    data, labels, value_labels = ingest_module.read_source(path)
    whole = ingest_module.ingest_frame(data, labels, value_labels, tmp_path / "whole")

    assert streamed.row_count == whole.row_count == size
    left = {v.name: v for v in streamed.variables}
    right = {v.name: v for v in whole.variables}
    assert set(left) == set(right)

    for name in sorted(left):
        a, b = left[name], right[name]
        assert a.var_type == b.var_type, f"{name}: {a.var_type} vs {b.var_type}"
        assert a.n_missing == b.n_missing, name
        assert a.n_unique == b.n_unique, name
        for field in ("min_value", "max_value", "mean_value"):
            x, y = getattr(a, field), getattr(b, field)
            assert (x is None) == (y is None), f"{name}.{field}"
            if x is not None:
                assert abs(x - y) < 1e-6, f"{name}.{field}"

    # And the classification itself is right, not merely consistent
    assert left["sex"].var_type == "categorical"      # value labels
    assert left["age"].var_type == "numeric"
    assert left["region"].var_type == "categorical"   # few distinct strings
    # Sparse, so the whole-file read sees enough values to call it a date while
    # an individual chunk may not. Whatever they conclude, they must agree.
    assert left["visited"].var_type == right["visited"].var_type
    assert left["never_asked"].var_type == "text"     # no values, no evidence


def test_a_gps_column_is_found_and_a_date_is_not_mistaken_for_one():
    """"lat" appears inside ACTIVATE_DATE_SIMULATION, which is not a latitude.

    A bare substring match reads it as one and points the map at a date column,
    which is what happened on a real export.
    """
    from app.services.ingest import VariableMeta, detect_monitoring_fields

    def variable(name: str) -> VariableMeta:
        return VariableMeta(name=name, label="", var_type="numeric", storage_type="DOUBLE")

    detected = detect_monitoring_fields(
        [
            variable("ACTIVATE_DATE_SIMULATION"),
            variable("GPS_4__Latitude"),
            variable("GPS_4__Longitude"),
        ]
    )
    assert detected["latitude"] == "GPS_4__Latitude"
    assert detected["longitude"] == "GPS_4__Longitude"


# --- a GPS question that arrived as one column ------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # ODK Central: latitude, longitude, altitude, accuracy in one field.
        ("-17.7333 168.3273 42.0 5.0", (-17.7333, 168.3273)),
        ("-17.7333 168.3273", (-17.7333, 168.3273)),
        ("-17.7333,168.3273", (-17.7333, 168.3273)),
        ("-17.7333, 168.3273", (-17.7333, 168.3273)),
        ("  -17.7333;168.3273  ", (-17.7333, 168.3273)),
        # WKT and GeoJSON are longitude first by specification.
        ("POINT(168.3273 -17.7333)", (-17.7333, 168.3273)),
        ("POINT Z (168.3273 -17.7333 42.0)", (-17.7333, 168.3273)),
        ('{"type": "Point", "coordinates": [168.3273, -17.7333]}', (-17.7333, 168.3273)),
        # A bare pair written longitude first: 168 cannot be a latitude.
        ("168.3273 -17.7333", (-17.7333, 168.3273)),
    ],
)
def test_one_field_holding_both_coordinates_is_read(value, expected):
    from app.services.ingest import parse_geopoint

    parsed = parse_geopoint(value)
    assert parsed is not None
    assert parsed[0] == pytest.approx(expected[0])
    assert parsed[1] == pytest.approx(expected[1])


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "not a location",
        "-17.7333",                     # one number is not a point
        "-117.7333 268.3273",           # neither can be a latitude
        "91.5 190.2",                   # out of range both ways
        '{"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]}',
        "{not json",
    ],
)
def test_what_is_not_a_location_is_not_read_as_one(value):
    from app.services.ingest import parse_geopoint

    assert parse_geopoint(value) is None


def test_a_combined_gps_column_becomes_two_numeric_columns(tmp_path):
    """The map offers numeric variables, so text holding a point is unreachable."""
    from app.services.ingest import detect_monitoring_fields, ingest_frame

    frame = pd.DataFrame(
        {
            "interview__key": [f"K{i}" for i in range(6)],
            "gps": [
                "-17.7333 168.3273 42.0 5.0",
                "-17.7401 168.3150 38.5 4.0",
                "-17.7288 168.3402 51.2 6.0",
                "-17.7355 168.3199 44.1 5.5",
                None,
                "-17.7290 168.3311 40.0 4.5",
            ],
        }
    )
    result = ingest_frame(frame, {"gps": "Location of dwelling"}, {}, tmp_path / "out")

    by_name = {v.name: v for v in result.variables}
    assert by_name["gps__latitude"].var_type == "numeric"
    assert by_name["gps__longitude"].var_type == "numeric"
    # The original column is kept: it is still what the enumerator recorded.
    assert "gps" in by_name
    # A row without a reading has no coordinates rather than a zero pair, so
    # the missing-GPS check counts it and the map does not plot the Atlantic.
    assert by_name["gps__latitude"].n_missing == 1

    stored = pd.read_parquet(result.parquet_path)
    assert stored["gps__latitude"].iloc[0] == pytest.approx(-17.7333)
    assert stored["gps__longitude"].iloc[0] == pytest.approx(168.3273)

    # Named so the platform finds them without anybody configuring a thing.
    detected = detect_monitoring_fields(result.variables)
    assert detected["latitude"] == "gps__latitude"
    assert detected["longitude"] == "gps__longitude"

    assert any("gps__latitude" in w for w in result.warnings)


def test_a_column_of_whole_number_pairs_is_left_alone(tmp_path):
    """A score and a rank are a valid coordinate on paper and nonsense on a map."""
    from app.services.ingest import ingest_frame

    frame = pd.DataFrame(
        {
            "ranking": ["3 7", "1 4", "5 2", "8 1", "2 9", "6 3"],
        }
    )
    result = ingest_frame(frame, {}, {}, tmp_path / "out")
    assert [v.name for v in result.variables] == ["ranking"]


def test_a_mostly_unparseable_column_is_left_alone(tmp_path):
    """A column where a third of the values look like points is something else."""
    from app.services.ingest import ingest_frame

    frame = pd.DataFrame(
        {
            "notes": [
                "-17.7333 168.3273",
                "-17.7401 168.3150",
                "respondent not at home",
                "call back on Tuesday",
                "refused",
                "moved to another village",
            ],
        }
    )
    result = ingest_frame(frame, {}, {}, tmp_path / "out")
    assert [v.name for v in result.variables] == ["notes"]


def test_separate_coordinate_columns_are_not_disturbed(tmp_path):
    """A Survey Solutions export already has two columns and needs no splitting."""
    from app.services.ingest import ingest_frame

    frame = pd.DataFrame(
        {
            "GPS__Latitude": [-17.7333, -17.7401, -17.7288],
            "GPS__Longitude": [168.3273, 168.3150, 168.3402],
        }
    )
    result = ingest_frame(frame, {}, {}, tmp_path / "out")
    assert [v.name for v in result.variables] == ["GPS__Latitude", "GPS__Longitude"]
    assert result.warnings == []


def test_a_chunked_read_splits_every_chunk_the_same_way():
    """A column split in one chunk and not the next gives the file two schemas.

    The streaming reader decides off the first chunk, so a later chunk in which
    nothing parses still has to come out with the same columns.
    """
    from app.services.ingest import add_geopoint_columns, geopoint_columns

    first = pd.DataFrame(
        {"gps": [f"-17.73{n} 168.32{n} 42.0 5.0" for n in range(30, 36)]}
    )
    columns = geopoint_columns(first)
    assert columns == ["gps"]

    later = pd.DataFrame({"gps": [None, "no fix", None, "no fix", None, None]})
    add_geopoint_columns(later, columns, {})
    assert list(later.columns) == ["gps", "gps__latitude", "gps__longitude"]
    assert later["gps__latitude"].isna().all()


@pytest.mark.parametrize(
    "value",
    [
        # Two numbers in a string is not a location. A column of addresses
        # would otherwise be picked as the dataset's coordinates.
        "10.0.0.1",
        "192.168.1.1",
        "version 1.5 of 2.3",
        "-17.7333 / 168.3273",
        "lat -17.7333 lon 168.3273",
        # More numbers than a reading has.
        "1.1 2.2 3.3 4.4 5.5",
    ],
)
def test_text_that_merely_contains_two_numbers_is_not_a_location(value):
    from app.services.ingest import parse_geopoint

    assert parse_geopoint(value) is None


def test_a_column_of_addresses_is_not_taken_for_coordinates(tmp_path):
    """"10.0.0.1" holds two numbers in range and a decimal point."""
    from app.services.ingest import ingest_frame

    frame = pd.DataFrame(
        {"server": [f"10.0.0.{n}" for n in range(1, 9)]},
    )
    result = ingest_frame(frame, {}, {}, tmp_path / "out")
    assert [v.name for v in result.variables] == ["server"]


def test_a_pair_of_measurements_is_not_taken_for_coordinates(tmp_path):
    """A height and a weight are a legal coordinate and nonsense on a map.

    Syntax cannot tell them apart - both are two numbers with a separator - so
    precision does: a device reading is good to metres and carries the decimals
    to prove it, and a measurement written down by hand does not.
    """
    from app.services.ingest import ingest_frame

    frame = pd.DataFrame(
        {
            "height_weight": [
                "1.75 68.5",
                "1.62 55.0",
                "1.80 74.2",
                "1.58 49.8",
                "1.71 63.1",
                "1.69 58.4",
            ]
        }
    )
    result = ingest_frame(frame, {}, {}, tmp_path / "out")
    assert [v.name for v in result.variables] == ["height_weight"]


def test_unreadable_values_at_the_top_of_a_column_do_not_hide_it(tmp_path):
    """Whether a column is coordinates cannot depend on how the rows are sorted.

    A round that opens with a few devices that never got a fix is still a
    column of coordinates, and the share threshold is what should decide.
    """
    from app.services.ingest import ingest_frame

    frame = pd.DataFrame(
        {
            "gps": ["no fix", "no fix", "no fix"]
            + [f"-17.73{n} 168.32{n} 42.0 5.0" for n in range(1000, 1060)]
        }
    )
    result = ingest_frame(frame, {}, {}, tmp_path / "out")
    by_name = {v.name: v for v in result.variables}
    assert "gps__latitude" in by_name
    # The three that could not be read have no coordinates, not a zero pair.
    assert by_name["gps__latitude"].n_missing == 3
