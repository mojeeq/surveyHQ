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
