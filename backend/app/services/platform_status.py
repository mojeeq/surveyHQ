"""Whether the platform is up, and whether its background work is running.

Two different questions with different callers:

- **Readiness** (``/health/ready``): can this API serve requests? Only the
  database is required for that. It is cheap, needs no sign-in, and is what
  Docker, load balancers and uptime monitors ask. It answers 503 when the
  database is unreachable, so a monitor that only reads the HTTP status sees it.
- **Operational status** (``/api/v1/system/status``, administrators only): is
  the background work happening? Queue backlog, which workers answer and which
  queues have nobody taking from them, and when the scheduler last sent work.
  A page can be served while imports quietly stop, which readiness cannot show.

Liveness (``/health/live``) checks nothing but the process itself, so a
database outage never makes an orchestrator restart a healthy API.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any

import redis
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import engine

logger = get_logger(__name__)

# Every queue a worker should be taking from. docker-compose.yml runs one worker
# for the first two and one for the last three.
QUEUES = ("imports", "default", "monitoring", "quality", "maintenance")

# Written by the scheduler (celery beat) each time it sends a periodic task.
SCHEDULER_KEY = "surveyhq:scheduler:last_sent"
# Beat sends something at least every ten minutes (stale-job reaping and
# dashboard snapshots), so twice that without a word means it has stopped.
SCHEDULER_STALE_AFTER = dt.timedelta(minutes=20)
# A queue with more than this many jobs waiting is worth an administrator's look.
BACKLOG_WARNING = 50
# How long a job may sit queued before that is reported.
QUEUED_TOO_LONG = dt.timedelta(minutes=15)

# When this API process started, so "the scheduler has never reported" can be
# told apart from "the platform was started a minute ago".
STARTED_AT = dt.datetime.now(dt.UTC)


def _redis() -> redis.Redis:
    return redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        decode_responses=True,
    )


def database_ok() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        logger.warning("readiness: database unreachable", exc_info=True)
        return False


def queue_ok() -> bool:
    try:
        return bool(_redis().ping())
    except redis.RedisError:
        return False


def readiness() -> tuple[bool, dict[str, Any]]:
    """Whether the API can serve requests, and what was checked.

    The database is required; the job queue is reported but does not fail
    readiness, because pages are still served while it is down and restarting
    the API would not bring it back.
    """
    database = database_ok()
    queue = queue_ok()
    from app import __version__

    body = {
        "status": "ok" if database else "unavailable",
        "version": __version__,
        "database": "ok" if database else "unreachable",
        "queue": "ok" if queue else "unreachable",
    }
    return database, body


# --- The scheduler's heartbeat -------------------------------------------------


def record_scheduler_heartbeat(task_name: str) -> None:
    """Note that the scheduler just sent a task. Never raises: beat must not stop over this."""
    try:
        _redis().set(
            SCHEDULER_KEY,
            json.dumps({"at": dt.datetime.now(dt.UTC).isoformat(), "task": task_name}),
            ex=int(dt.timedelta(days=7).total_seconds()),
        )
    except Exception:  # noqa: BLE001 - a heartbeat is best effort by design
        logger.debug("scheduler heartbeat not recorded", exc_info=True)


def scheduler_status(client: redis.Redis | None, now: dt.datetime) -> dict[str, Any]:
    last_at: dt.datetime | None = None
    last_task: str | None = None
    if client is not None:
        try:
            raw = client.get(SCHEDULER_KEY)
            if raw:
                record = json.loads(raw)
                last_at = dt.datetime.fromisoformat(record["at"])
                last_task = record.get("task")
        except (redis.RedisError, ValueError, KeyError, TypeError):
            pass
    if last_at is None:
        # Only a problem once the scheduler has had time to send something.
        ok = None if now - STARTED_AT < SCHEDULER_STALE_AFTER else False
        return {"ok": ok, "last_sent_at": None, "last_task": None, "age_seconds": None}
    age = now - last_at
    return {
        "ok": age <= SCHEDULER_STALE_AFTER,
        "last_sent_at": last_at.isoformat(),
        "last_task": last_task,
        "age_seconds": int(age.total_seconds()),
    }


# --- Workers and the queue -----------------------------------------------------


def _inspect_workers() -> dict[str, list[str]] | None:
    """Each worker that answered within a second, and the queues it takes from.

    None when the broker could not be asked at all.
    """
    from app.workers.celery_app import celery_app

    try:
        answer = celery_app.control.inspect(timeout=1.0).active_queues()
    except Exception:  # noqa: BLE001 - any broker failure means "could not ask"
        logger.warning("could not ask the workers which queues they take", exc_info=True)
        return None
    return {
        worker: sorted(queue.get("name", "") for queue in (queues or []))
        for worker, queues in (answer or {}).items()
    }


def _backlog(client: redis.Redis) -> dict[str, int]:
    # Celery's Redis transport keeps each queue as a list of that name.
    return {queue: int(client.llen(queue)) for queue in QUEUES}


def _jobs(db) -> dict[str, Any]:
    from app.models import Job, JobStatus

    queued = db.scalar(select(func.count()).select_from(Job).where(Job.status == JobStatus.queued))
    running = db.scalar(
        select(func.count()).select_from(Job).where(Job.status == JobStatus.running)
    )
    oldest = db.scalar(select(func.min(Job.created_at)).where(Job.status == JobStatus.queued))
    if oldest is not None and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=dt.UTC)
    return {
        "queued": int(queued or 0),
        "running": int(running or 0),
        "oldest_queued_at": oldest.isoformat() if oldest else None,
    }


def operational_status(db, now: dt.datetime | None = None) -> dict[str, Any]:
    """Everything an administrator needs to see whether background work is running."""
    now = now or dt.datetime.now(dt.UTC)
    started = time.monotonic()
    problems: list[str] = []

    database = database_ok()
    if not database:
        problems.append("The database is unreachable.")

    client: redis.Redis | None = _redis()
    backlog: dict[str, int] | None = None
    try:
        client.ping()
        backlog = _backlog(client)
    except redis.RedisError:
        client = None
        problems.append(
            "The job queue (Redis) is unreachable, so imports and scheduled work cannot run."
        )

    workers = _inspect_workers() if client is not None else None
    missing: list[str] = []
    if client is not None:
        if workers is None:
            problems.append("The workers could not be asked whether they are running.")
        else:
            served = {queue for queues in workers.values() for queue in queues}
            missing = [queue for queue in QUEUES if queue not in served]
            if not workers:
                problems.append(
                    "No background worker is answering. Imports and checks will not run."
                )
            elif missing:
                problems.append(
                    "No worker is taking jobs from the "
                    + ", ".join(missing)
                    + (" queue." if len(missing) == 1 else " queues.")
                )

    if backlog:
        for queue, waiting in backlog.items():
            if waiting > BACKLOG_WARNING:
                problems.append(f"{waiting} jobs are waiting in the {queue} queue.")

    if client is None:
        # Its heartbeat lives in Redis, so with Redis down there is nothing to
        # read; the queue problem above already says what is wrong.
        scheduler = {"ok": None, "last_sent_at": None, "last_task": None, "age_seconds": None}
    else:
        scheduler = scheduler_status(client, now)
    if scheduler["ok"] is False:
        if scheduler["last_sent_at"] is None:
            problems.append("The scheduler has not sent any work since the platform started.")
        else:
            minutes = scheduler["age_seconds"] // 60
            problems.append(
                f"The scheduler last sent work {minutes} minutes ago. "
                "Scheduled imports, indicators and checks have stopped."
            )

    from app.services.storage_retention import disk

    space = disk()
    if space.get("low"):
        problems.append(
            f"The disk holding the data is nearly full: {space['free_percent']}% "
            f"({space['free_bytes'] // (1024 ** 3)} GB) free."
        )

    jobs = _jobs(db) if database else None
    if jobs and jobs["oldest_queued_at"]:
        waited = now - dt.datetime.fromisoformat(jobs["oldest_queued_at"])
        if waited > QUEUED_TOO_LONG:
            problems.append(
                f"A job has been waiting to start for {int(waited.total_seconds() // 60)} minutes."
            )

    return {
        "checked_at": now.isoformat(),
        "ok": not problems,
        "problems": problems,
        "database": {"ok": database},
        "queue": {"ok": client is not None, "backlog": backlog},
        "workers": {
            "ok": bool(workers) and not missing if workers is not None else None,
            "responding": [
                {"name": name, "queues": queues} for name, queues in sorted((workers or {}).items())
            ],
            "queues_without_worker": missing,
        },
        "scheduler": scheduler,
        "jobs": jobs,
        "disk": space,
        "took_ms": int((time.monotonic() - started) * 1000),
    }
