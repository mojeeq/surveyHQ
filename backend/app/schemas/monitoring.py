from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.monitoring import (
    AlertStatus,
    CheckType,
    Direction,
    Severity,
)
from app.schemas.query import FilterGroup, QuerySpec


class IndicatorCreate(BaseModel):
    name: str
    description: str = ""
    dataset_id: str
    spec: QuerySpec
    unit: str = ""
    value_format: str = "number"
    target_value: float | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    direction: Direction = Direction.higher_is_better
    breakdown_variable: str = ""
    percent_of: Literal["", "all_rows", "answered"] = ""
    display_order: int = 0


class IndicatorUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    spec: QuerySpec | None = None
    unit: str | None = None
    value_format: str | None = None
    target_value: float | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    direction: Direction | None = None
    breakdown_variable: str | None = None
    percent_of: Literal["", "all_rows", "answered"] | None = None
    is_active: bool | None = None
    display_order: int | None = None


class IndicatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    dataset_id: str
    spec: dict[str, Any] = Field(default_factory=dict)
    unit: str = ""
    value_format: str = "number"
    target_value: float | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    direction: Direction
    breakdown_variable: str = ""
    percent_of: str = ""
    is_active: bool = True
    display_order: int = 0
    last_value: float | None = None
    last_computed_at: dt.datetime | None = None
    created_at: dt.datetime


class IndicatorValue(BaseModel):
    indicator_id: str
    name: str
    value: float | None = None
    unit: str = ""
    value_format: str = "number"
    target_value: float | None = None
    progress_percent: float | None = None
    status: str = "unknown"
    direction: Direction = Direction.higher_is_better
    breakdown: dict[str, float] = Field(default_factory=dict)
    breakdown_variable: str = ""
    computed_at: dt.datetime | None = None
    error: str | None = None
    trend: list[dict[str, Any]] = Field(default_factory=list)


class AlertRuleCreate(BaseModel):
    name: str
    description: str = ""
    indicator_id: str | None = None
    dataset_id: str | None = None
    condition: dict[str, Any] = Field(default_factory=lambda: {"operator": "lt", "value": 0})
    severity: Severity = Severity.warning
    channels: list[str] = Field(default_factory=lambda: ["in_app"])
    recipients: list[str] = Field(default_factory=list)
    cooldown_minutes: int = 60


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    condition: dict[str, Any] | None = None
    severity: Severity | None = None
    channels: list[str] | None = None
    recipients: list[str] | None = None
    cooldown_minutes: int | None = None
    is_active: bool | None = None


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    indicator_id: str | None = None
    dataset_id: str | None = None
    condition: dict[str, Any] = Field(default_factory=dict)
    severity: Severity
    channels: list[str] = Field(default_factory=list)
    recipients: list[str] = Field(default_factory=list)
    cooldown_minutes: int
    is_active: bool
    last_triggered_at: dt.datetime | None = None
    created_at: dt.datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_id: str | None = None
    title: str = ""
    message: str = ""
    severity: Severity
    status: AlertStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime
    acknowledged_at: dt.datetime | None = None
    resolved_at: dt.datetime | None = None


class QualityRuleCreate(BaseModel):
    name: str
    dataset_id: str
    check_type: CheckType
    config: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = Severity.warning
    threshold: float = 0.0
    # Restricts the check to part of the dataset. Both the failing rows and the
    # total are counted inside it, so the failure rate stays a rate of what the
    # check actually looked at.
    filters: FilterGroup = Field(default_factory=FilterGroup)


class QualityRuleUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    severity: Severity | None = None
    threshold: float | None = None
    is_active: bool | None = None
    filters: FilterGroup | None = None


class QualityRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    dataset_id: str
    check_type: CheckType
    config: dict[str, Any] = Field(default_factory=dict)
    severity: Severity
    threshold: float
    is_active: bool
    filters: FilterGroup = Field(default_factory=FilterGroup)
    created_at: dt.datetime


class QualityResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_id: str
    run_at: dt.datetime
    passed: bool
    failed_rows: int
    total_rows: int
    failure_rate: float
    details: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class QualityRuleWithResult(QualityRuleOut):
    latest_result: QualityResultOut | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str = ""
    body: str = ""
    level: str = "info"
    link: str = ""
    created_at: dt.datetime
    read_at: dt.datetime | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: str
    status: str
    title: str = ""
    progress: float = 0.0
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    created_at: dt.datetime
