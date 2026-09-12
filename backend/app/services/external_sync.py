"""Background import path for non-Survey-Solutions connections."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.crypto import decrypt
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import (
    Connection,
    Dataset,
    DatasetSource,
    Job,
    JobStatus,
    SyncRun,
    SyncStatus,
)
from app.services import rproject
from app.services.archives import SOURCE_COLUMN
from app.services.datasets import (
    append_frame_into_dataset,
    create_dataset_record,
    dataset_is_queryable,
    load_file_into_dataset,
)
from app.services.derived import rebuild_dependents
from app.services.external_sources import ExternalSourceClient, RemoteTable, SourceError, source_label
from app.services.ingest import IngestError

logger = get_logger(__name__)


def _dataset_source(source_type: str) -> DatasetSource:
    try:
        return DatasetSource(source_type)
    except ValueError as exc:
        raise SourceError(f"Unsupported dataset source '{source_type}'") from exc


def _existing_dataset(db: Any, connection_id: str, source_ref: str) -> Dataset | None:
    return db.scalar(
        select(Dataset).where(
            Dataset.connection_id == connection_id,
            Dataset.source_ref == source_ref,
        )
    )


def _write_table(
    *,
    db: Any,
    connection: Connection,
    table: RemoteTable,
    project_id: str | None,
    created_by: str | None,
    mode: str,
    workdir: Path,
) -> tuple[Dataset, bool]:
    """Create/refresh one SurveyHQ dataset from an adapter table.

    Returns the dataset plus whether this was a newly-created record.
    """
    frame = table.frame.copy()
    if len(frame.columns) == 0:
        raise IngestError(f"'{table.name}' contains no columns")
    frame[SOURCE_COLUMN] = table.source_ref

    dataset = _existing_dataset(db, connection.id, table.source_ref)
    created = dataset is None
    if dataset is None:
        dataset = create_dataset_record(
            db,
            name=table.name,
            description=f"Imported from {source_label(connection.source_type)}",
            source=_dataset_source(connection.source_type),
            source_ref=table.source_ref,
            connection_id=connection.id,
            created_by=created_by,
            project_id=project_id,
            tags=[connection.source_type],
        )
    else:
        # A connection can be moved between projects. Its next refresh should
        # carry its own datasets with it rather than leaving stale copies behind.
        dataset.project_id = project_id
        dataset.connection_id = connection.id
        dataset.source = _dataset_source(connection.source_type)
        dataset.source_ref = table.source_ref
        tags = list(dataset.tags or [])
        if connection.source_type not in tags:
            tags.append(connection.source_type)
            dataset.tags = tags

    meta = dict(dataset.meta or {})
    meta["remote_source"] = {
        "type": connection.source_type,
        "connection_id": connection.id,
        "resource": table.source_ref,
    }
    dataset.meta = meta

    if mode == "append" and not created and dataset_is_queryable(dataset):
        append_frame_into_dataset(db, dataset, frame, {}, {})
    else:
        # The file ingestion path is the one place SurveyHQ applies column-name
        # cleaning, type inference, metadata profiling and Parquet writing. API
        # connectors deliberately go through it too, so an ODK form and a Stata
        # upload behave identically once they become a dataset.
        csv_path = workdir / f"{dataset.id}.csv"
        frame.to_csv(csv_path, index=False)
        load_file_into_dataset(db, dataset, csv_path)

    return dataset, created


def run_external_connection_sync(job_id: str, task_id: str = "") -> dict[str, Any]:
    """Pull selected resources through one external adapter and ingest them."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return {"error": "job not found"}
        params = dict(job.params or {})
        connection_id = str(params.get("connection_id") or "")
        connection = db.get(Connection, connection_id)
        if connection is None:
            job.status = JobStatus.failed
            job.error = "The connection no longer exists"
            job.finished_at = utcnow()
            return {"error": job.error}
        job.status = JobStatus.running
        job.started_at = utcnow()
        job.celery_task_id = task_id
        connection.last_sync_status = SyncStatus.running
        source_type = connection.source_type or "survey_solutions"
        credentials = {
            "source_type": source_type,
            "base_url": connection.base_url,
            "workspace": connection.workspace,
            "username": connection.username,
            "secret": decrypt(connection.password_encrypted),
            "verify_ssl": connection.verify_ssl,
            "config": dict(connection.source_config or {}),
        }
        connection_name = connection.name
        project_id = params.get("project_id") or connection.project_id
        created_by = job.created_by
        resources = list(params.get("questionnaires") or connection.questionnaires or [])
        mode = str(params.get("mode") or "replace")

    summary: dict[str, Any] = {"datasets": [], "errors": [], "rows": 0}
    workdir = Path(tempfile.mkdtemp(prefix="surveyhq-source-sync-"))
    try:
        with ExternalSourceClient(**credentials) as client:
            catalogue = {resource.identity: resource for resource in client.list_resources()}
            # A configured SDMX query can be too specific to appear in dataflow
            # discovery. Selected identities are therefore always honoured even
            # when the catalogue cannot name them.
            for identity in resources:
                resource = catalogue.get(identity)
                title = resource.title if resource else identity
                with session_scope() as db:
                    run = SyncRun(
                        connection_id=connection_id,
                        questionnaire=title,
                        status=SyncStatus.running,
                        started_at=utcnow(),
                    )
                    db.add(run)
                    db.flush()
                    run_id = run.id

                try:
                    tables = client.pull(identity)
                    if not tables:
                        raise SourceError(f"'{title}' returned no tables")
                    touched: list[str] = []
                    rows = 0
                    created_count = 0
                    log: list[str] = []
                    with session_scope() as db:
                        connection = db.get(Connection, connection_id)
                        if connection is None:
                            raise SourceError("The connection was deleted during the import")
                        for table in tables:
                            dataset, created = _write_table(
                                db=db,
                                connection=connection,
                                table=table,
                                project_id=project_id,
                                created_by=created_by,
                                mode=mode,
                                workdir=workdir,
                            )
                            touched.append(dataset.id)
                            rows += int(dataset.row_count or 0) if mode == "replace" else len(table.frame)
                            created_count += int(created)
                            log.append(
                                f"{'Created' if created else 'Refreshed'} {dataset.name}: "
                                f"{len(table.frame):,} incoming row(s)"
                            )
                            summary["datasets"].append(
                                {
                                    "id": dataset.id,
                                    "name": dataset.name,
                                    "rows": dataset.row_count,
                                    "source": source_type,
                                }
                            )
                        rebuilt = rebuild_dependents(db, touched)
                        if rebuilt:
                            log.append(f"{len(rebuilt)} merged dataset(s) rebuilt")
                        replay = rproject.run_on_import(db, project_id, created_by)
                        log.extend(replay or [])

                    summary["rows"] += rows
                    with session_scope() as db:
                        run = db.get(SyncRun, run_id)
                        if run:
                            run.status = SyncStatus.success
                            run.finished_at = utcnow()
                            run.rows_imported = rows
                            run.datasets_created = created_count
                            run.message = (
                                f"Imported {rows:,} row(s) from {title} into "
                                f"{len(tables)} dataset(s)"
                            )
                            run.log = log
                except (SourceError, IngestError, ValueError) as exc:
                    logger.error("%s sync failed for %s: %s", source_type, identity, exc)
                    summary["errors"].append({"resource": title, "error": str(exc)})
                    with session_scope() as db:
                        run = db.get(SyncRun, run_id)
                        if run:
                            run.status = SyncStatus.failed
                            run.finished_at = utcnow()
                            run.message = str(exc)

        with session_scope() as db:
            connection = db.get(Connection, connection_id)
            if connection:
                connection.last_sync_at = utcnow()
                connection.last_sync_status = (
                    SyncStatus.failed if summary["errors"] else SyncStatus.success
                )
                connection.last_sync_error = (
                    summary["errors"][0]["error"] if summary["errors"] else ""
                )
            job = db.get(Job, job_id)
            if job:
                job.status = (
                    JobStatus.failed
                    if summary["errors"] and not summary["datasets"]
                    else JobStatus.success
                )
                job.finished_at = utcnow()
                job.progress = 100.0
                job.result = summary
                if summary["errors"]:
                    job.error = summary["errors"][0]["error"]
        return summary
    except Exception as exc:  # noqa: BLE001 - background jobs must record the reason
        logger.exception("External source job %s failed", job_id)
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job:
                job.status = JobStatus.failed
                job.finished_at = utcnow()
                job.error = str(exc)
            connection = db.get(Connection, connection_id)
            if connection:
                connection.last_sync_status = SyncStatus.failed
                connection.last_sync_error = str(exc)
                connection.last_sync_at = utcnow()
        return {"error": str(exc)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
