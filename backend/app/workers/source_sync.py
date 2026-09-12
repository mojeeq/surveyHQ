"""Provider-neutral scheduled/manual sync for SurveyHQ data connections."""

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
from app.models import Connection, Dataset, DatasetSource, Job, JobStatus, SyncRun, SyncStatus
from app.services.archives import extract_members, is_archive
from app.services.datasets import (
    append_file_into_dataset,
    create_dataset_record,
    dataset_is_queryable,
    load_file_into_dataset,
)
from app.services.derived import rebuild_dependents
from app.services.ingest import IngestError
from app.services.scheduling import is_due
from app.services.source_connectors import (
    PROVIDER_LABELS,
    SourceConnectorError,
    SourceResource,
    make_connector,
)
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

ARCHIVES_KEPT = 5


def _provider(connection: Connection) -> str:
    return connection.provider or "survey_solutions"


def _source(connection: Connection):
    return make_connector(
        provider=_provider(connection),
        base_url=connection.base_url,
        username=connection.username,
        secret=(decrypt(connection.password_encrypted) if connection.password_encrypted else ""),
        workspace=connection.workspace,
        verify_ssl=connection.verify_ssl,
        source_config=dict(connection.source_config or {}),
    )


def source_files_path() -> Path:
    from app.core.config import settings

    path = settings.storage_path / "sync-archives"
    path.mkdir(parents=True, exist_ok=True)
    return path


def prune_source_files(connection_id: str, keep: int = ARCHIVES_KEPT) -> None:
    """Keep recent raw source files without letting scheduled imports fill disk."""
    with session_scope() as db:
        runs = db.scalars(
            select(SyncRun)
            .where(SyncRun.connection_id == connection_id, SyncRun.archive_path != "")
            .order_by(SyncRun.started_at.desc())
        ).all()
        for run in runs[keep:]:
            Path(run.archive_path).unlink(missing_ok=True)
            run.archive_path = ""


def _existing_dataset(
    db,
    *,
    connection_id: str,
    source_ref: str,
    project_id: str | None,
) -> Dataset | None:
    statement = select(Dataset).where(
        Dataset.connection_id == connection_id,
        Dataset.source_ref == source_ref,
    )
    statement = statement.where(
        Dataset.project_id.is_(None) if project_id is None else Dataset.project_id == project_id
    )
    return db.scalar(statement)


def _import_table(
    *,
    connection_id: str,
    provider: str,
    resource: SourceResource,
    path: Path,
    project_id: str | None,
    mode: str,
    member_name: str = "",
) -> tuple[Dataset, str, bool]:
    """Import one table, replacing the same connection/resource in place."""
    source_ref = resource.identity + (f"::{member_name}" if member_name else "")
    stem = Path(member_name).stem if member_name else resource.title
    display_name = (
        f"{resource.title} - {stem}" if member_name and stem != resource.title else resource.title
    )
    tag = provider.replace("_", "-")

    with session_scope() as db:
        dataset = _existing_dataset(
            db,
            connection_id=connection_id,
            source_ref=source_ref,
            project_id=project_id,
        )
        created = dataset is None
        before = dataset.row_count if dataset is not None else 0
        if dataset is None:
            dataset = create_dataset_record(
                db,
                name=display_name,
                description=(
                    f"Imported from {PROVIDER_LABELS.get(provider, provider)}: {resource.title}"
                ),
                source=DatasetSource.external,
                source_ref=source_ref,
                connection_id=connection_id,
                tags=[tag],
                project_id=project_id,
            )
            load_file_into_dataset(db, dataset, path)
            action = f"Created {dataset.name} ({dataset.row_count:,} rows)"
        elif mode == "append" and dataset_is_queryable(dataset):
            append_file_into_dataset(db, dataset, path, source_name=member_name or path.name)
            action = (
                f"Appended {dataset.row_count - before:,} rows to {dataset.name} "
                f"({dataset.row_count:,} total)"
            )
        else:
            load_file_into_dataset(db, dataset, path)
            rebuilt = rebuild_dependents(db, [dataset.id])
            action = (
                f"Refreshed {dataset.name} ({before:,} -> {dataset.row_count:,} rows)"
                + (f"; rebuilt {len(rebuilt)} derived dataset(s)" if rebuilt else "")
            )
        # Keep provenance authoritative even for records created by an older
        # release before DatasetSource.external existed.
        dataset.connection_id = connection_id
        dataset.source = DatasetSource.external
        dataset.source_ref = source_ref
        tags = list(dataset.tags or [])
        if tag not in tags:
            tags.append(tag)
        dataset.tags = tags
        db.flush()
        return dataset, action, created


def _import_external_file(
    *,
    connection_id: str,
    provider: str,
    resource: SourceResource,
    source_file: Path,
    project_id: str | None,
    mode: str,
    workdir: Path,
) -> dict[str, Any]:
    datasets: list[dict[str, Any]] = []
    log: list[str] = []
    created = 0
    rows = 0

    if is_archive(source_file):
        members = extract_members(source_file, workdir / f"extract-{resource.id}")
        for member in members:
            dataset, action, was_created = _import_table(
                connection_id=connection_id,
                provider=provider,
                resource=resource,
                path=member.path,
                project_id=project_id,
                mode=mode,
                member_name=member.name,
            )
            datasets.append({"id": dataset.id, "name": dataset.name, "rows": dataset.row_count})
            log.append(action)
            created += int(was_created)
            rows += dataset.row_count if mode == "replace" else len(member.frame)
    else:
        dataset, action, was_created = _import_table(
            connection_id=connection_id,
            provider=provider,
            resource=resource,
            path=source_file,
            project_id=project_id,
            mode=mode,
        )
        datasets.append({"id": dataset.id, "name": dataset.name, "rows": dataset.row_count})
        log.append(action)
        created += int(was_created)
        rows += dataset.row_count

    return {"datasets": datasets, "rows": rows, "created": created, "log": log}


def _finish_job(job_id: str, connection_id: str, summary: dict[str, Any]) -> None:
    with session_scope() as db:
        connection = db.get(Connection, connection_id)
        errors = list(summary.get("errors") or [])
        if connection:
            connection.last_sync_at = utcnow()
            connection.last_sync_status = SyncStatus.failed if errors else SyncStatus.success
            connection.last_sync_error = errors[0]["error"] if errors else ""
        job = db.get(Job, job_id)
        if job:
            job.status = (
                JobStatus.failed
                if errors and not summary.get("datasets")
                else JobStatus.success
            )
            job.finished_at = utcnow()
            job.progress = 100.0
            job.result = summary
            job.error = errors[0]["error"] if errors else ""


@celery_app.task(name="app.workers.source_sync.run_connection_sync", bind=True)
def run_connection_sync(self: Any, job_id: str) -> dict[str, Any]:
    """Import a connection regardless of which collection system it uses."""
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
            return {"error": job.error}
        provider = _provider(connection)

    # Keep the mature Survey Solutions path unchanged, including questionnaire
    # version merging, Stata labels and paradata semantics.
    if provider == "survey_solutions":
        from app.workers.tasks import run_connection_sync as survey_solutions_sync

        return survey_solutions_sync.run(job_id)

    with session_scope() as db:
        job = db.get(Job, job_id)
        connection = db.get(Connection, connection_id)
        if job is None or connection is None:
            return {"error": "job or connection not found"}
        job.status = JobStatus.running
        job.started_at = utcnow()
        job.celery_task_id = getattr(self.request, "id", "") or ""
        connection.last_sync_status = SyncStatus.running
        params = dict(job.params or {})
        selected = list(params.get("questionnaires") or [])
        project_id = params.get("project_id") or connection.project_id
        mode = str(params.get("mode") or "replace")
        connection_snapshot = {
            "provider": provider,
            "base_url": connection.base_url,
            "username": connection.username,
            "secret": decrypt(connection.password_encrypted) if connection.password_encrypted else "",
            "workspace": connection.workspace,
            "verify_ssl": connection.verify_ssl,
            "source_config": dict(connection.source_config or {}),
        }

    summary: dict[str, Any] = {"datasets": [], "errors": [], "rows": 0}
    workdir = Path(tempfile.mkdtemp(prefix="surveyhq-source-sync-"))
    try:
        with make_connector(**connection_snapshot) as source:
            catalogue = {row.identity: row for row in source.list_resources()}
            for identity in selected:
                resource = catalogue.get(identity)
                if resource is None:
                    summary["errors"].append(
                        {"resource": identity, "error": "The selected source resource no longer exists"}
                    )
                    continue

                with session_scope() as db:
                    run = SyncRun(
                        connection_id=connection_id,
                        questionnaire=resource.title,
                        status=SyncStatus.running,
                        started_at=utcnow(),
                    )
                    db.add(run)
                    db.flush()
                    run_id = run.id

                try:
                    raw = source_files_path() / f"{run_id}{source.export_suffix(identity)}"
                    source.export_to_file(identity, raw)
                    outcome = _import_external_file(
                        connection_id=connection_id,
                        provider=provider,
                        resource=resource,
                        source_file=raw,
                        project_id=project_id,
                        mode=mode,
                        workdir=workdir,
                    )
                    summary["datasets"].extend(outcome["datasets"])
                    summary["rows"] += outcome["rows"]
                    with session_scope() as db:
                        run = db.get(SyncRun, run_id)
                        if run:
                            run.status = SyncStatus.success
                            run.finished_at = utcnow()
                            run.rows_imported = outcome["rows"]
                            run.datasets_created = outcome["created"]
                            run.archive_path = str(raw)
                            run.message = (
                                f"Imported {outcome['rows']:,} records into "
                                f"{len(outcome['datasets'])} dataset(s)"
                            )
                            run.log = outcome["log"]
                except (SourceConnectorError, IngestError, OSError, ValueError) as exc:
                    logger.error("%s sync failed for %s: %s", provider, identity, exc)
                    summary["errors"].append({"resource": resource.title, "error": str(exc)})
                    with session_scope() as db:
                        run = db.get(SyncRun, run_id)
                        if run:
                            run.status = SyncStatus.failed
                            run.finished_at = utcnow()
                            run.message = str(exc)

        prune_source_files(connection_id)
        _finish_job(job_id, connection_id, summary)
        return summary
    except Exception as exc:  # noqa: BLE001 - a job must always record its failure
        logger.exception("External sync job %s failed", job_id)
        summary["errors"].append({"resource": "connection", "error": str(exc)})
        _finish_job(job_id, connection_id, summary)
        return {"error": str(exc), **summary}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@celery_app.task(name="app.workers.source_sync.schedule_due_syncs")
def schedule_due_syncs() -> dict[str, Any]:
    """Queue due automatic imports for every supported provider."""
    queued: list[str] = []
    now = utcnow()
    with session_scope() as db:
        connections = db.scalars(
            select(Connection).where(
                Connection.is_active.is_(True), Connection.sync_enabled.is_(True)
            )
        ).all()
        for connection in connections:
            if not connection.questionnaires:
                continue
            if connection.last_sync_status == SyncStatus.running:
                continue
            if not is_due(
                mode=connection.sync_mode or "interval",
                times=list(connection.sync_times or []),
                timezone=connection.sync_timezone or "UTC",
                interval_minutes=connection.sync_interval_minutes,
                last_sync_at=connection.last_sync_at,
                now=now,
            ):
                continue
            job = Job(
                job_type="sync",
                status=JobStatus.queued,
                title=f"Scheduled import from {connection.name}",
                params={
                    "connection_id": connection.id,
                    "questionnaires": list(connection.questionnaires),
                    "interview_status": connection.interview_status,
                    "project_id": connection.project_id,
                    "mode": "replace",
                },
            )
            db.add(job)
            db.flush()
            queued.append(job.id)

    for job_id in queued:
        run_connection_sync.delay(job_id)
    if queued:
        logger.info("Queued %s scheduled multi-source sync job(s)", len(queued))
    return {"queued": len(queued)}
