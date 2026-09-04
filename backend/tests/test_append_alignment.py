"""Appended rows land in the columns they belong to.

The dataset a file is appended to holds cleaned column names, because ingest
cleans them on the way in. The incoming file's names are whatever the file
says. Lining the two up without putting them in the same namespace first makes
pandas treat one variable as two - the old rows under one name, the new rows
under another - which is what "the column shows data from another column"
looks like from the outside.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from app.services.ingest import clean_columns


def test_cleaning_puts_both_frames_in_one_namespace():
    stored = pd.DataFrame({"a b": [1, 2]})  # as ingest wrote it
    incoming = pd.DataFrame({"a\nb": [9]})  # as the file has it

    naive = pd.concat([stored, incoming], ignore_index=True, sort=False)
    assert list(naive.columns) == ["a b", "a\nb"], "the bug this guards against"

    fixed = pd.concat([stored, clean_columns(incoming)], ignore_index=True, sort=False)
    assert list(fixed.columns) == ["a b"]
    assert fixed["a b"].tolist() == [1, 2, 9]


def test_cleaning_leaves_ordinary_names_alone():
    frame = pd.DataFrame({"province": [1], "hh_size": [2]})
    assert clean_columns(frame) is frame


def _archive(rows: int, *, column: str, offset: int = 0) -> bytes:
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i + offset}" for i in range(rows)],
            column: [i + offset for i in range(rows)],
        }
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        member = io.BytesIO()
        frame.to_stata(member, write_index=False, version=118)
        archive.writestr("VN_LFS.dta", member.getvalue())
    return buffer.getvalue()


@pytest.fixture
def project(client, auth_headers) -> str:
    created = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Append alignment"}
    )
    project_id = created.json()["id"]
    yield project_id
    client.delete(
        f"/api/v1/projects/{project_id}", headers=auth_headers, params={"contents": "delete"}
    )


def test_appended_rows_stay_in_their_own_columns(client, auth_headers, project):
    """End to end: append twice and every value is still under its own name."""
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("v2.zip", _archive(3, column="hh_size"), "application/zip")),
            ("file", ("v1.zip", _archive(2, column="hh_size", offset=100), "application/zip")),
        ],
        data={"project_id": project, "labels": '["2", "1"]', "version_column": "version"},
    )
    assert response.status_code == 201, response.text
    dataset_id = next(
        d["id"] for d in response.json()["datasets"] if d["name"] == "VN_LFS"
    )

    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    names = [v["name"] for v in detail["variables"]]
    # One column per variable: no "hh_size" alongside a second copy of itself.
    assert names.count("hh_size") == 1
    assert names.count("interview__key") == 1
    assert detail["row_count"] == 5

    rows = client.get(
        f"/api/v1/datasets/{dataset_id}/preview", headers=auth_headers, params={"limit": 50}
    ).json()["rows"]
    at = {name: index for index, name in enumerate(rows and detail["variables"] and
          [v["name"] for v in detail["variables"]])}
    # Every row has a key and a size; none is blank because its value went to
    # another column.
    for row in rows:
        assert row[at["interview__key"]] not in (None, "")
        assert row[at["hh_size"]] is not None


def test_a_changed_coding_is_reported_rather_than_applied_silently(
    client, auth_headers, project
):
    """A revised questionnaire can reuse a code for a different answer."""

    def archive(mapping: dict[int, str]) -> bytes:
        frame = pd.DataFrame({"interview__key": ["a", "b"], "status": [1, 2]})
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            member = io.BytesIO()
            frame.to_stata(
                member,
                write_index=False,
                version=118,
                value_labels={"status": mapping},
            )
            bundle.writestr("VN_LFS.dta", member.getvalue())
        return buffer.getvalue()

    first = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[("file", ("v2.zip", archive({1: "Employed", 2: "Unemployed"}), "application/zip"))],
        data={"project_id": project},
    )
    assert first.status_code == 201, first.text

    # The same codes, meaning the opposite thing.
    second = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[("file", ("v1.zip", archive({1: "Unemployed", 2: "Employed"}), "application/zip"))],
        data={"project_id": project, "mode": "append"},
    )
    assert second.status_code == 201, second.text
    warnings = " ".join(second.json()["warnings"])
    assert "labels the same codes differently" in warnings, warnings
    assert "status" in warnings


def test_two_archives_leave_one_row_per_variable(client, auth_headers, project):
    """The duplicate-metadata bug, which is what made columns look swapped.

    Both archives are imported in one transaction, and the variable rows used
    to be deleted through the dataset's own collection - which still held the
    first pass's objects from before they were flushed. The second pass deleted
    nothing and added a second row for every variable.
    """
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("a.zip", _archive(3, column="hh_size"), "application/zip")),
            ("file", ("b.zip", _archive(2, column="hh_size", offset=50), "application/zip")),
        ],
        data={"project_id": project, "labels": '["2", "1"]', "version_column": "version"},
    )
    assert response.status_code == 201, response.text
    dataset_id = next(d["id"] for d in response.json()["datasets"] if d["name"] == "VN_LFS")

    variables = client.get(
        f"/api/v1/datasets/{dataset_id}/variables", headers=auth_headers
    ).json()
    names = [v["name"] for v in variables]
    assert len(names) == len(set(names)), f"a variable is listed more than once: {names}"
    # And the positions are a clean run, not two interleaved sets.
    assert sorted(v["position"] for v in variables) == list(range(len(variables)))
