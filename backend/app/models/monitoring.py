"""Indicators, alerts and data quality rules - the monitoring core."""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Direction(str, enum.Enum):
    """Whether a rising value is good or bad, used for colour coding."""

    higher_is_better = "higher_is_better"
    lower_is_better = "lower_is_better"
    neutral = "neutral"


class Severity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class AlertStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class CheckType(str, enum.Enum):
    missing_rate = "missing_rate"
    value_range = "value_range"
    duplicates = "duplicates"
    outliers = "outliers"
    consistency = "consistency"
    interview_duration = "interview_duration"
    gps_missing = "gps_missing"
    constant_value = "constant_value"


class Indicator(UUIDMixin, TimestampMixin, Base):
    """A single tracked number, e.g. 'completed interviews' or 'mean age'."""

    __tablename__ = "indicators"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    # A query spec producing exactly one measure and at most one dimension
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    unit: Mapped[str] = mapped_column(String(40), default="")
    value_format: Mapped[str] = mapped_column(String(40), default="number")
    target_value: Mapped[float | None] = mapped_column(Float)
    warning_threshold: Mapped[float | None] = mapped_column(Float)
    critical_threshold: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[Direction] = mapped_column(
        Enum(Direction, name="indicator_direction"), default=Direction.higher_is_better
    )
    # Optional variable used to break the indicator down (region, team, ...)
    breakdown_variable: Mapped[str] = mapped_column(String(300), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    last_value: Mapped[float | None] = mapped_column(Float)
    last_computed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    snapshots: Mapped[list[IndicatorSnapshot]] = relationship(
        back_populates="indicator",
        cascade="all, delete-orphan",
        order_by="desc(IndicatorSnapshot.computed_at)",
    )


class IndicatorSnapshot(UUIDMixin, Base):
    """Historical values, so the platform can show trends over the field period."""

    __tablename__ = "indicator_snapshots"

    indicator_id: Mapped[str] = mapped_column(
        ForeignKey("indicators.id", ondelete="CASCADE"), index=True
    )
    value: Mapped[float | None] = mapped_column(Float)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)

    indicator: Mapped[Indicator] = relationship(back_populates="snapshots")


class AlertRule(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "alert_rules"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    indicator_id: Mapped[str | None] = mapped_column(
        ForeignKey("indicators.id", ondelete="CASCADE"), nullable=True, index=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # {"operator": "lt", "value": 100} evaluated against the indicator value
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="alert_severity"), default=Severity.warning
    )
    # ["in_app", "email"]
    channels: Mapped[list] = mapped_column(JSON, default=lambda: ["in_app"])
    recipients: Mapped[list] = mapped_column(JSON, default=list)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    alerts: Mapped[list[Alert]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class Alert(UUIDMixin, Base):
    __tablename__ = "alerts"

    rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="alert_severity"), default=Severity.warning
    )
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus, name="alert_status"), default=AlertStatus.open, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    rule: Mapped[AlertRule | None] = relationship(back_populates="alerts")


class QualityRule(UUIDMixin, TimestampMixin, Base):
    """Automated data quality check run against a dataset."""

    __tablename__ = "quality_rules"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    check_type: Mapped[CheckType] = mapped_column(Enum(CheckType, name="check_type"))
    # Check specific parameters, e.g. {"variable": "age", "min": 0, "max": 120}
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="alert_severity"), default=Severity.warning
    )
    # Fail the check when the share of offending rows exceeds this fraction
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    results: Mapped[list[QualityResult]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        order_by="desc(QualityResult.run_at)",
    )


class QualityResult(UUIDMixin, Base):
    __tablename__ = "quality_results"

    rule_id: Mapped[str] = mapped_column(
        ForeignKey("quality_rules.id", ondelete="CASCADE"), index=True
    )
    run_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_rows: Mapped[int] = mapped_column(BigInteger, default=0)
    total_rows: Mapped[int] = mapped_column(BigInteger, default=0)
    failure_rate: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str] = mapped_column(Text, default="")

    rule: Mapped[QualityRule] = relationship(back_populates="results")
