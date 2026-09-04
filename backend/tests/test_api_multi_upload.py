"""Several export archives appended into one set of datasets.

A questionnaire revised mid-fieldwork exports as separate versions holding the
same member file names. The analyst's usual answer is a do-file that stamps a
version on each and appends them file by file; this is that, in one upload.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest


def _archive(version: int, rows: int, *, with_late_variable: bool) -> bytes:
    """One export: an interview file and a roster, as a zip of .dta members."""
    interview = pd.DataFrame(
        {
            "interview__key": [f"{version}{i:04d}" for i in range(rows)],
            "province": [(i % 6) + 1 for i in range(rows)],
        }
    )
    if with_late_variable:
        interview["internet_access"] = [i % 2 for i in range(rows)]
    roster = pd.DataFrame(
        {
            "interview__key": [f"{version}{i:04d}" for i in range(rows) for _ in range(2)],
            "age": [(i * 7) % 80 for i in range(rows * 2)],
        }
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, frame in (("VN_LFS.dta", interview), ("R_members.dta", roster)):
            member = io.BytesIO()
            frame.to_stata(member, write_index=False, version=118)
            archive.writestr(name, member.getvalue())
    return buffer.getvalue()


@pytest.fixture
def project(client, auth_headers) -> str:
    created = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Versions"}
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    yield project_id
    client.delete(
        f"/api/v1/projects/{project_id}", headers=auth_headers, params={"contents": "delete"}
    )


def test_three_versions_become_one_dataset_per_member_file(client, auth_headers, project):
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("VANLFS_v11.zip", _archive(11, 8, with_late_variable=True), "application/zip")),
            ("file", ("VANLFS_v10.zip", _archive(10, 5, with_late_variable=True), "application/zip")),
            ("file", ("VANLFS_v9.zip", _archive(9, 3, with_late_variable=False), "application/zip")),
        ],
        data={
            "mode": "replace",
            "project_id": project,
            "labels": '["11", "10", "9"]',
            "version_column": "version",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()

    by_name = {d["name"]: d for d in body["datasets"]}
    assert set(by_name) == {"VN_LFS", "R_members"}
    # 8 + 5 + 3 interviews in one dataset, and twice that in the roster.
    assert by_name["VN_LFS"]["row_count"] == 16
    assert by_name["R_members"]["row_count"] == 32

    # The version that arrived without the later variable is reported, not
    # silently dropped or refused.
    assert any("internet_access" in warning for warning in body["warnings"])

    dataset_id = by_name["VN_LFS"]["id"]
    counted = client.post(
        "/api/v1/analytics/query",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "spec": {
                "dimensions": [{"variable": "version"}],
                "measures": [{"agg": "count", "alias": "n"}],
                "limit": 50,
            },
        },
    )
    assert counted.status_code == 200, counted.text
    assert {str(row[0]): row[1] for row in counted.json()["rows"]} == {
        "11": 8,
        "10": 5,
        "9": 3,
    }


def test_the_stamp_never_overwrites_a_variable_of_its_own_name(
    client, auth_headers, project
):
    """"province" is an answer. Stamping over it would lose data silently."""
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("v11.zip", _archive(11, 4, with_late_variable=True), "application/zip")),
        ],
        data={
            "project_id": project,
            "labels": '["11"]',
            "version_column": "province",
        },
    )
    assert response.status_code == 201, response.text
    assert any("province" in warning for warning in response.json()["warnings"])

    dataset_id = next(
        d["id"] for d in response.json()["datasets"] if d["name"] == "VN_LFS"
    )
    values = client.post(
        "/api/v1/analytics/query",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "spec": {
                "dimensions": [{"variable": "province"}],
                "measures": [{"agg": "count", "alias": "n"}],
                "limit": 50,
            },
        },
    ).json()
    assert {str(row[0]) for row in values["rows"]} != {"11"}, "the answers were stamped over"


def test_several_files_have_to_be_archives(client, auth_headers, project):
    """Appending a spreadsheet onto an export is a different request."""
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("v11.zip", _archive(11, 2, with_late_variable=True), "application/zip")),
            ("file", ("notes.csv", b"a,b\n1,2\n", "text/csv")),
        ],
        data={"project_id": project},
    )
    assert response.status_code == 422, response.text


def test_labels_must_line_up_with_the_files(client, auth_headers, project):
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("v11.zip", _archive(11, 2, with_late_variable=True), "application/zip")),
            ("file", ("v10.zip", _archive(10, 2, with_late_variable=True), "application/zip")),
        ],
        data={"project_id": project, "labels": '["11"]', "version_column": "version"},
    )
    assert response.status_code == 422, response.text
