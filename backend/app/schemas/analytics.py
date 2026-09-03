from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.analytics import ChartType, WidgetType
from app.schemas.query import QuerySpec


class SavedQueryCreate(BaseModel):
    name: str
    description: str = ""
    dataset_id: str
    spec: QuerySpec


class SavedQueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    dataset_id: str
    spec: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime
    updated_at: dt.datetime


class ChartCreate(BaseModel):
    name: str
    description: str = ""
    dataset_id: str
    chart_type: ChartType = ChartType.bar
    spec: dict[str, Any] = Field(default_factory=dict)


class ChartUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    chart_type: ChartType | None = None
    spec: dict[str, Any] | None = None


class ChartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    dataset_id: str
    chart_type: ChartType
    spec: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime
    updated_at: dt.datetime


class WidgetIn(BaseModel):
    id: str | None = None
    title: str = ""
    widget_type: WidgetType = WidgetType.chart
    chart_id: str | None = None
    indicator_id: str | None = None
    dataset_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)
    position: int = 0
    page: int = 0


class WidgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    title: str = ""
    widget_type: WidgetType
    chart_id: str | None = None
    indicator_id: str | None = None
    dataset_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)
    position: int = 0
    page: int = 0


class DashboardCreate(BaseModel):
    name: str
    description: str = ""
    filters: list[dict[str, Any]] = Field(default_factory=list)
    refresh_interval_seconds: int = 0
    project_id: str | None = None
    pages: list[dict[str, Any]] = Field(default_factory=list)


class DashboardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    filters: list[dict[str, Any]] | None = None
    refresh_interval_seconds: int | None = None
    pages: list[dict[str, Any]] | None = None
    is_public: bool | None = None
    widgets: list[WidgetIn] | None = None


class DashboardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str = ""
    filters: list[dict[str, Any]] = Field(default_factory=list)
    project_id: str | None = None
    pages: list[dict[str, Any]] = Field(default_factory=list)
    is_public: bool = False
    public_token: str | None = None
    refresh_interval_seconds: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime


class DashboardDetail(DashboardOut):
    widgets: list[WidgetOut] = Field(default_factory=list)


class QueryRequest(BaseModel):
    dataset_id: str
    spec: QuerySpec


class ChartRenderRequest(BaseModel):
    """Runs a chart's stored query, optionally with extra dashboard filters."""

    filters: dict[str, Any] | None = None
