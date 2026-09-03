"""Background tasks: server sync, indicator refresh, quality checks, housekeeping."""

from __future__ import annotations

import datetime as dt
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
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
from app.services.datasets import load_archive_as_datasets, load_file_into_dataset
from app.services.derived import rebuild_dependents
from app.services.ingest import IngestError
from app.services.monitoring import evaluate_alert_rule, refresh_indicator
from app.services.quality import execute_rule
from app.services.scheduling import is_due
from app.services.survey_solutions import (
    SurveySolutionsClient,
    SurveySolutionsError,
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
    mode = params.get("mode") or "replace"

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
            project_id = params.get("project_id") or connection.project_id

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
                    # Kept where it can be downloaded again, and named after the
                    # run so a connection's history is a list of real archives.
                    archive = archives_path() / f"{run_id}.zip"
                    client.export_to_file(
                        identity,
                        archive,
                        export_type=export_format,  # type: ignore[arg-type]
                        interview_status=interview_status,  # type: ignore[arg-type]
                    )
                    outcome = _import_export_archive(
                        connection_id=str(connection_id),
                        connection_name=connection_name,
                        title=title,
                        archive=archive,
                        project_id=project_id,
                        mode=mode,
                        summary=summary,
                    )
                    with session_scope() as db:
                        run = db.get(SyncRun, run_id)
                        if run:
                            run.status = SyncStatus.success
                            run.finished_at = utcnow()
                            run.rows_imported = outcome["rows"]
                            run.datasets_created = outcome["datasets"]
                            run.archive_path = str(archive)
                            run.message = (
                                f"Imported {outcome['rows']:,} records into "
                                f"{outcome['datasets']} dataset(s)"
                            )
                            run.log = outcome["log"]
                except (SurveySolutionsError, IngestError) as exc:
                    logger.error("Sync failed for %s: %s", identity, exc)
                    summary["errors"].append({"questionnaire": title, "error": str(exc)})
                    with session_scope() as db:
                        run = db.get(SyncRun, run_id)
                        if run:
                            run.status = SyncStatus.failed
                            run.finished_at = utcnow()
                            run.message = str(exc)

        prune_archives(str(connection_id))

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


ARCHIVES_KEPT = 5


def archives_path() -> Path:
    return settings.storage_path / "sync-archives"


def prune_archives(connection_id: str, keep: int = ARCHIVES_KEPT) -> None:
    """Keep the last few export zips per connection and delete the rest.

    An export is tens of megabytes and a connection syncing every six hours
    produces four a day, so keeping all of them fills the disk of the machine
    the platform runs on. The recent ones are the ones anybody downloads.
    """
    with session_scope() as db:
        runs = db.scalars(
            select(SyncRun)
            .where(SyncRun.connection_id == connection_id, SyncRun.archive_path != "")
            .order_by(SyncRun.started_at.desc())
        ).all()
        for run in runs[keep:]:
            Path(run.archive_path).unlink(missing_ok=True)
            run.archive_path = ""


def _import_export_archive(
    *,
    connection_id: str,
    connection_name: str,
    title: str,
    archive: Path,
    project_id: str | None,
    mode: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Import a whole export, the same way an uploaded archive is imported.

    A Survey Solutions export is one file per roster level plus the paradata,
    and this used to keep only the first of them - so everything below the
    interview level, and every record of how the fieldwork went, was downloaded
    and thrown away. Sending the archive through the same path an upload takes
    also means a re-import replaces each dataset in place, keeping the ids that
    charts, indicators and merges are built on.
    """
    with session_scope() as db:
        result = load_archive_as_datasets(
            db,
            archive_path=archive,
            archive_name=f"{title}.zip",
            project_id=project_id,
            created_by=None,
            name_prefix="",
            mode=mode,
        )
        rebuilt = rebuild_dependents(db, result.replaced_ids)
        db.flush()
        for dataset in result.datasets:
            summary["datasets"].append(
                {"id": dataset.id, "name": dataset.name, "rows": dataset.row_count}
            )
        summary["rows"] += result.rows
        log = result.created + result.replaced + result.appended
        if rebuilt:
            log.append(f"{len(rebuilt)} merged dataset(s) rebuilt")
        # The connection is recorded on each dataset so a later sync of the same
        # questionnaire finds them, and so the UI can say where they came from.
        for dataset in result.datasets:
            dataset.connection_id = connection_id
            if dataset.source == DatasetSource.upload:
                dataset.source = DatasetSource.survey_solutions
            tags = list(dataset.tags or [])
            if connection_name and "survey-solutions" not in tags:
                tags.append("survey-solutions")
                dataset.tags = tags
        return {
            "rows": result.rows,
            "datasets": len(result.datasets),
            "log": log + result.warnings,
        }


@celery_app.task(name="app.workers.tasks.schedule_due_syncs")
def schedule_due_syncs() -> dict[str, Any]:
    """Queue the automatic imports that are due.

    Runs every few minutes, and each connection decides for itself whether its
    moment has arrived - an elapsed interval, or a clock time in its own zone
    that has passed with nothing having run since.
    """
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
