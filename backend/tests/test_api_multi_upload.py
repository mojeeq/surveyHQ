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


def _stata(name: str, rows: int) -> bytes:
    """One plain data file, the way a roster level leaves a census export."""
    frame = pd.DataFrame(
        {
            "interview__key": [f"{name}-{i:04d}" for i in range(rows)],
            "value": list(range(rows)),
        }
    )
    buffer = io.BytesIO()
    frame.to_stata(buffer, write_index=False, version=118)
    return buffer.getvalue()


def test_several_data_files_each_become_their_own_dataset(client, auth_headers, project):
    """A census round is several tables, not several rounds of one table.

    The household file, the person roster and the paradata leave Survey
    Solutions as separate .dta files. Appending them would be nonsense, so each
    gets its own dataset - and until this worked, choosing them together was
    refused outright and people were told to zip files the platform was about
    to unzip again.
    """
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("household.dta", _stata("hh", 9), "application/octet-stream")),
            ("file", ("roster_pp.dta", _stata("pp", 30), "application/octet-stream")),
            ("file", ("interview_actions.dta", _stata("ia", 4), "application/octet-stream")),
        ],
        data={"project_id": project},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    by_name = {d["name"]: d for d in body["datasets"]}
    # Named after themselves. One shared name would have been a collision, and
    # naming only the first leaves the others called nothing in particular.
    assert set(by_name) == {"household", "roster_pp", "interview_actions"}
    assert by_name["household"]["row_count"] == 9
    assert by_name["roster_pp"]["row_count"] == 30
    assert by_name["interview_actions"]["row_count"] == 4
    assert sorted(body["created"]) == ["household", "interview_actions", "roster_pp"]
    assert body["appended"] == [] and body["replaced"] == []
    assert body["rows"] == 43
    # Each lands in the project it was uploaded to. The shared area would
    # publish census microdata to every user on the platform.
    assert all(d["project_id"] == project for d in body["datasets"])


def test_one_data_file_still_answers_with_the_dataset_itself(client, auth_headers, project):
    """The single-file shape is what everything reading this route expects."""
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[("file", ("just_one.dta", _stata("one", 5), "application/octet-stream"))],
        data={"project_id": project, "name": "Named by hand"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "datasets" not in body
    assert body["name"] == "Named by hand"
    assert body["row_count"] == 5


def test_a_mixture_of_archives_and_data_files_is_refused(client, auth_headers, project):
    """Appending archives and making a dataset per file are different acts.

    A selection holding both has no single meaning, and guessing one would
    quietly do the other.
    """
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("export.zip", _archive(1, 3, with_late_variable=False), "application/zip")),
            ("file", ("stray.dta", _stata("s", 3), "application/octet-stream")),
        ],
        data={"project_id": project},
    )
    assert response.status_code == 422
    assert "mixture" in response.json()["detail"]


def test_a_version_column_on_data_files_is_refused_rather_than_ignored(
    client, auth_headers, project
):
    """It writes each file's label into the rows that file brought, so the
    rounds an append merged stay tellable apart. Nothing is merged here, so the
    column would be one constant per dataset - and silently writing it would
    teach somebody it had done something."""
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("a.dta", _stata("a", 3), "application/octet-stream")),
            ("file", ("b.dta", _stata("b", 3), "application/octet-stream")),
        ],
        data={"project_id": project, "labels": '["1", "2"]', "version_column": "version"},
    )
    assert response.status_code == 422
    assert "append" in response.json()["detail"]


def test_the_worker_fills_every_dataset_a_queued_upload_made(client, auth_headers, monkeypatch, project):
    """The path the interface actually uses.

    Every upload from the browser asks for a review, and a review is always
    handed to the worker - so the inline branch above is not what a person
    exercises. The worker carried one dataset id and read only the first file;
    with several, the rest would have been written to disk and then left as
    empty dataset records.
    """
    from types import SimpleNamespace

    from app.workers.tasks import run_upload_import

    monkeypatch.setattr(run_upload_import, "delay", lambda *a: SimpleNamespace(id="queued-test"))
    # Anything over the inline limit goes to the worker. Lowering it is how a
    # test reaches that branch without a 48 MB fixture.
    monkeypatch.setattr("app.api.v1.endpoints.datasets.INLINE_IMPORT_LIMIT", 1)
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("household.dta", _stata("hh", 7), "application/octet-stream")),
            ("file", ("roster_pp.dta", _stata("pp", 21), "application/octet-stream")),
        ],
        data={"project_id": project},
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]

    result = run_upload_import.run(job_id)
    reported = {d["name"]: d["rows"] for d in result["datasets"]}
    assert reported == {"household": 7, "roster_pp": 21}
    assert result["rows"] == 28


def test_a_queued_upload_from_the_previous_release_still_finishes(
    client, auth_headers, monkeypatch, project, db_session
):
    """A job queued before this change carries dataset_id and no dataset_ids.

    It is sitting in Redis across the deploy that introduces the list. Reading
    only the new key would fail it, and somebody's upload would be lost to a
    release note nobody read.
    """
    from types import SimpleNamespace

    from app.models import Job
    from app.workers.tasks import run_upload_import

    monkeypatch.setattr(run_upload_import, "delay", lambda *a: SimpleNamespace(id="queued-test"))
    monkeypatch.setattr("app.api.v1.endpoints.datasets.INLINE_IMPORT_LIMIT", 1)
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[("file", ("legacy.dta", _stata("lg", 6), "application/octet-stream"))],
        data={"project_id": project},
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]

    job = db_session.get(Job, job_id)
    job.params = {k: v for k, v in job.params.items() if k != "dataset_ids"}
    db_session.commit()

    result = run_upload_import.run(job_id)
    assert [d["rows"] for d in result["datasets"]] == [6]


def test_naming_one_dataset_while_uploading_several_is_refused(client, auth_headers, project):
    """Each file becomes its own dataset, so a single name fits none of them.

    Applying it to all would make several datasets sharing a name; applying it
    to the first is a coin toss; ignoring it teaches somebody it worked.
    """
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", ("a.dta", _stata("a", 3), "application/octet-stream")),
            ("file", ("b.dta", _stata("b", 3), "application/octet-stream")),
        ],
        data={"project_id": project, "name": "One name for all of them"},
    )
    assert response.status_code == 422
    assert "one at a time" in response.json()["detail"]
