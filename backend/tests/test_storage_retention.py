"""Restore-point limits and safe removal of dataset files nothing needs.

Every refresh keeps the version it replaced, and nothing used to remove them;
a failed or abandoned import could also leave files behind. These pin what
the clean-up may and may not do:

- it never removes a file a dataset reads now, a restore point that is still
  listed, or a file an import waiting for review will publish;
- restore points past the limit are let go oldest first, and the ones still
  listed can still be restored;
- unused files are left alone until they are older than the grace period;
- a dry run removes nothing and changes nothing;
- a dataset that changes during the clean-up is skipped, and a file that
  becomes needed between the check and the removal is kept;
- two clean-ups cannot run at once.

The restore-point limit is applied only to the datasets each test makes, so a
run here never lets go of restore points other tests are relying on.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path

import pandas as pd
import pytest

from app.core.config import settings
from app.services import storage_retention
from app.services.dataset_versions import list_versions
from tests.conftest import sign_in

GRACE = dt.timedelta(hours=1)
LONG_AGO = dt.datetime.now(dt.UTC) - dt.timedelta(days=3)


def _age(path: Path, when: dt.datetime = LONG_AGO) -> None:
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))


def _parquet(folder: Path, rows: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"data-{uuid.uuid4().hex}.parquet"
    pd.DataFrame({"x": list(range(rows))}).to_parquet(path, index=False)
    return path


def _record(folder: Path, version: int, parquet: Path, rows: int) -> Path:
    versions = folder / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    path = versions / f"{version}-{uuid.uuid4().hex}.json"
    path.write_text(
        json.dumps(
            {
                "version": version,
                "parquet_path": str(parquet),
                "row_count": rows,
                "column_count": 1,
                "file_size": parquet.stat().st_size,
                "variables": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def mine(monkeypatch):
    """The datasets this test made; the limit is applied to these only."""
    ids: set[str] = set()
    real = storage_retention.over_limit
    monkeypatch.setattr(
        storage_retention,
        "over_limit",
        lambda dataset, keep: real(dataset, keep) if dataset.id in ids else [],
    )
    return ids


@pytest.fixture
def make_dataset(client, db_session, mine):
    """A dataset at version ``restore_points + 1`` with one restore point per earlier version.

    Version n has n rows, so which version is current or restored is visible.
    Every file is made old, so only the grace period a test chooses protects it.
    """
    from app.models import Dataset, DatasetStatus

    def make(restore_points: int) -> Dataset:
        dataset_id = str(uuid.uuid4())
        folder = settings.datasets_path / dataset_id
        listed = []
        for version in range(1, restore_points + 1):
            parquet = _parquet(folder, version)
            record = _record(folder, version, parquet, version)
            _age(parquet)
            _age(record)
            listed.append(str(record))
        current = _parquet(folder, restore_points + 1)
        _age(current)
        dataset = Dataset(
            id=dataset_id,
            name=f"retention {dataset_id[:8]}",
            slug=f"retention-{dataset_id[:8]}",
            status=DatasetStatus.ready,
            storage_path=str(current),
            row_count=restore_points + 1,
            column_count=1,
            version=restore_points + 1,
            meta={"retained_versions": listed},
        )
        db_session.add(dataset)
        db_session.commit()
        mine.add(dataset_id)
        return dataset

    return make


def _fresh(dataset_id):
    from app.db.session import SessionLocal
    from app.models import Dataset

    with SessionLocal() as db:
        dataset = db.get(Dataset, dataset_id)
        return dataset, [v["version"] for v in list_versions(dataset)]


def _theirs(report, dataset_id):
    return [item for item in report.removable if item.dataset_id == dataset_id]


# --- The limit ---------------------------------------------------------------


def test_the_limit_lets_go_of_the_oldest_restore_points(make_dataset):
    dataset = make_dataset(5)
    assert [r.version for r in storage_retention.over_limit(dataset, 3)] == [2, 1]
    assert storage_retention.over_limit(dataset, 5) == []
    assert storage_retention.over_limit(dataset, 9) == []
    # 0 keeps every version.
    assert storage_retention.over_limit(dataset, 0) == []


def test_a_restore_point_whose_file_is_gone_is_not_counted(make_dataset):
    dataset = make_dataset(3)
    listed = dataset.meta["retained_versions"]
    oldest = json.loads(Path(listed[0]).read_text())
    Path(oldest["parquet_path"]).unlink()
    # The page doesn't show version 1 any more, so the limit of 2 is already met.
    assert storage_retention.over_limit(dataset, 2) == []


# --- Dry run ------------------------------------------------------------------


def test_a_dry_run_reports_and_changes_nothing(db_session, make_dataset):
    dataset = make_dataset(4)
    report = storage_retention.run(db_session, delete=False, keep=2, grace=GRACE)
    found = _theirs(report, dataset.id)
    assert {item.reason for item in found} == {storage_retention.LIMIT}
    # Versions 1 and 2: each a record and its data file.
    assert len(found) == 4
    assert all(Path(item.path).exists() for item in found)
    _, versions = _fresh(dataset.id)
    assert versions == [4, 3, 2, 1]
    assert storage_retention.latest()["deleted"] is False


# --- Removal ------------------------------------------------------------------


def test_removal_keeps_the_newest_restore_points_and_they_still_restore(
    client, auth_headers, db_session, make_dataset
):
    dataset = make_dataset(4)
    report = storage_retention.run(db_session, delete=True, keep=2, grace=GRACE)
    assert report.pruned_versions >= 2

    fresh, versions = _fresh(dataset.id)
    assert versions == [4, 3]
    # The current data is untouched.
    assert Path(fresh.storage_path).exists()
    # What was let go is gone from disk.
    gone = [p for p in (settings.datasets_path / dataset.id).rglob("*") if p.is_file()]
    assert len([p for p in gone if p.suffix == ".parquet"]) == 3  # current + versions 3 and 4

    response = client.post(
        f"/api/v1/datasets/{dataset.id}/versions/3/restore", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["row_count"] == 3


def test_the_data_a_dataset_reads_is_never_removed(db_session, make_dataset):
    dataset = make_dataset(0)
    storage_retention.run(db_session, delete=True, keep=1, grace=GRACE)
    assert Path(_fresh(dataset.id)[0].storage_path).exists()


def test_files_an_import_waiting_for_review_will_publish_are_kept(db_session, make_dataset):
    from app.models import Job, JobStatus, JobType

    dataset = make_dataset(0)
    folder = settings.datasets_path / dataset.id
    candidate = _parquet(folder, 99)
    _age(candidate)
    job = Job(
        id=str(uuid.uuid4()),
        title="Upload waiting for review",
        job_type=JobType.ingest,
        status=JobStatus.success,
        params={"candidates": [{"id": dataset.id, "snapshot": {"parquet_path": str(candidate)}}]},
        result={"review": True},
    )
    db_session.add(job)
    db_session.commit()

    report = storage_retention.run(db_session, delete=True, keep=1, grace=GRACE)
    assert candidate.exists()
    assert str(candidate) not in {item.path for item in report.removable}


def test_a_file_left_by_a_failed_import_is_removed_once_it_is_old_enough(
    db_session, make_dataset
):
    dataset = make_dataset(0)
    folder = settings.datasets_path / dataset.id
    old = _parquet(folder, 7)
    _age(old)
    new = _parquet(folder, 8)  # just written: could be an import still running

    report = storage_retention.run(db_session, delete=True, keep=1, grace=GRACE)
    assert not old.exists()
    assert new.exists()
    assert report.recent_unused_files >= 1
    removed = {item.path: item.reason for item in report.removable}
    assert removed[str(old)] == storage_retention.UNUSED


def test_a_version_record_that_was_never_kept_is_removed(db_session, make_dataset):
    dataset = make_dataset(1)
    folder = settings.datasets_path / dataset.id
    # What a rolled-back import leaves: a record nobody lists.
    stray = _record(folder, 2, Path(dataset.storage_path), 2)
    _age(stray)

    report = storage_retention.run(db_session, delete=True, keep=5, grace=GRACE)
    assert not stray.exists()
    assert {item.path: item.reason for item in report.removable}[str(stray)] == (
        storage_retention.UNLISTED
    )
    assert _fresh(dataset.id)[1] == [1]


def test_the_folder_of_a_dataset_that_no_longer_exists_is_removed(client, db_session):
    folder = settings.datasets_path / str(uuid.uuid4())
    parquet = _parquet(folder, 3)
    summary = folder / "monitoring-summary.json"
    summary.write_text("{}")
    for path in (parquet, summary):
        _age(path)

    report = storage_retention.run(db_session, delete=True, keep=5, grace=GRACE)
    assert not folder.exists()
    assert {item.path: item.reason for item in report.removable}[str(parquet)] == (
        storage_retention.GONE
    )


# --- Concurrency --------------------------------------------------------------


def test_a_dataset_changed_during_the_clean_up_is_skipped(db_session, make_dataset):
    from app.db.session import SessionLocal
    from app.models import Dataset

    dataset = make_dataset(3)
    # The clean-up has read the dataset...
    db_session.get(Dataset, dataset.id)
    # ...and an import commits a new version before it saves.
    with SessionLocal() as other:
        row = other.get(Dataset, dataset.id)
        row.version = row.version + 1
        other.commit()

    report = storage_retention.Report(
        checked_at="", deleted=True, keep_versions=1, grace_hours=1
    )
    released = storage_retention._prune_lists(db_session, 1, report)
    assert dataset.id in report.skipped_changed
    assert released == set()
    assert len(_fresh(dataset.id)[0].meta["retained_versions"]) == 3


def test_a_file_that_becomes_needed_before_removal_is_kept(db_session, make_dataset, monkeypatch):
    from app.db.session import SessionLocal
    from app.models import Dataset

    dataset = make_dataset(0)
    folder = settings.datasets_path / dataset.id
    left = _parquet(folder, 5)
    _age(left)

    real_plan = storage_retention.plan

    def plan_then_an_import_commits(*args, **kwargs):
        found = real_plan(*args, **kwargs)
        # Between the check and the removal, an import publishes that file.
        with SessionLocal() as other:
            row = other.get(Dataset, dataset.id)
            row.storage_path = str(left)
            row.version = row.version + 1
            other.commit()
        return found

    monkeypatch.setattr(storage_retention, "plan", plan_then_an_import_commits)
    db_session.expire_all()
    storage_retention.run(db_session, delete=True, keep=1, grace=GRACE)
    assert left.exists()


def test_two_clean_ups_cannot_run_at_once(client, db_session):
    from app.db.session import SessionLocal
    from app.services.operation_lock import acquire

    holder = SessionLocal()
    try:
        acquire(holder, "storage-cleanup")
        with pytest.raises(storage_retention.CleanupBusy):
            storage_retention.run(db_session, delete=True, keep=1, grace=GRACE)
    finally:
        holder.rollback()
        holder.close()


# --- Usage and the admin endpoints ---------------------------------------------


def test_usage_counts_current_data_and_restore_points(db_session, make_dataset):
    dataset = make_dataset(2)
    usage = storage_retention.usage(db_session)
    assert usage["restore_point_bytes"] > 0
    assert usage["current_bytes"] > 0
    assert usage["datasets_bytes"] >= usage["current_bytes"] + usage["restore_point_bytes"]
    assert storage_retention.disk()["total_bytes"] > 0
    assert dataset.id in {row["id"] for row in usage["largest"]} or len(usage["largest"]) == 10


def test_storage_endpoints_are_for_administrators(client, auth_headers, db_session):
    report = client.post("/api/v1/system/storage/check", headers=auth_headers)
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["deleted"] is False
    assert body["cleanup_enabled"] is False
    assert {"removable_files", "removable_bytes", "usage", "disk"} <= set(body)
    assert client.get("/api/v1/system/storage", headers=auth_headers).status_code == 200

    from app.core.security import hash_password
    from app.models import Role, User

    db_session.add(
        User(
            email="storage-manager@example.org",
            username="storage-manager",
            full_name="Not An Admin",
            hashed_password=hash_password("Fieldwork-2026-manager"),
            role=Role.manager,
        )
    )
    db_session.commit()
    manager = sign_in(client, "storage-manager@example.org", "Fieldwork-2026-manager")
    for method, path in (
        ("get", "/api/v1/system/storage"),
        ("post", "/api/v1/system/storage/check"),
        ("post", "/api/v1/system/storage/cleanup"),
    ):
        assert getattr(client, method)(path, headers=manager).status_code == 403, path


def test_removing_now_is_recorded_in_the_audit_log(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.models import AuditLog

    response = client.post("/api/v1/system/storage/cleanup", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
    entry = db_session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "storage_cleanup")
        .order_by(AuditLog.created_at.desc())
    )
    assert entry is not None
