"""Jobs, notifications, audit log and platform health."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, RequireAdmin
from app.core.config import settings
from app.db.base import utcnow
from app.models import AuditLog, Job, Notification
from app.schemas.common import Message, Page
from app.schemas.monitoring import JobOut, NotificationOut

router = APIRouter()


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    db: DbSession, _: CurrentUser, limit: int = Query(default=50, le=200), status: str = ""
) -> list[Job]:
    statement = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(Job.status == status)
    return list(db.scalars(statement).all())


@router.get("/jobs/{job_id}", response_model=JobOut)
def read_job(job_id: str, db: DbSession, _: CurrentUser) -> Job:
    job = db.get(Job, job_id)
    if job is None:
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


@router.get("/info", response_model=dict)
def platform_info(_: CurrentUser) -> dict[str, Any]:
    from app import __version__

    return {
        "name": settings.project_name,
        "version": __version__,
        "environment": settings.environment,
        "mail_enabled": settings.mail_enabled,
        "max_upload_mb": settings.max_upload_mb,
        "supported_formats": [".dta", ".sav", ".csv", ".tab", ".tsv", ".xlsx", ".xls"],
    }
