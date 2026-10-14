"""Celery application and the periodic schedule."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.logging import configure_logging
from app.services.query_runtime import install_query_runtime
from app.workers.schedules import Tunable

configure_logging()
install_query_runtime()

celery_app = Celery(
    "surveyhq",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600 * 4,
    task_soft_time_limit=3600 * 3,
    worker_max_tasks_per_child=50,
    result_expires=60 * 60 * 24 * 3,
    broker_connection_retry_on_startup=True,
    # How long beat may sleep between looking at its schedule. It decides how
    # soon a changed interval takes hold, because beat otherwise sleeps until
    # the next run is due - an hourly task shortened to five minutes would not
    # be noticed for an hour. A minute of sleep costs nothing and is the whole
    # price of settings that need no restart.
    beat_max_loop_interval=60,
    task_default_queue="default",
    task_routes={
        # File parsing and Survey Solutions downloads can saturate CPU / disk for
        # minutes. They must not make alerts and monitoring wait in the same queue.
        "app.workers.tasks.run_upload_import": {"queue": "imports"},
        "app.workers.tasks.run_connection_sync": {"queue": "imports"},
        "app.workers.tasks.run_folder_import": {"queue": "imports"},
        # With the imports, because it is the same kind of work: a full pass
        # over a dataset per value, on the worker whose concurrency is the one
        # tuned for how much memory that takes.
        "app.workers.tasks.run_report_burst": {"queue": "imports"},
        "app.workers.tasks.schedule_due_syncs": {"queue": "monitoring"},
        "app.workers.tasks.refresh_all_indicators": {"queue": "monitoring"},
        "app.workers.tasks.run_all_quality_checks": {"queue": "quality"},
        "app.workers.tasks.prune_history": {"queue": "maintenance"},
        "app.workers.tasks.reap_stale_jobs": {"queue": "maintenance"},
    },
)

celery_app.conf.beat_schedule = {
    # Both intervals are settings an administrator can change from the
    # platform itself, so they are read when beat asks rather than captured
    # here at import.
    "check-due-connection-syncs": {
        "task": "app.workers.tasks.schedule_due_syncs",
        "schedule": Tunable("sync_tick_minutes"),
    },
    "refresh-indicators-and-alerts": {
        "task": "app.workers.tasks.refresh_all_indicators",
        "schedule": Tunable("monitor_tick_minutes"),
    },
    "run-quality-checks": {
        "task": "app.workers.tasks.run_all_quality_checks",
        "schedule": crontab(minute=15, hour="*/6"),
    },
    # Every ten minutes, so a slot set to 08:00 is caught shortly after it
    # opens. Each board checks its own schedule; this only asks.
    "take-due-dashboard-snapshots": {
        "task": "app.workers.tasks.take_due_snapshots",
        "schedule": 600.0,
    },
    # Often enough that a job left behind by a worker that went away is not
    # still claiming to be running an hour later, cheap enough to be free: it
    # is one indexed query that normally matches nothing.
    "reap-stale-jobs": {
        "task": "app.workers.tasks.reap_stale_jobs",
        "schedule": 600.0,
    },
    "prune-old-records": {
        "task": "app.workers.tasks.prune_history",
        "schedule": crontab(minute=30, hour=3),
    },
}
