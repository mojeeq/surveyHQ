"""Background jobs, notifications and the audit trail."""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


class JobType(str, enum.Enum):
    ingest = "ingest"
    sync = "sync"
    export = "export"
    monitor = "monitor"
    quality = "quality"


class Job(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    job_type: Mapped[JobType] = mapped_column(Enum(JobType, name="job_type"))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.queued, index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    celery_task_id: Mapped[str] = mapped_column(String(80), default="")
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Notification(UUIDMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(20), default="info")
    link: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_email: Mapped[str] = mapped_column(String(320), default="")
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)


class SystemSetting(TimestampMixin, Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
