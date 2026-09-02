"""Survey Solutions server connections and sync history."""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class SyncStatus(str, enum.Enum):
    never = "never"
    running = "running"
    success = "success"
    failed = "failed"


class ExportFormat(str, enum.Enum):
    stata = "STATA"
    tabular = "Tabular"
    spss = "SPSS"


# Two tables share this type, so it is declared once rather than per column.
sync_status_type = Enum(SyncStatus, name="sync_status")


class Connection(UUIDMixin, TimestampMixin, Base):
    """Credentials and sync settings for one Survey Solutions workspace."""

    __tablename__ = "connections"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    workspace: Mapped[str] = mapped_column(String(120), default="primary")
    username: Mapped[str] = mapped_column(String(200), default="")
    password_encrypted: Mapped[str] = mapped_column(Text, default="")
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Sync configuration
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    export_format: Mapped[ExportFormat] = mapped_column(
        Enum(ExportFormat, name="export_format"), default=ExportFormat.stata
    )
    # Which questionnaires to pull; empty means "all"
    questionnaires: Mapped[list] = mapped_column(JSON, default=list)
    interview_status: Mapped[str] = mapped_column(String(50), default="All")

    last_sync_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[SyncStatus] = mapped_column(
        sync_status_type, default=SyncStatus.never
    )
    last_sync_error: Mapped[str] = mapped_column(Text, default="")
    server_info: Mapped[dict] = mapped_column(JSON, default=dict)

    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    runs: Mapped[list[SyncRun]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
        order_by="desc(SyncRun.started_at)",
    )


class SyncRun(UUIDMixin, Base):
    __tablename__ = "sync_runs"

    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), index=True
    )
    questionnaire: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[SyncStatus] = mapped_column(
        sync_status_type, default=SyncStatus.running
    )
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    datasets_created: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    log: Mapped[list] = mapped_column(JSON, default=list)

    connection: Mapped[Connection] = relationship(back_populates="runs")
