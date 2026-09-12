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


class ChartLibraryOut(ChartOut):
    """A saved chart together with the source context needed by the library UI."""

    dataset_name: str
    project_id: str | None = None
    project_name: str | None = None


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


class WidgetPatch(BaseModel):
    """Changes to one widget, for edits that do not rewrite the whole board.

    The references belong here as much as the title does. Without them,
    changing the chart a widget shows had to go through the whole-dashboard
    PATCH, whose contract is "here is the complete widget list" - and the
    editor sent a list of one, which deleted every other widget on every page.

    Each is optional and distinguished by exclude_unset, so a field left out is
    untouched while one sent as null is genuinely cleared.
    """

    title: str | None = None
    page: int | None = None
    layout: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    chart_id: str | None = None
    indicator_id: str | None = None
    dataset_id: str | None = None


class DashboardCreate(BaseModel):
    name: str
    description: str = ""
    filters: list[dict[str, Any]] = Field(default_factory=list)
    refresh_interval_seconds: int = 0
    project_id: str | None = None
    pages: list[dict[str, Any]] = Field(default_factory=list)
    theme: str = "default"
    appearance: dict[str, Any] = Field(default_factory=dict)
    drilldown: list[dict[str, Any]] = Field(default_factory=list)


class DashboardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    filters: list[dict[str, Any]] | None = None
    refresh_interval_seconds: int | None = None
    pages: list[dict[str, Any]] | None = None
    theme: str | None = None
    appearance: dict[str, Any] | None = None
    drilldown: list[dict[str, Any]] | None = None
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
    theme: str = "default"
    appearance: dict[str, Any] = Field(default_factory=dict)
    # The hierarchy the board drills through, outermost first:
    # [{"variable": "province", "label": "Province"}, ...]
    drilldown: list[dict[str, Any]] = Field(default_factory=list)
    is_public: bool = False
    public_token: str | None = None
    public_hostname: str | None = None
    refresh_interval_seconds: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime


class DashboardDetail(DashboardOut):
    widgets: list[WidgetOut] = Field(default_factory=list)


class DashboardViewIn(BaseModel):
    """A named filter selection saved against a dashboard."""

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    state: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    is_shared: bool = True


class DashboardViewPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    state: dict[str, Any] | None = None
    is_default: bool | None = None
    is_shared: bool | None = None


class DashboardViewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    name: str
    description: str = ""
    state: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    is_shared: bool = True
    created_by: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class WidgetCommentIn(BaseModel):
    widget_id: str
    body: str = Field(min_length=1, max_length=4000)
    # The saved view this is being said under, if one is open. Empty means it
    # is said of the board itself and will be shown under every view.
    view_id: str | None = None
    # The comment being answered, for a reply. One level only.
    parent_id: str | None = None


class WidgetCommentPatch(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    is_resolved: bool | None = None


class WidgetCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    widget_id: str
    view_id: str | None = None
    parent_id: str | None = None
    body: str
    is_resolved: bool = False
    created_by: str | None = None
    # Who said it, resolved once here rather than left to the browser to look
    # up an id per comment. Their name if they gave one, otherwise the address.
    author_name: str = ""
    created_at: dt.datetime
    updated_at: dt.datetime


class PageMove(BaseModel):
    """Move the page at one position to another."""

    from_index: int = Field(ge=0, alias="from")
    to_index: int = Field(ge=0, alias="to")

    model_config = ConfigDict(populate_by_name=True)


class HostnameIn(BaseModel):
    """A name for a shared dashboard: a label, or the whole hostname."""

    hostname: str = ""


class QueryRequest(BaseModel):
    dataset_id: str
    spec: QuerySpec


class ChartRenderRequest(BaseModel):
    """Runs a chart's stored query, optionally with extra dashboard filters."""

    filters: dict[str, Any] | None = None


class HtmlSnippetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    html: str = ""
    """Which project this belongs to. Empty is the shared library, which is
    what makes a snippet reusable across projects."""
    project_id: str | None = None


class HtmlSnippetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    html: str | None = None
    project_id: str | None = None


class HtmlSnippetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    html: str = ""
    project_id: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
