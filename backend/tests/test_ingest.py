"""Reading survey files and deriving metadata."""

from __future__ import annotations

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
