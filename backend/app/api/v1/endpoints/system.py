"""Jobs, notifications, audit log and platform health."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession, RequireAdmin
from app.core.config import settings
from app.db.base import utcnow
from app.models import AuditLog, Connection, Job, JobStatus, JobType, Notification, Project, Role
from app.schemas.common import Message, Page
from app.schemas.monitoring import (
    ActivityJob,
    ActivityOut,
    JobOut,
    NotificationOut,
    ScheduledSync,
)
from app.services import preferences
from app.services.audit import record
from app.services.hostnames import base_domain as dashboard_domain
from app.services.projects import scope_for
from app.services.scheduling import next_due

router = APIRouter()

# How long a finished import stays in the activity panel, so that somebody who
# looks away while it runs can still read what it did.
RECENT_MINUTES = 30


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    db: DbSession, user: CurrentUser, limit: int = Query(default=50, le=200), status: str = ""
) -> list[Job]:
    statement = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if not user.has_role(Role.admin):
        statement = statement.where(Job.created_by == user.id)
    if status:
        statement = statement.where(Job.status == status)
    return list(db.scalars(statement).all())


@router.get("/activity", response_model=ActivityOut)
def activity(db: DbSession, user: CurrentUser) -> ActivityOut:
    """What is happening in the background that this person can see, and what is next.

    The top bar asks this every few seconds while something is running. Not
    the jobs list: that is an administrator's page and shows a person only the
    jobs they started, while a scheduled import is started by nobody and was
    therefore invisible to everybody but an administrator - which is exactly
    the import whose data a dashboard is waiting on. Here a job shows to
    anybody who can see the project it imports into.

    Without its parameters, which can hold an archive's password.
    """
    scope = scope_for(db, user)
    since = utcnow() - dt.timedelta(minutes=RECENT_MINUTES)
    jobs = db.scalars(
        select(Job)
        .where(
            Job.job_type.in_([JobType.sync, JobType.ingest]),
            or_(
                Job.status.in_([JobStatus.queued, JobStatus.running]),
                Job.finished_at >= since,
            ),
        )
        .order_by(Job.created_at.desc())
        .limit(40)
    ).all()
    names = {project.id: project.name for project in db.scalars(select(Project)).all()}

    def visible(job: Job) -> bool:
        if user.has_role(Role.admin) or job.created_by == user.id:
            return True
        project_id = (job.params or {}).get("project_id") or None
        return job.created_by is None and scope.allows(project_id)

    shown = [
        ActivityJob(
            id=job.id,
            job_type=job.job_type.value,
            status=job.status.value,
            title=job.title,
            progress=job.progress or 0.0,
            stages=list(job.stages or []),
            error=job.error,
            warnings=list((job.result or {}).get("warnings") or [])[:20],
            project_name=names.get((job.params or {}).get("project_id") or "", ""),
            started_at=job.started_at,
            finished_at=job.finished_at,
            created_at=job.created_at,
        )
        for job in jobs
        if visible(job)
    ][:15]

    now = utcnow()
    upcoming: list[ScheduledSync] = []
    for connection in db.scalars(
        select(Connection).where(
            Connection.is_active.is_(True), Connection.sync_enabled.is_(True)
        )
    ).all():
        if not scope.allows(connection.project_id):
            continue
        due = next_due(
            mode=connection.sync_mode or "interval",
            times=list(connection.sync_times or []),
            timezone=connection.sync_timezone or "UTC",
            interval_minutes=connection.sync_interval_minutes,
            last_sync_at=connection.last_sync_at,
            now=now,
        )
        if due is not None:
            upcoming.append(
                ScheduledSync(
                    connection_id=connection.id,
                    name=connection.name,
                    project_name=names.get(connection.project_id or "", ""),
                    due_at=due,
                )
            )
    upcoming.sort(key=lambda one: one.due_at)
    return ActivityOut(jobs=shown, upcoming=upcoming[:5])


@router.get("/jobs/{job_id}", response_model=JobOut)
def read_job(job_id: str, db: DbSession, user: CurrentUser) -> Job:
    job = db.get(Job, job_id)
    if job is None or (
        not user.has_role(Role.admin) and (job.created_by is None or job.created_by != user.id)
    ):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    db: DbSession, user: CurrentUser, unread_only: bool = False, limit: int = 50
) -> list[Notification]:
    statement = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    return list(db.scalars(statement).all())


@router.post("/notifications/read-all", response_model=Message)
def mark_all_read(db: DbSession, user: CurrentUser) -> Message:
    notifications = db.scalars(
        select(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    ).all()
    for notification in notifications:
        notification.read_at = utcnow()
    db.commit()
    return Message(detail=f"{len(notifications)} notification(s) marked as read")


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: str, db: DbSession, user: CurrentUser) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_at = utcnow()
    db.commit()
    db.refresh(notification)
    return notification


@router.get("/audit", response_model=Page[dict])
def list_audit(
    db: DbSession,
    _: RequireAdmin,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    action: str = "",
) -> Page[dict[str, Any]]:
    statement = select(AuditLog)
    if action:
        statement = statement.where(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    ).all()
    items = [
        {
            "id": row.id,
            "user_email": row.user_email,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "detail": row.detail,
            "ip_address": row.ip_address,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/settings", response_model=list[dict])
def read_platform_settings(_: RequireAdmin) -> list[dict[str, Any]]:
    """Every setting an administrator may change here, and what it is now.

    Each one carries what `.env` says as well, so the page can show what it
    would go back to and whether anybody has moved it.
    """
    return preferences.catalogue()


@router.put("/settings", response_model=list[dict])
def write_platform_settings(
    changes: dict[str, Any], db: DbSession, user: RequireAdmin
) -> list[dict[str, Any]]:
    """Change some of them, as one transaction.

    All or nothing: a page that saved four of six settings and reported an
    error would leave somebody guessing which four. A secret arriving empty is
    left as it was, because the page never had it to send back.
    """
    recorded: dict[str, Any] = {}
    try:
        for name, given in changes.items():
            if name in preferences.ENCRYPTED and given in (None, ""):
                continue
            recorded[name] = preferences.put(db, name, given)
    except preferences.NotAllowed as exc:
        # Said rather than left to the session's teardown, which would also
        # discard these writes: what this method promises is all or nothing,
        # and a promise kept by something three layers away is a promise
        # waiting to be broken by a change over there.
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if recorded:
        record(
            db,
            user=user,
            action="system.settings",
            entity_type="system",
            entity_id="settings",
            detail=recorded,
        )
    db.commit()
    preferences.forget()
    return preferences.catalogue()


@router.delete("/settings/{name}", response_model=list[dict])
def reset_platform_setting(
    name: str, db: DbSession, user: RequireAdmin
) -> list[dict[str, Any]]:
    """Put one setting back to what `.env` says."""
    try:
        preferences.clear(db, name)
    except preferences.NotAllowed as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    record(
        db,
        user=user,
        action="system.settings.reset",
        entity_type="system",
        entity_id=name,
        detail={"setting": name},
    )
    db.commit()
    preferences.forget()
    return preferences.catalogue()


@router.get("/info", response_model=dict)
def platform_info(_: CurrentUser) -> dict[str, Any]:
    from app import __version__

    return {
        "name": settings.project_name,
        "version": __version__,
        "environment": settings.environment,
        "mail_enabled": preferences.mail_enabled(),
        "max_upload_mb": preferences.value("max_upload_mb"),
        # Empty means no wildcard DNS record and certificate are configured, so
        # the interface does not offer to name a dashboard something that would
        # resolve to nothing.
        "dashboard_domain": dashboard_domain(),
        "supported_formats": [".dta", ".sav", ".csv", ".tab", ".tsv", ".xlsx", ".xls"],
    }
