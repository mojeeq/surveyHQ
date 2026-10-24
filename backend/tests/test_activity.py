"""The activity panel: what is running, what each step did, and what is next.

Asked for in so many words - "I don't have a clue what's happening". An
import used to show nothing but its own completion, and a scheduled one, being
started by nobody, was on no list but an administrator's.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.models import Connection, Job, JobStatus, JobType
from app.services.scheduling import next_due
from tests.conftest import sign_in

NOW = dt.datetime(2026, 10, 23, 9, 30, tzinfo=dt.UTC)


def test_an_interval_import_is_next_due_an_interval_after_the_last():
    due = next_due(
        mode="interval",
        times=[],
        timezone="UTC",
        interval_minutes=60,
        last_sync_at=NOW - dt.timedelta(minutes=20),
        now=NOW,
    )
    assert due == NOW + dt.timedelta(minutes=40)


def test_one_that_is_due_already_is_due_now():
    assert (
        next_due(
            mode="interval",
            times=[],
            timezone="UTC",
            interval_minutes=60,
            last_sync_at=None,
            now=NOW,
        )
        == NOW
    )


def test_a_daily_import_is_next_due_at_its_next_time_in_its_own_zone():
    """09:30 UTC is 21:30 in Fiji (UTC+12): the 08:00 slot there has gone and
    the 22:00 one, 10:00 UTC, has not."""
    due = next_due(
        mode="daily",
        times=["08:00", "22:00"],
        timezone="Pacific/Fiji",
        interval_minutes=0,
        last_sync_at=NOW - dt.timedelta(hours=1),
        now=NOW,
    )
    assert due is not None
    assert due.astimezone(dt.UTC) == dt.datetime(2026, 10, 23, 10, 0, tzinfo=dt.UTC)


def test_a_daily_import_with_no_times_is_never_due():
    assert (
        next_due(
            mode="daily",
            times=[],
            timezone="UTC",
            interval_minutes=0,
            last_sync_at=NOW,
            now=NOW,
        )
        is None
    )


@pytest.fixture
def scheduled(client, auth_headers, db_session, request):
    """A project, a scheduled connection into it, and an import running for it."""
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": f"Act {request.node.name[:40]}"}
    ).json()
    connection = Connection(
        name=f"Field {request.node.name[:30]}",
        base_url="https://survey.example.org",
        username="u",
        password_encrypted="",
        project_id=project["id"],
        sync_enabled=True,
        sync_interval_minutes=60,
        last_sync_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10),
    )
    db_session.add(connection)
    job = Job(
        job_type=JobType.sync,
        status=JobStatus.running,
        title=f"Scheduled import from {connection.name}",
        params={"project_id": project["id"], "password": "zip-secret"},
        stages=[
            {"key": "download", "label": "Download", "status": "done", "detail": "", "items": []},
            {"key": "merges", "label": "Rebuild", "status": "running", "detail": "", "items": []},
        ],
    )
    db_session.add(job)
    db_session.commit()
    return {"project": project, "connection": connection.id, "job": job.id}


def test_a_scheduled_import_shows_to_whoever_can_see_its_project(
    client, auth_headers, scheduled
):
    body = client.get("/api/v1/system/activity", headers=auth_headers).json()
    mine = next(one for one in body["jobs"] if one["id"] == scheduled["job"])
    assert mine["status"] == "running"
    assert [stage["status"] for stage in mine["stages"]] == ["done", "running"]
    assert mine["project_name"] == scheduled["project"]["name"]
    assert "params" not in mine and "zip-secret" not in str(body)

    upcoming = {one["connection_id"]: one for one in body["upcoming"]}
    assert scheduled["connection"] in upcoming


def test_nor_to_somebody_who_cannot_see_its_project(client, auth_headers, scheduled):
    email, password = "activity-outsider@example.com", "outsider-password-123"
    made = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": email,
            "full_name": "Outsider",
            "role": "analyst",
            "password": password,
            "restricted_to_projects": True,
        },
    )
    assert made.status_code in (201, 409), made.text
    body = client.get("/api/v1/system/activity", headers=sign_in(client, email, password)).json()
    assert scheduled["job"] not in {one["id"] for one in body["jobs"]}
    assert scheduled["connection"] not in {one["connection_id"] for one in body["upcoming"]}
