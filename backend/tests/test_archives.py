"""Uploading a zip of Stata files and appending them into one dataset.

Several rounds of a survey arrive as several export archives. Analysing them one
file at a time is not the point: the useful object is one dataset covering every
round, with a column saying which file each row came from.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from app.services.archives import (
    SOURCE_COLUMN,
    combine,
    extract_members,
    group_by_schema,
    is_archive,
)
from app.services.ingest import IngestError


def _stata(path: Path, frame: pd.DataFrame) -> Path:
    frame.to_stata(path, write_index=False, version=118)
    return path


def _zip(path: Path, files: list[Path]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for file in files:
            archive.write(file, arcname=file.name)
    return path


@pytest.fixture
def two_rounds(tmp_path) -> Path:
    """Two files with identical columns, as consecutive rounds would be."""
    a = _stata(tmp_path / "round1.dta", pd.DataFrame({"id": [1, 2], "age": [30.0, 40.0]}))
    b = _stata(tmp_path / "round2.dta", pd.DataFrame({"id": [3, 4], "age": [50.0, 60.0]}))
    return _zip(tmp_path / "rounds.zip", [a, b])


def test_is_archive():
    assert is_archive(Path("x.zip"))
    assert not is_archive(Path("x.dta"))


def test_members_are_appended_with_their_source_file(two_rounds, tmp_path):
    members = extract_members(two_rounds, tmp_path / "work")
    assert {m.name for m in members} == {"round1.dta", "round2.dta"}

    result = combine(sorted(members, key=lambda m: m.name))
    assert len(result.frame) == 4
    # Every row can be traced back to the file it came from
    assert set(result.frame[SOURCE_COLUMN]) == {"round1.dta", "round2.dta"}
    assert sorted(result.frame["id"].tolist()) == [1, 2, 3, 4]


def test_survey_solutions_system_files_are_ignored(tmp_path):
    """An export ships action and error logs beside the data; they are not rounds."""
    data = _stata(tmp_path / "household.dta", pd.DataFrame({"id": [1], "age": [30.0]}))
    actions = _stata(
        tmp_path / "interview__actions.dta", pd.DataFrame({"id": [1], "action": [2.0]})
    )
    archive = _zip(tmp_path / "export.zip", [data, actions])

    members = extract_members(archive, tmp_path / "work")
    assert [m.name for m in members] == ["household.dta"]


def test_files_with_different_schemas_are_grouped_apart(tmp_path):
    """A zip is often roster levels, not rounds; appending them would be wrong."""
    person_a = _stata(tmp_path / "person1.dta", pd.DataFrame({"pid": [1], "age": [9.0]}))
    person_b = _stata(tmp_path / "person2.dta", pd.DataFrame({"pid": [2], "age": [8.0]}))
    household = _stata(tmp_path / "hh.dta", pd.DataFrame({"hhid": [1], "size": [4.0]}))
    archive = _zip(tmp_path / "mixed.zip", [person_a, person_b, household])

    groups = group_by_schema(extract_members(archive, tmp_path / "work"))
    assert len(groups) == 2
    # The largest matching group comes first, and it is the two person files
    assert sorted(m.name for m in groups[0]) == ["person1.dta", "person2.dta"]


def test_a_later_round_may_add_a_variable(tmp_path):
    """Appending on the union keeps every row; the unasked question stays blank."""
    a = _stata(tmp_path / "r1.dta", pd.DataFrame({"id": [1], "age": [30.0]}))
    b = _stata(
        tmp_path / "r2.dta", pd.DataFrame({"id": [2], "age": [40.0], "income": [100.0]})
    )
    archive = _zip(tmp_path / "grew.zip", [a, b])

    members = sorted(extract_members(archive, tmp_path / "work"), key=lambda m: m.name)
    result = combine(members)

    assert len(result.frame) == 2
    assert result.frame["income"].isna().sum() == 1
    assert any("income" in warning for warning in result.warnings)


def test_strict_combine_refuses_a_mismatch(tmp_path):
    a = _stata(tmp_path / "r1.dta", pd.DataFrame({"id": [1], "age": [30.0]}))
    b = _stata(tmp_path / "r2.dta", pd.DataFrame({"id": [2], "other": [1.0]}))
    archive = _zip(tmp_path / "bad.zip", [a, b])
    members = sorted(extract_members(archive, tmp_path / "work"), key=lambda m: m.name)

    with pytest.raises(IngestError, match="does not match"):
        combine(members, strict=True)


def test_an_archive_with_no_data_files_is_rejected(tmp_path):
    notes = tmp_path / "notes.pdf"
    notes.write_bytes(b"%PDF-1.4")
    archive = _zip(tmp_path / "empty.zip", [notes])

    with pytest.raises(IngestError, match="no data files"):
        extract_members(archive, tmp_path / "work")


def test_the_exports_own_readme_is_not_treated_as_a_round(tmp_path):
    """.txt is a data format here, so export__readme.txt would otherwise append."""
    data = _stata(tmp_path / "household.dta", pd.DataFrame({"id": [1], "age": [30.0]}))
    readme = tmp_path / "export__readme.txt"
    readme.write_text("This export was produced by Survey Solutions.")
    archive = _zip(tmp_path / "export.zip", [data, readme])

    members = extract_members(archive, tmp_path / "work")
    assert [m.name for m in members] == ["household.dta"]


def test_a_file_that_is_not_a_zip_is_rejected(tmp_path):
    fake = tmp_path / "not.zip"
    fake.write_bytes(b"definitely not a zip")
    with pytest.raises(IngestError, match="not a readable zip"):
        extract_members(fake, tmp_path / "work")


def test_member_names_cannot_escape_the_extraction_directory(tmp_path):
    """A crafted archive must not write outside where it is unpacked."""
    inner = _stata(tmp_path / "ok.dta", pd.DataFrame({"id": [1], "age": [30.0]}))
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(inner, arcname="../../escaped.dta")

    work = tmp_path / "work"
    members = extract_members(archive, work)
    # Only the basename is used, so the file lands inside the work directory
    assert [m.name for m in members] == ["escaped.dta"]
    assert members[0].path.resolve().parent == work.resolve()
    assert not (tmp_path.parent / "escaped.dta").exists()
