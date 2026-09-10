"""Saved queries, charts, dashboards and widgets."""

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


class HtmlSnippet(UUIDMixin, TimestampMixin, Base):
    """A saved HTML embed, so one can be reused instead of pasted again.

    An embed is usually a map, a video, or a bureau's own banner, and the same
    one belongs on several dashboards - often across several surveys. Pasting
    the markup into each widget meant the copies drifted: a corrected link was
    fixed on one dashboard and left wrong on four.

    A snippet in the shared area (project_id null) is available to every
    project, which is the point of a library; one given a project stays with
    it, for an embed that is nobody else's business.
    """

    __tablename__ = "html_snippets"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    html: Mapped[str] = mapped_column(Text, default="")
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ShareLink(UUIDMixin, TimestampMixin, Base):
    """One published address for a dashboard, of possibly several.

    A dashboard is rarely shown to one audience. The same board goes to a
    minister, to the field supervisors, and to a donor, and those want
    different lifetimes: the donor's link is closed when the report is filed,
    the supervisors keep theirs for the season. One link for all of them meant
    closing any of them closed all of them, so the answer was to make and
    unmake dashboards instead.

    A password is optional and is held as a hash. It is not a login: everyone
    who has it is the same anonymous reader, and it exists to keep a forwarded
    link from being a public one, not to identify anybody.
    """

    __tablename__ = "share_links"

    dashboard_id: Mapped[str] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Closed rather than deleted keeps the row, so reopening restores the same
    # address: a link already pasted into a ministry email is worth being able
    # to switch back on.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # When the link stops opening, if it was given a date. Held rather than
    # acted on by a job: a link that expires while nobody is watching must
    # already be shut when the next reader arrives, and a nightly sweep would
    # leave it open until the sweep ran.
    expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_hash: Mapped[str] = mapped_column(String(200), default="")
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    last_viewed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    # A hostname this dashboard answers on, e.g. "labour-force.dash.gov.vu".
    # Unique so two dashboards cannot claim one name - though the uniqueness
    # that matters is checked in Python as well, because a column added to an
    # existing database by ALTER TABLE arrives without its index.
    public_hostname: Mapped[str | None] = mapped_column(
        String(253), unique=True, index=True
    )
    # The hierarchy the whole board drills through, outermost first, e.g.
    # [{"variable": "province", "label": "Province"}, {"variable": "district"}].
    # One list for the dashboard rather than one per chart: drilling is a
    # question asked of the board ("show me Malampa"), and a page whose charts
    # each sat at their own level would answer several questions at once.
    drilldown: Mapped[list] = mapped_column(
        JSON, default=list, server_default=text("'[]'")
    )
    refresh_interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    views: Mapped[list[DashboardView]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardView.name",
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


class DashboardView(UUIDMixin, TimestampMixin, Base):
    """A named filter selection somebody wants to come back to.

    A monitoring board is read the same few ways over and over - "Malampa, this
    week", "everything a supervisor rejected" - and setting the filters by hand
    each morning is where the reading stops happening. A view is that selection
    under a name, not a copy of the board: the widgets, layout and data are the
    dashboard's, and only what was chosen lives here.
    """

    __tablename__ = "dashboard_views"

    dashboard_id: Mapped[str] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # What was selected: {"page": 1, "filters": {"province": "Malampa"},
    # "drill": [{"variable": "province", "value": "Malampa"}]}. A dict because
    # a board's controls change, and a view that names a filter the board no
    # longer offers should be ignored rather than refuse to open.
    state: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    # Opened instead of the empty board. At most one per dashboard, which is
    # enforced where views are written rather than by a constraint: two rows
    # both claiming it is a display question, not a corruption.
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Whether a reader who is not the author sees it, including through a
    # shared link. A private view is one person's shortcut.
    is_shared: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    dashboard: Mapped[Dashboard] = relationship(back_populates="views")
