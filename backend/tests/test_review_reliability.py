"""Regression tests for statistics, atomic publication, review, and recovery."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import Dataset
from app.schemas.query import Aggregation, Measure
from app.services.query_engine import _chi_square


def test_cramers_v_is_invariant_under_transpose():
    first = _chi_square([[10, 0, 0], [0, 5, 5]], [10, 10], [10, 5, 5], 20)
    second = _chi_square([[10, 0], [0, 5], [0, 5]], [10, 5, 5], [10, 10], 20)
    assert first["cramers_v"] == second["cramers_v"] == 1.0


@pytest.mark.parametrize(
    "agg", ["median", "p25", "p75", "p90", "stddev", "count_distinct", "min", "max"]
)
def test_unsupported_weights_are_rejected(agg):
    with pytest.raises(ValidationError, match="Survey weights are not supported"):
        Measure(agg=Aggregation(agg), variable="income", weight="weight")


def upload(client, headers, csv=b"id,value\n1,10\n2,20\n"):
    response = client.post(
        "/api/v1/datasets/upload",
        headers=headers,
        files={"file": ("version-check.csv", csv)},
        data={"name": "Version check"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_failure_after_file_write_preserves_committed_data(
    client, auth_headers, monkeypatch, tmp_path
):
    from app.services import datasets
    from app.services.ingest import IngestError

    original = upload(client, auth_headers)
    with SessionLocal() as db:
        dataset = db.get(Dataset, original["id"])
        old_path = dataset.storage_path
        old_bytes = Path(old_path).read_bytes()
        original_ingest = datasets.ingest_file

        def fail_after_write(source, destination):
            original_ingest(source, destination)
            raise IngestError("simulated disk/metadata failure")

        monkeypatch.setattr(datasets, "ingest_file", fail_after_write)
        source = tmp_path / "incoming.csv"
        source.write_text("id,value\n1,99\n")
        with pytest.raises(IngestError):
            datasets.load_file_into_dataset(db, dataset, source)
        db.commit()
        assert dataset.storage_path == old_path
        assert dataset.status.value == "ready"
        assert Path(old_path).read_bytes() == old_bytes


def test_successful_update_retains_restorable_version(client, auth_headers):
    original = upload(client, auth_headers)
    ident = original["id"]
    updated = client.post(
        f"/api/v1/datasets/{ident}/replace",
        headers=auth_headers,
        files={"file": ("new.csv", b"id,value\n3,30\n")},
    )
    assert updated.status_code == 200, updated.text
    versions = client.get(f"/api/v1/datasets/{ident}/versions", headers=auth_headers).json()
    assert any(v["version"] == original["version"] and v["rows"] == 2 for v in versions)
    restored = client.post(
        f"/api/v1/datasets/{ident}/versions/{original['version']}/restore", headers=auth_headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["row_count"] == 2
    assert restored.json()["version"] > updated.json()["version"]


def archive(csv):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("household.csv", csv)
    return out.getvalue()


def review(client, headers, monkeypatch, project, csv):
    from app.workers.tasks import run_upload_import

    monkeypatch.setattr(run_upload_import, "delay", lambda *args: SimpleNamespace(id="queued-test"))
    response = client.post(
        "/api/v1/datasets/upload",
        headers=headers,
        files={"file": ("survey.zip", archive(csv))},
        data={"review": "true", "project_id": project},
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    result = run_upload_import.run(job_id)
    assert result.get("review"), result
    return job_id, result


def test_review_does_not_publish_until_accepted(client, auth_headers, monkeypatch):
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Review project"}
    ).json()["id"]
    job, result = review(client, auth_headers, monkeypatch, project, "id,value\n1,10\n1,10\n")
    assert result["changes"][0]["duplicate_rows"] == 1
    assert (
        client.get(f"/api/v1/datasets?project_id={project}", headers=auth_headers).json()["total"]
        == 0
    )
    response = client.post(f"/api/v1/datasets/reviews/{job}/accept", headers=auth_headers)
    assert response.status_code == 200, response.text
    ident = response.json()["datasets"][0]["id"]
    assert client.get(f"/api/v1/datasets/{ident}", headers=auth_headers).json()["row_count"] == 2
    assert (
        client.post(f"/api/v1/datasets/reviews/{job}/accept", headers=auth_headers).status_code
        == 409
    )
    with SessionLocal() as db:
        dataset = db.get(Dataset, ident)
        assert Path(dataset.storage_path).parent.name == ident


def test_stale_review_is_refused_without_overwriting_newer_data(client, auth_headers, monkeypatch):
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Stale review project"}
    ).json()["id"]
    first, _ = review(client, auth_headers, monkeypatch, project, "id,value\n1,10\n")
    ident = client.post(f"/api/v1/datasets/reviews/{first}/accept", headers=auth_headers).json()[
        "datasets"
    ][0]["id"]
    staged, changes = review(client, auth_headers, monkeypatch, project, "id,amount\n1,20\n")
    assert changes["changes"][0]["removed_variables"] == ["value"]
    replaced = client.post(
        f"/api/v1/datasets/{ident}/replace",
        headers=auth_headers,
        files={"file": ("new.csv", b"id,value\n1,99\n2,88\n")},
    )
    assert replaced.status_code == 200, replaced.text
    response = client.post(f"/api/v1/datasets/reviews/{staged}/accept", headers=auth_headers)
    assert response.status_code == 409
    assert client.get(f"/api/v1/datasets/{ident}", headers=auth_headers).json()["row_count"] == 2


def test_project_lock_spans_transaction_and_releases_after_rollback(client):
    from app.services.operation_lock import OperationBusy, acquire

    with SessionLocal() as first, SessionLocal() as second:
        acquire(first, "test-project")
        with pytest.raises(OperationBusy):
            acquire(second, "test-project")
        first.rollback()
        acquire(second, "test-project")


def test_migration_adopts_populated_legacy_database(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from app.db.base import Base
    from app.db.migrations import require_current, upgrade

    bind = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(bind)
    with bind.begin() as con:
        con.execute(
            text(
                "INSERT INTO users (id,email,username,full_name,hashed_password,role,is_active,must_change_password,restricted_to_projects) VALUES ('legacy','legacy@example.org','legacy','Legacy','unused','viewer',1,0,0)"
            )
        )
        con.execute(text("DROP INDEX ix_users_username"))
        con.execute(text("ALTER TABLE users DROP COLUMN username"))
    with pytest.raises(RuntimeError, match="migration required"):
        require_current(bind)
    upgrade(bind)
    require_current(bind)
    with bind.connect() as con:
        assert (
            con.execute(text("SELECT username FROM users WHERE id='legacy'")).scalar() == "legacy"
        )
    assert "ix_users_username" in {i["name"] for i in inspect(bind).get_indexes("users")}
    upgrade(bind)
    bind.dispose()


def test_queued_r_run_retains_code_and_result(client, auth_headers, monkeypatch):
    from types import SimpleNamespace

    from app.models import Job
    from app.services import rproject
    from app.workers.tasks import run_project_r

    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Queued R"}
    ).json()["id"]
    monkeypatch.setattr(rproject, "unavailable_reason", lambda: "")
    monkeypatch.setattr(run_project_r, "delay", lambda *args: SimpleNamespace(id="test-r-task"))
    queued = client.post(
        f"/api/v1/projects/{project}/queue-run", headers=auth_headers, json={"code": "print(42)"}
    )
    assert queued.status_code == 202, queued.text
    ident = queued.json()["id"]
    monkeypatch.setattr(
        rproject,
        "_run",
        lambda *args, **kwargs: rproject.ProjectRResult(
            message="Ran", output="42", written=[], files=[], environment=[]
        ),
    )
    result = run_project_r.run(ident)
    assert result["output"] == "42"
    with SessionLocal() as db:
        job = db.get(Job, ident)
        assert job.status.value == "success"
        assert job.params["code"] == "print(42)"
    directory = rproject.get_settings().storage_path / "r-runs" / project
    assert len(list(directory.glob("*/script.R"))) == 1
    assert len(list(directory.glob("*/run.json"))) == 1


def test_database_rollback_never_changes_the_active_file(client, auth_headers, tmp_path):
    from app.services.datasets import load_file_into_dataset

    original = upload(client, auth_headers)
    source = tmp_path / "new.csv"
    source.write_text("id,value\n3,99\n")
    with SessionLocal() as db:
        dataset = db.get(Dataset, original["id"])
        committed_path = dataset.storage_path
        load_file_into_dataset(db, dataset, source)
        assert dataset.storage_path != committed_path
        db.rollback()
        db.refresh(dataset)
        assert dataset.storage_path == committed_path
        assert dataset.row_count == 2
        assert not (dataset.meta or {}).get("retained_versions")
