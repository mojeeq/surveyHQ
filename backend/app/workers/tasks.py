"""Background tasks: server sync, indicator refresh, quality checks, housekeeping."""

from __future__ import annotations

import datetime as dt
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
    Alert,
    AlertRule,
    AlertStatus,
    Connection,
    Dataset,
    DatasetSource,
    Indicator,
    IndicatorSnapshot,
    Job,
    JobStatus,
    QualityResult,
    QualityRule,
    SyncRun,
    SyncStatus,
)
from app.services.datasets import create_dataset_record, load_file_into_dataset
from app.services.ingest import IngestError
from app.services.monitoring import evaluate_alert_rule, refresh_indicator
from app.services.quality import execute_rule
from app.services.survey_solutions import (
    SurveySolutionsClient,
    SurveySolutionsError,
    pick_main_file,
)
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

SNAPSHOT_RETENTION_DAYS = 180
ALERT_RETENTION_DAYS = 90
QUALITY_RESULT_RETENTION_DAYS = 90
JOB_RETENTION_DAYS = 30


@celery_app.task(name="app.workers.tasks.run_connection_sync", bind=True)
def run_connection_sync(self: Any, job_id: str) -> dict[str, Any]:
    """Export the configured questionnaires from a server and import them."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return {"error": "job not found"}
        job.status = JobStatus.running
        job.started_at = utcnow()
        job.celery_task_id = getattr(self.request, "id", "") or ""
        params = dict(job.params or {})
        db.flush()

    connection_id = params.get("connection_id")
    questionnaires: list[str] = list(params.get("questionnaires") or [])
    interview_status = params.get("interview_status") or "All"

    summary: dict[str, Any] = {"datasets": [], "errors": [], "rows": 0}
    workdir = Path(tempfile.mkdtemp(prefix="surveyhq-sync-"))

    try:
        with session_scope() as db:
            connection = db.get(Connection, connection_id)
            if connection is None:
                raise SurveySolutionsError("The connection no longer exists")
            credentials = {
                "base_url": connection.base_url,
                "username": connection.username,
                "password": decrypt(connection.password_encrypted),
                "workspace": connection.workspace,
                "verify_ssl": connection.verify_ssl,
            }
            export_format = connection.export_format.value
            connection.last_sync_status = SyncStatus.running
            connection_name = connection.name

        with SurveySolutionsClient(**credentials) as client:
            catalogue = {q.identity: q for q in client.list_questionnaires()}

            for identity in questionnaires:
                questionnaire = catalogue.get(identity)
                title = questionnaire.title if questionnaire else identity
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
                    target = workdir / identity.replace("$", "_")
                    files = client.export_to_directory(
                        identity,
                        target,
                        export_type=export_format,  # type: ignore[arg-type]
                        interview_status=interview_status,  # type: ignore[arg-type]
                    )
                    main_file = pick_main_file(
                        files, questionnaire.variable if questionnaire else ""
                    )
                    rows = _import_export_file(
                        connection_id=str(connection_id),
                        connection_name=connection_name,
                        identity=identity,
                        title=title,
                        file_path=main_file,
                        summary=summary,
                    )
                    with session_scope() as db:
                        run = db.get(SyncRun, run_id)
                        if run:
                            run.status = SyncStatus.success
                            run.finished_at = utcnow()
                            run.rows_imported = rows
                            run.datasets_created = 1
                            run.message = f"Imported {rows:,} records from {main_file.name}"
                            run.log = [f.name for f in files]
                except (SurveySolutionsError, IngestError) as exc:
                    logger.error("Sync failed for %s: %s", identity, exc)
                    summary["errors"].append({"questionnaire": title, "error": str(exc)})
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

    except Exception as exc:  # noqa: BLE001 - always record why a job died
        logger.exception("Sync job %s failed", job_id)
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


def _import_export_file(
    *,
    connection_id: str,
    connection_name: str,
    identity: str,
    title: str,
    file_path: Path,
    summary: dict[str, Any],
) -> int:
    """Create or refresh the dataset backing one questionnaire."""
    with session_scope() as db:
        dataset = db.scalar(
            select(Dataset).where(
                Dataset.connection_id == connection_id, Dataset.source_ref == identity
            )
        )
        if dataset is None:
            dataset = create_dataset_record(
                db,
                name=f"{title} ({connection_name})",
                description=f"Imported from Survey Solutions questionnaire {identity}",
                source=DatasetSource.survey_solutions,
                source_ref=identity,
                connection_id=connection_id,
                tags=["survey-solutions"],
            )
        load_file_into_dataset(db, dataset, file_path)
        summary["datasets"].append(
            {"id": dataset.id, "name": dataset.name, "rows": dataset.row_count}
        )
        summary["rows"] += dataset.row_count
        return dataset.row_count


@celery_app.task(name="app.workers.tasks.schedule_due_syncs")
def schedule_due_syncs() -> dict[str, Any]:
    """Queue syncs for connections whose interval has elapsed."""
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
            last = connection.last_sync_at
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=dt.UTC)
                if (now - last).total_seconds() < connection.sync_interval_minutes * 60:
                    continue
            if connection.last_sync_status == SyncStatus.running:
                continue

            job = Job(
                job_type="sync",
                status=JobStatus.queued,
                title=f"Scheduled import from {connection.name}",
                params={
                    "connection_id": connection.id,
                    "questionnaires": list(connection.questionnaires),
                    "interview_status": connection.interview_status,
                },
            )
            db.add(job)
            db.flush()
            queued.append(job.id)

    for job_id in queued:
        run_connection_sync.delay(job_id)
    if queued:
        logger.info("Queued %s scheduled sync job(s)", len(queued))
    return {"queued": len(queued)}


@celery_app.task(name="app.workers.tasks.refresh_all_indicators")
def refresh_all_indicators() -> dict[str, Any]:
    """Recompute indicators, store a snapshot, then evaluate alert rules."""
    refreshed = 0
    triggered = 0
    with session_scope() as db:
        indicators = db.scalars(
            select(Indicator).where(Indicator.is_active.is_(True))
        ).all()
        for indicator in indicators:
            try:
                refresh_indicator(db, indicator)
                refreshed += 1
            except Exception as exc:  # noqa: BLE001 - one bad spec must not stop the rest
                logger.warning("Indicator '%s' failed to refresh: %s", indicator.name, exc)

        rules = db.scalars(select(AlertRule).where(AlertRule.is_active.is_(True))).all()
        for rule in rules:
            try:
                if evaluate_alert_rule(db, rule) is not None:
                    triggered += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Alert rule '%s' failed: %s", rule.name, exc)

    logger.info("Refreshed %s indicator(s); %s alert(s) fired", refreshed, triggered)
    return {"refreshed": refreshed, "alerts_triggered": triggered}


@celery_app.task(name="app.workers.tasks.run_all_quality_checks")
def run_all_quality_checks() -> dict[str, Any]:
    passed = failed = 0
    with session_scope() as db:
        rules = db.scalars(select(QualityRule).where(QualityRule.is_active.is_(True))).all()
        for rule in rules:
            try:
                result = execute_rule(db, rule)
                if result.passed:
                    passed += 1
                else:
                    failed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Quality rule '%s' failed to run: %s", rule.name, exc)
                failed += 1
    logger.info("Quality checks complete: %s passed, %s failed", passed, failed)
    return {"passed": passed, "failed": failed}


@celery_app.task(name="app.workers.tasks.ingest_dataset_file")
def ingest_dataset_file(dataset_id: str, file_path: str) -> dict[str, Any]:
    """Used for large uploads that are handed off to the worker."""
    with session_scope() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            return {"error": "dataset not found"}
        try:
            load_file_into_dataset(db, dataset, Path(file_path))
            return {"rows": dataset.row_count, "columns": dataset.column_count}
        except IngestError as exc:
            return {"error": str(exc)}
        finally:
            Path(file_path).unlink(missing_ok=True)


@celery_app.task(name="app.workers.tasks.prune_history")
def prune_history() -> dict[str, int]:
    """Keep the operational tables from growing without bound."""
    now = utcnow()
    removed = {"snapshots": 0, "alerts": 0, "quality_results": 0, "jobs": 0}
    with session_scope() as db:
        snapshot_cutoff = now - dt.timedelta(days=SNAPSHOT_RETENTION_DAYS)
        for snapshot in db.scalars(
            select(IndicatorSnapshot).where(IndicatorSnapshot.computed_at < snapshot_cutoff)
        ).all():
            db.delete(snapshot)
            removed["snapshots"] += 1

        alert_cutoff = now - dt.timedelta(days=ALERT_RETENTION_DAYS)
        for alert in db.scalars(
            select(Alert).where(
                Alert.created_at < alert_cutoff, Alert.status == AlertStatus.resolved
            )
        ).all():
            db.delete(alert)
            removed["alerts"] += 1

        quality_cutoff = now - dt.timedelta(days=QUALITY_RESULT_RETENTION_DAYS)
        for result in db.scalars(
            select(QualityResult).where(QualityResult.run_at < quality_cutoff)
        ).all():
            db.delete(result)
            removed["quality_results"] += 1

        job_cutoff = now - dt.timedelta(days=JOB_RETENTION_DAYS)
        for job in db.scalars(select(Job).where(Job.created_at < job_cutoff)).all():
            db.delete(job)
            removed["jobs"] += 1

    logger.info("Pruned old records: %s", removed)
    return removed
