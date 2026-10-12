"""Jobs, notifications, audit log and platform health."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, RequireAdmin
from app.core.config import settings
from app.db.base import utcnow
from app.models import AuditLog, Job, Notification, Role
from app.schemas.common import Message, Page
from app.schemas.monitoring import JobOut, NotificationOut
from app.services import preferences
from app.services.audit import record
from app.services.hostnames import base_domain as dashboard_domain

router = APIRouter()


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
    from app.services.export_pdf import why_not as pdf_refusal

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
        # Whether this server can print a dashboard itself. Empty reason means
        # it can; the interface offers the format or says why it cannot,
        # rather than handing somebody a button that answers 503.
        "pdf_export": not pdf_refusal(),
        "pdf_export_reason": pdf_refusal(),
    }
