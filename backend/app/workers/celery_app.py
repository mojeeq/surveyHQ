"""Celery application and the periodic schedule."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.logging import configure_logging
from app.services.query_runtime import install_query_runtime

configure_logging()
install_query_runtime()

celery_app = Celery(
    "surveyhq",
    broker=settings.redis_url,
    backend=settings.redis_url,
    # source_sync deliberately loads after tasks and registers the same two
    # connection-sync task names as provider-aware dispatchers. Old queued task
    # names remain valid while Survey Solutions still delegates to its mature
    # implementation in tasks.py.
    include=["app.workers.tasks", "app.workers.source_sync"],
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
    task_default_queue="default",
    task_routes={
        # File parsing and external-source downloads can saturate CPU / disk for
        # minutes. They must not make alerts and monitoring wait in the same queue.
        "app.workers.tasks.run_upload_import": {"queue": "imports"},
        "app.workers.tasks.run_connection_sync": {"queue": "imports"},
        "app.workers.tasks.schedule_due_syncs": {"queue": "monitoring"},
        "app.workers.tasks.refresh_all_indicators": {"queue": "monitoring"},
        "app.workers.tasks.run_all_quality_checks": {"queue": "quality"},
        "app.workers.tasks.prune_history": {"queue": "maintenance"},
    },
)

celery_app.conf.beat_schedule = {
    "check-due-connection-syncs": {
        "task": "app.workers.tasks.schedule_due_syncs",
        "schedule": settings.sync_tick_minutes * 60.0,
    },
    "refresh-indicators-and-alerts": {
        "task": "app.workers.tasks.refresh_all_indicators",
        "schedule": settings.monitor_tick_minutes * 60.0,
    },
    "run-quality-checks": {
        "task": "app.workers.tasks.run_all_quality_checks",
        "schedule": crontab(minute=15, hour="*/6"),
    },
    "prune-old-records": {
        "task": "app.workers.tasks.prune_history",
        "schedule": crontab(minute=30, hour=3),
    },
}
