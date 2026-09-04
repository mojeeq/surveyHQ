"""Saved queries, charts, dashboards and widgets."""

from __future__ import annotations

import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class ChartType(str, enum.Enum):
    bar = "bar"
    horizontal_bar = "horizontal_bar"
    stacked_bar = "stacked_bar"
    line = "line"
    area = "area"
    pie = "pie"
    donut = "donut"
    scatter = "scatter"
    table = "table"
    kpi = "kpi"
    heatmap = "heatmap"
    crosstab = "crosstab"
    map = "map"
    gauge = "gauge"
    # A stacked bar lying on its side, and the two-sided bar that a population
    # by age and sex is always drawn as.
    horizontal_stacked_bar = "horizontal_stacked_bar"
    population_pyramid = "population_pyramid"
    funnel = "funnel"


class WidgetType(str, enum.Enum):
    chart = "chart"
    table = "table"
    kpi = "kpi"
    indicator = "indicator"
    text = "text"
    crosstab = "crosstab"
    quality = "quality"
    countdown = "countdown"
    map = "map"
    html = "html"
    freshness = "freshness"


class SavedQuery(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "saved_queries"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Chart(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "charts"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    chart_type: Mapped[ChartType] = mapped_column(
        Enum(ChartType, name="chart_type"), default=ChartType.bar
    )
    # {"query": {...}, "encoding": {...}, "options": {...}}
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Dashboard(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "dashboards"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # A dashboard's widgets can draw on several datasets, so it carries its own
    # project rather than inferring one. Null is the shared area.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Dashboard level filter controls offered to viewers
    filters: Mapped[list] = mapped_column(JSON, default=list)
    # Named pages, e.g. [{"name": "Fieldwork"}, {"name": "Data quality"}]. A
    # dashboard with none behaves as one unnamed page, which is what every
    # dashboard created before pages existed is.
    # A server default so this can be added to a table that already has rows;
    # without one it is NOT NULL with nothing to fill in, and the upgrade has to
    # skip it - which start-up reports as an error rather than silently ignoring.
    pages: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    # Which categorical ordering the charts on this dashboard use. The orders
    # live in the frontend, which is what draws them; the server only remembers
    # the choice, so adding one needs no migration.
    theme: Mapped[str] = mapped_column(
        String(40), default="default", server_default=text("'default'")
    )
    # How the dashboard is dressed: {"background_color": "#0f172a",
    # "background_image": "<file>", "background_fit": "cover", "fade": 0.3,
    # "canvas_width": 2000, "columns": 12, "row_height": 74,
    # "widget_opacity": 0.6, "tab_background": "#ffffff"}. A dict rather than
    # columns because it is presentation, changes often, and nothing queries it.
    appearance: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    public_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    refresh_interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    widgets: Mapped[list[Widget]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="Widget.position",
    )


class Widget(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "widgets"

    dashboard_id: Mapped[str] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    widget_type: Mapped[WidgetType] = mapped_column(
        Enum(WidgetType, name="widget_type"), default=WidgetType.chart
    )
    chart_id: Mapped[str | None] = mapped_column(
        ForeignKey("charts.id", ondelete="SET NULL"), nullable=True
    )
    indicator_id: Mapped[str | None] = mapped_column(
        ForeignKey("indicators.id", ondelete="SET NULL"), nullable=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    # Inline spec for widgets that do not reference a saved chart
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"x": 0, "y": 0, "w": 6, "h": 4}
    layout: Mapped[dict] = mapped_column(JSON, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Index into Dashboard.pages. Zero is the first page, and the page every
    # widget that predates this feature is already on.
    page: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    dashboard: Mapped[Dashboard] = relationship(back_populates="widgets")
