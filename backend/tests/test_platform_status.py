"""Liveness, readiness, and whether background work is running.

/health used to answer 200 with "degraded" in the body when the database was
down, so a monitor that reads only the status code saw a healthy API. And a
reachable database said nothing about whether imports and scheduled checks
were running. These pin the three answers that replaced it:

- /health/live: the process is up. Checks nothing else.
- /health/ready (and /health): 503 when the database is unreachable.
- /api/v1/system/status: workers, queue, scheduler, for administrators only.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
import redis

from app.services import platform_status
from tests.conftest import sign_in

NOW = dt.datetime(2026, 11, 7, 12, 0, tzinfo=dt.UTC)
REAL_JOBS = platform_status._jobs


# --- Liveness and readiness ----------------------------------------------------


def test_liveness_answers_without_checking_anything(client, monkeypatch):
    monkeypatch.setattr(platform_status, "database_ok", lambda: False)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_is_ok_when_the_database_answers(client, monkeypatch):
    monkeypatch.setattr(platform_status, "queue_ok", lambda: True)
    for path in ("/health/ready", "/health"):
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        assert body["queue"] == "ok"


def test_readiness_fails_with_503_when_the_database_is_down(client, monkeypatch):
    monkeypatch.setattr(platform_status, "database_ok", lambda: False)
    monkeypatch.setattr(platform_status, "queue_ok", lambda: True)
    for path in ("/health/ready", "/health"):
        response = client.get(path)
        assert response.status_code == 503, path
        assert response.json() == {
            "status": "unavailable",
            "version": response.json()["version"],
            "database": "unreachable",
            "queue": "ok",
        }
    # The process is still alive: restarting it would not bring the database back.
    assert client.get("/health/live").status_code == 200


def test_a_queue_outage_is_reported_but_does_not_fail_readiness(client, monkeypatch):
    monkeypatch.setattr(platform_status, "queue_ok", lambda: False)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["queue"] == "unreachable"


# --- Operational status --------------------------------------------------------


class FakeRedis:
    """Just what operational_status asks of Redis."""

    def __init__(self, *, up=True, heartbeat=None, backlog=None):
        self.up = up
        self.heartbeat = heartbeat
        self.backlog = backlog or {}

    def ping(self):
        if not self.up:
            raise redis.ConnectionError("down")
        return True

    def llen(self, name):
        return self.backlog.get(name, 0)

    def get(self, key):
        assert key == platform_status.SCHEDULER_KEY
        if self.heartbeat is None:
            return None
        return json.dumps({"at": self.heartbeat.isoformat(), "task": "reap_stale_jobs"})


ALL_QUEUES = {
    "celery@worker": ["default", "imports"],
    "celery@worker-monitoring": ["maintenance", "monitoring", "quality"],
}


@pytest.fixture
def healthy(monkeypatch):
    """A platform where everything is running; each test breaks one thing."""
    state = {"redis": FakeRedis(heartbeat=NOW - dt.timedelta(minutes=3)), "workers": ALL_QUEUES}
    monkeypatch.setattr(platform_status, "_redis", lambda: state["redis"])
    monkeypatch.setattr(platform_status, "_inspect_workers", lambda: state["workers"])
    monkeypatch.setattr(platform_status, "database_ok", lambda: True)
    monkeypatch.setattr(platform_status, "STARTED_AT", NOW - dt.timedelta(hours=2))
    # Other tests leave queued jobs in the shared database, which would look
    # hours old against this fixed clock. The job count has its own test.
    monkeypatch.setattr(
        platform_status,
        "_jobs",
        lambda _db: {"queued": 0, "running": 0, "oldest_queued_at": None},
    )
    # The real disk is whatever this machine has; the low-disk test sets its own.
    from app.services import storage_retention

    state["disk"] = {"free_percent": 55.0, "free_bytes": 200 * 1024**3, "low": False}
    monkeypatch.setattr(storage_retention, "disk", lambda: state["disk"])
    return state


def test_all_running_reports_no_problems(healthy, db_session):
    status = platform_status.operational_status(db_session, now=NOW)
    assert status["problems"] == []
    assert status["ok"] is True
    assert status["workers"]["ok"] is True
    assert status["scheduler"]["ok"] is True
    assert status["scheduler"]["age_seconds"] == 180
    assert status["queue"]["backlog"] == dict.fromkeys(platform_status.QUEUES, 0)


def test_a_queue_with_no_worker_is_named(healthy, db_session):
    healthy["workers"] = {"celery@worker": ["default", "imports"]}
    status = platform_status.operational_status(db_session, now=NOW)
    assert status["ok"] is False
    assert status["workers"]["queues_without_worker"] == ["monitoring", "quality", "maintenance"]
    assert status["problems"] == [
        "No worker is taking jobs from the monitoring, quality, maintenance queues."
    ]


def test_no_workers_answering(healthy, db_session):
    healthy["workers"] = {}
    status = platform_status.operational_status(db_session, now=NOW)
    assert "No background worker is answering. Imports and checks will not run." in status["problems"]


def test_a_stopped_scheduler(healthy, db_session):
    healthy["redis"] = FakeRedis(heartbeat=NOW - dt.timedelta(minutes=45))
    status = platform_status.operational_status(db_session, now=NOW)
    assert status["scheduler"]["ok"] is False
    assert status["problems"] == [
        "The scheduler last sent work 45 minutes ago. "
        "Scheduled imports, indicators and checks have stopped."
    ]


def test_a_scheduler_that_never_reported(healthy, db_session, monkeypatch):
    healthy["redis"] = FakeRedis(heartbeat=None)
    status = platform_status.operational_status(db_session, now=NOW)
    assert "The scheduler has not sent any work since the platform started." in status["problems"]

    # Just after start-up it has not had the chance yet, which is not a problem.
    monkeypatch.setattr(platform_status, "STARTED_AT", NOW - dt.timedelta(minutes=2))
    status = platform_status.operational_status(db_session, now=NOW)
    assert status["scheduler"]["ok"] is None
    assert status["problems"] == []


def test_the_queue_unreachable(healthy, db_session):
    healthy["redis"] = FakeRedis(up=False)
    status = platform_status.operational_status(db_session, now=NOW)
    assert status["queue"]["ok"] is False
    assert status["workers"]["ok"] is None
    # The scheduler's heartbeat is in Redis too, so it is unknown, not "stopped".
    assert status["scheduler"]["ok"] is None
    assert len(status["problems"]) == 1
    assert status["problems"][0].startswith("The job queue (Redis) is unreachable")


def test_a_backlog_is_reported(healthy, db_session):
    healthy["redis"].backlog = {"imports": 120}
    status = platform_status.operational_status(db_session, now=NOW)
    assert status["queue"]["backlog"]["imports"] == 120
    assert status["problems"] == ["120 jobs are waiting in the imports queue."]


def test_a_job_waiting_too_long_is_reported(healthy, db_session, monkeypatch):
    from app.models import Job, JobStatus, JobType

    monkeypatch.setattr(platform_status, "_jobs", REAL_JOBS)

    job = Job(
        id=str(uuid.uuid4()),
        title="Import waiting",
        job_type=JobType.ingest,
        status=JobStatus.queued,
        created_at=NOW - dt.timedelta(minutes=40),
    )
    db_session.add(job)
    db_session.flush()
    try:
        status = platform_status.operational_status(db_session, now=NOW)
        assert status["jobs"]["queued"] >= 1
        assert any(problem.startswith("A job has been waiting to start for") for problem in status["problems"])
    finally:
        db_session.rollback()


def test_a_nearly_full_disk_is_reported(healthy, db_session):
    healthy["disk"] = {"free_percent": 4.2, "free_bytes": 8 * 1024**3, "low": True}
    status = platform_status.operational_status(db_session, now=NOW)
    assert status["problems"] == [
        "The disk holding the data is nearly full: 4.2% (8 GB) free."
    ]


def test_the_database_down(healthy, db_session, monkeypatch):
    monkeypatch.setattr(platform_status, "database_ok", lambda: False)
    status = platform_status.operational_status(db_session, now=NOW)
    assert status["database"]["ok"] is False
    assert status["jobs"] is None
    assert status["problems"][0] == "The database is unreachable."


# --- Who may see it ------------------------------------------------------------


def test_only_administrators_see_the_operational_status(client, auth_headers, healthy, db_session):
    response = client.get("/api/v1/system/status", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert set(response.json()) >= {"ok", "problems", "database", "queue", "workers", "scheduler"}

    from app.core.security import hash_password
    from app.models import Role, User

    db_session.add(
        User(
            email="status-manager@example.org",
            username="status-manager",
            full_name="Not An Admin",
            hashed_password=hash_password("Fieldwork-2026-manager"),
            role=Role.manager,
        )
    )
    db_session.commit()
    manager = sign_in(client, "status-manager@example.org", "Fieldwork-2026-manager")
    assert client.get("/api/v1/system/status", headers=manager).status_code == 403
    assert client.get("/api/v1/system/status").status_code == 401


def test_the_heartbeat_never_raises(monkeypatch):
    class Broken:
        def set(self, *args, **kwargs):
            raise redis.ConnectionError("down")

    monkeypatch.setattr(platform_status, "_redis", lambda: Broken())
    platform_status.record_scheduler_heartbeat("app.workers.tasks.reap_stale_jobs")
