from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.scheduling import valid_time, valid_timezone, valid_weekday

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
    group_id: str = ""


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
    group_id: str = ""


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
    group_id: str | None = None
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
    groups: list[dict[str, Any]] = Field(default_factory=list)
    theme: str = "default"
    appearance: dict[str, Any] = Field(default_factory=dict)
    drilldown: list[dict[str, Any]] = Field(default_factory=list)


class DashboardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    filters: list[dict[str, Any]] | None = None
    refresh_interval_seconds: int | None = None
    pages: list[dict[str, Any]] | None = None
    groups: list[dict[str, Any]] | None = None
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
    # Named boxes behind the widgets that belong to them:
    # [{"id": "g1", "name": "Fieldwork", "page": 0, "collapsed": false}]
    groups: list[dict[str, Any]] = Field(default_factory=list)
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


class SketchBlock(BaseModel):
    """One widget, as small as it can be described and still be drawn.

    What a thumbnail of a board needs is where its widgets are and what kind
    they are. Not their titles, their configs or their chart references: the
    list page draws a shape, and sending a census board's full widget list to
    draw a shape 240 pixels wide would be sending a hundred times what is used.

    The layout is passed on as it is stored, which is sometimes empty - a
    widget added before anybody dragged it has no position of its own. Filling
    that in is the board's rule, not this schema's, and it is applied in the
    one place that already owns it.
    """

    kind: WidgetType
    layout: dict[str, Any] = Field(default_factory=dict)


class DashboardCard(DashboardOut):
    """A dashboard as the list page shows it: its shape, not its contents.

    `sketch` is the first page only, which is what opening the board would
    show, and `widget_count` is the whole board, which is what tells you
    whether there is more behind the first page.
    """

    sketch: list[SketchBlock] = Field(default_factory=list)
    widget_count: int = 0
    page_count: int = 1


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


class SnapshotSchedule(BaseModel):
    """When to keep a copy of the board, and how many to keep."""

    enabled: bool = False
    # "HH:MM", validated against the same pattern connections use.
    times: list[str] = Field(default_factory=list)
    # Monday 0 through Sunday 6. Empty is every day.
    days: list[int] = Field(default_factory=list)
    timezone: str = "UTC"
    keep: int = Field(default=12, ge=1, le=365)

    @field_validator("times")
    @classmethod
    def _times_are_times(cls, value: list[str]) -> list[str]:
        for text in value:
            if not valid_time(text):
                raise ValueError(f"{text!r} is not a time of day, e.g. 08:00")
        return value

    @field_validator("days")
    @classmethod
    def _days_are_weekdays(cls, value: list[int]) -> list[int]:
        for day in value:
            if not valid_weekday(day):
                raise ValueError("A weekday is 0 (Monday) through 6 (Sunday)")
        # Sorted and deduplicated so [2, 0, 0] and [0, 2] are the same schedule
        # rather than two spellings of it.
        return sorted(set(value))

    @field_validator("timezone")
    @classmethod
    def _timezone_is_real(cls, value: str) -> str:
        if not valid_timezone(value):
            raise ValueError(f"{value!r} is not a time zone this server knows")
        return value


class DashboardSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    label: str
    taken_at: dt.datetime
    size_bytes: int = 0
    is_automatic: bool = False
    created_by: str | None = None
