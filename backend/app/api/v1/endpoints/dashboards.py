"""Charts, dashboards, widgets and public sharing."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from slugify import slugify
from sqlalchemy import or_, select

from app.api.deps import (
    CurrentUser,
    DbSession,
    RequireAnalyst,
    get_ready_dataset,
)
from app.core.security import hash_password, new_public_token
from app.db.base import utcnow
from app.models import (
    BoundaryLayer,
    Chart,
    Dashboard,
    DashboardView,
    Dataset,
    HtmlSnippet,
    Indicator,
    IndicatorSnapshot,
    QualityResult,
    QualityRule,
    Role,
    ShareLink,
    User,
    Widget,
)
from app.schemas.analytics import (
    ChartCreate,
    ChartOut,
    ChartUpdate,
    DashboardCreate,
    DashboardDetail,
    DashboardOut,
    DashboardUpdate,
    DashboardViewIn,
    DashboardViewOut,
    DashboardViewPatch,
    HostnameIn,
    HtmlSnippetIn,
    HtmlSnippetOut,
    HtmlSnippetUpdate,
    PageMove,
    WidgetIn,
    WidgetPatch,
)
from app.schemas.common import Message
from app.schemas.query import (
    CrosstabRequest,
    CrosstabResult,
    FilterGroup,
    QueryResult,
    QuerySpec,
)
from app.services import boundary_store, multiselect, quality, static_export
from app.services.audit import record
from app.services.boundaries import Areas
from app.services.dashboard_assets import (
    BackgroundError,
    background_file,
    remove_all,
    remove_background,
    save_background,
)
from app.services.datasets import dataset_is_queryable
from app.services.freshness import (
    DEFAULT_CRITICAL_HOURS,
    DEFAULT_WARN_HOURS,
)
from app.services.freshness import report as freshness_report
from app.services.geo import check_areas
from app.services.geo import points as geo_points
from app.services.hostnames import HostnameError
from app.services.hostnames import normalise as normalise_hostname
from app.services.monitoring import (
    breakdown_progress,
    evaluate_indicator,
    indicator_status,
    progress_percent,
)
from app.services.projects import (
    can_edit,
    can_view,
    dataset_clause,
    in_project_clause,
    restrict,
    scope_for,
)
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    distinct_values,
    execute_crosstab,
    execute_query,
)
from app.services.sharing import as_utc, link_expired
from app.services.stata_expr import ExpressionError

router = APIRouter()


# --- charts ----------------------------------------------------------------


@router.get("/charts", response_model=list[ChartOut])
def list_charts(
    db: DbSession,
    user: CurrentUser,
    dataset_id: str = "",
    project_id: str | None = None,
) -> list[Chart]:
    """Saved charts, optionally only the ones belonging to a project.

    A chart takes its project from its dataset, like everything else built on
    one. `project_id=none` is the shared area, which is a real place rather
    than the absence of a filter.
    """
    statement = restrict(
        select(Chart).order_by(Chart.created_at.desc()),
        dataset_clause(db, user, Chart.dataset_id),
    )
    if dataset_id:
        statement = statement.where(Chart.dataset_id == dataset_id)
    if project_id is not None:
        statement = statement.where(
            in_project_clause(Chart.dataset_id, "" if project_id == "none" else project_id)
        )
    return list(db.scalars(statement).all())


@router.post("/charts", response_model=ChartOut, status_code=201)
def create_chart(payload: ChartCreate, db: DbSession, user: RequireAnalyst) -> Chart:
    get_ready_dataset(payload.dataset_id, db, user)
    _validate_chart_spec(payload.spec)
    chart = Chart(
        name=payload.name,
        description=payload.description,
        dataset_id=payload.dataset_id,
        chart_type=payload.chart_type,
        spec=payload.spec,
        created_by=user.id,
    )
    db.add(chart)
    db.commit()
    db.refresh(chart)
    return chart


@router.get("/charts/{chart_id}", response_model=ChartOut)
def read_chart(chart_id: str, db: DbSession, user: CurrentUser) -> Chart:
    return _get_chart(chart_id, db, user)


@router.patch("/charts/{chart_id}", response_model=ChartOut)
def update_chart(
    chart_id: str, payload: ChartUpdate, db: DbSession, user: RequireAnalyst
) -> Chart:
    chart = _get_chart(chart_id, db, user)
    data = payload.model_dump(exclude_unset=True)
    if "spec" in data:
        _validate_chart_spec(data["spec"])
    for field, value in data.items():
        setattr(chart, field, value)
    db.commit()
    db.refresh(chart)
    return chart


@router.delete("/charts/{chart_id}", response_model=Message)
def delete_chart(chart_id: str, db: DbSession, user: RequireAnalyst) -> Message:
    chart = _get_chart(chart_id, db, user)
    db.delete(chart)
    db.commit()
    return Message(detail="Chart deleted")


@router.post("/charts/{chart_id}/data", response_model=QueryResult | CrosstabResult)
def render_chart(
    chart_id: str, db: DbSession, user: CurrentUser, filters: FilterGroup | None = None
) -> QueryResult | CrosstabResult:
    """Execute a saved chart or cross-tabulation, narrowed by dashboard filters."""
    chart = _get_chart(chart_id, db, user)
    dataset = get_ready_dataset(chart.dataset_id, db, user)
    ctx = DatasetContext.from_model(dataset)
    filters = _applicable(filters, ctx)
    try:
        if _is_crosstab(chart.spec or {}):
            return execute_crosstab(ctx, _crosstab_from_chart(chart, filters))
        if _is_multiselect(chart.spec or {}):
            return _multiselect_result(ctx, chart.spec or {}, filters)
        return execute_query(ctx, _spec_from_chart(chart, filters))
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _get_chart(chart_id: str, db: DbSession, user: User) -> Chart:
    chart = db.get(Chart, chart_id)
    # A chart follows its dataset's project; it does not carry one of its own.
    if chart is None:
        raise HTTPException(status_code=404, detail="Chart not found")
    dataset = db.get(Dataset, chart.dataset_id)
    if dataset is None or not can_view(db, user, dataset.project_id):
        raise HTTPException(status_code=404, detail="Chart not found")
    return chart


def _applicable(filters: FilterGroup | None, ctx: DatasetContext) -> FilterGroup | None:
    """Drop conditions naming variables this dataset does not have.

    A dashboard's widgets can draw on several datasets - the interview level,
    the person level, the paradata - and a filter on "province" is meaningful
    only to those that carry it. Passing it to the rest would fail the query and
    replace those widgets with an error, so a dashboard-level filter narrows
    what it can and leaves the others as they were.
    """
    if filters is None or filters.is_empty():
        return filters
    known = set(ctx.variables)

    def prune(group: FilterGroup) -> FilterGroup:
        return FilterGroup(
            op=group.op,
            conditions=[c for c in group.conditions if c.variable in known],
            groups=[prune(g) for g in group.groups],
        )

    pruned = prune(filters)
    return None if pruned.is_empty() else pruned


def _ignored(filters: FilterGroup | None, ctx: DatasetContext) -> list[str]:
    """The variables a dashboard filter names that this dataset cannot honour.

    Dropping them silently is what makes a filter look broken: the widget goes
    on showing every row and nothing says why. Reported so the widget can.
    """
    if filters is None or filters.is_empty():
        return []
    known = set(ctx.variables)
    missing: list[str] = []

    def walk(group: FilterGroup) -> None:
        for condition in group.conditions:
            if condition.variable not in known and condition.variable not in missing:
                missing.append(condition.variable)
        for nested in group.groups:
            walk(nested)

    walk(filters)
    return missing


def _is_crosstab(spec: dict[str, Any]) -> bool:
    return bool(spec.get("crosstab"))


def _is_multiselect(spec: dict[str, Any]) -> bool:
    return bool((spec.get("multiselect") or {}).get("columns"))


def _multiselect_result(ctx: DatasetContext, spec: dict[str, Any], filters: FilterGroup | None):
    """Run a stored "tick all that apply" chart.

    It comes back as an ordinary result - one row per option - so every chart
    type, the table view and click-to-filter all work on it without knowing
    that the question was spread across a dozen columns in the file.
    """
    saved = spec.get("multiselect") or {}
    own = FilterGroup.model_validate(saved.get("filters") or {})
    # The page's filters on top of the chart's own, the same way every other
    # widget combines them.
    combined = (
        FilterGroup(op="and", conditions=[], groups=[own, filters])
        if filters and not filters.is_empty()
        else own
    )
    return multiselect.tabulate(
        ctx,
        list(saved.get("columns") or []),
        combined,
        percent_of=str(saved.get("percent_of") or "respondents"),
        sort=str(saved.get("sort") or "value_desc"),
        show=str(saved.get("show") or "both"),
    )


def _spec_variables(raw: dict[str, Any]) -> set[str]:
    """The variables a stored widget query groups on, best effort.

    A spec that no longer validates is a broken widget, not a reason to fail
    the whole dashboard, and it puts nothing on screen either way.
    """
    try:
        spec = QuerySpec.model_validate(raw.get("query", raw))
    except Exception:  # noqa: BLE001 - an unreadable spec simply shows nothing
        return set()
    return {dimension.variable for dimension in spec.dimensions if dimension.variable}


def visible_variables(db: DbSession, dashboard: Dashboard) -> set[str]:
    """Every variable this dashboard puts on screen.

    Used to bound what a filter arriving from outside may name. A dashboard's
    widgets are drawn from a whole dataset, and a filter is evaluated against
    that dataset rather than against the widget, so an arbitrary filter is a
    question about any column in the file - including the ones the dashboard
    deliberately does not show. Ask "how many interviews have phone number
    5551234" and a count of one is an answer, repeated until it is a list.

    What is already on screen carries no such risk: filtering by a category the
    viewer can read off an axis tells them nothing they could not see. So the
    axes are the allowance, along with the filter controls the author put on the
    dashboard themselves - which together are exactly what the shared page's UI
    can produce: a click on a mark, or a choice from a dropdown that was put
    there to be chosen from.
    """
    names: set[str] = {
        str((control or {}).get("variable") or "")
        for control in (dashboard.filters or [])
        if isinstance(control, dict)
    }
    for widget in dashboard.widgets:
        config = widget.config or {}
        if widget.chart_id:
            chart = db.get(Chart, widget.chart_id)
            if chart is None:
                continue
            spec = chart.spec or {}
            if _is_crosstab(spec):
                crosstab = spec.get("crosstab") or {}
                names.update(
                    str(crosstab.get(key) or "")
                    for key in ("row_variable", "column_variable")
                )
            else:
                names.update(_spec_variables(spec))
            continue
        if widget.widget_type.value == "map":
            names.update(str(config.get(key) or "") for key in ("latitude", "longitude"))
            names.update(str(name) for name in (config.get("detail") or []))
            names.add(str(config.get("measure_variable") or ""))
            continue
        if widget.widget_type.value == "indicator" and widget.indicator_id:
            if config.get("show_breakdown"):
                indicator = db.get(Indicator, widget.indicator_id)
                if indicator is not None and indicator.breakdown_variable:
                    names.add(indicator.breakdown_variable)
            continue
        names.update(_spec_variables(config))
    names.discard("")
    return names


def restrict_to_visible(
    filters: FilterGroup | None, allowed: set[str]
) -> FilterGroup | None:
    """Drop every condition naming something the dashboard does not show."""
    if filters is None or filters.is_empty():
        return filters

    def prune(group: FilterGroup) -> FilterGroup:
        return FilterGroup(
            op=group.op,
            conditions=[c for c in group.conditions if c.variable in allowed],
            groups=[prune(g) for g in group.groups],
        )

    pruned = prune(filters)
    return None if pruned.is_empty() else pruned


def _validate_chart_spec(spec: dict[str, Any]) -> None:
    try:
        if _is_crosstab(spec):
            CrosstabRequest.model_validate(spec["crosstab"])
        else:
            QuerySpec.model_validate(spec.get("query", spec))
    except Exception as exc:  # noqa: BLE001 - surface a readable message to the UI
        raise HTTPException(status_code=422, detail=f"Invalid chart query: {exc}") from exc


def _crosstab_from_chart(chart: Chart, extra: FilterGroup | None) -> CrosstabRequest:
    request = CrosstabRequest.model_validate((chart.spec or {})["crosstab"])
    if extra and not extra.is_empty():
        return request.model_copy(
            update={
                "filters": FilterGroup(
                    op="and", conditions=[], groups=[request.filters, extra]
                )
            }
        )
    return request


def _spec_from_chart(chart: Chart, extra: FilterGroup | None) -> QuerySpec:
    raw = (chart.spec or {}).get("query", chart.spec or {})
    spec = QuerySpec.model_validate(raw)
    if extra and not extra.is_empty():
        combined = FilterGroup(op="and", conditions=[], groups=[spec.filters, extra])
        spec = spec.model_copy(update={"filters": combined})
    return spec


@dataclass(frozen=True)
class Drill:
    """How far down a board's hierarchy the reader has clicked.

    `levels` is the dashboard's hierarchy, outermost first. `depth` is how many
    steps down the reader has taken; the values chosen on the way arrive as
    ordinary filter conditions, so only the depth has to travel separately.
    """

    levels: tuple[str, ...] = ()
    depth: int = 0

    @classmethod
    def of(cls, dashboard: Dashboard, depth: int) -> Drill:
        levels = tuple(
            str(item.get("variable") or "").strip()
            for item in (dashboard.drilldown or [])
            if isinstance(item, dict) and str(item.get("variable") or "").strip()
        )
        return cls(levels=levels, depth=max(0, min(int(depth or 0), len(levels))))

    def target(self, variable: str) -> str:
        """The level a chart grouped on `variable` should be drawn at.

        A chart never climbs above the level it was built for: a district chart
        stays on districts while the board is looking at a province, and only
        follows once the reader has gone deeper than it. A chart grouped on
        something outside the hierarchy is left alone.
        """
        if not self.levels or self.depth <= 0 or variable not in self.levels:
            return variable
        base = self.levels.index(variable)
        return self.levels[min(max(base, self.depth), len(self.levels) - 1)]


def _drilled(spec: QuerySpec, ctx: DatasetContext, drill: Drill | None) -> QuerySpec:
    """Regroup a chart at the level the board has drilled to."""
    if drill is None or not spec.dimensions:
        return spec
    first = spec.dimensions[0]
    variable = drill.target(first.variable)
    # A dataset that does not carry the deeper level cannot answer at it, so
    # that chart stays where it is rather than erroring out the whole page.
    if variable == first.variable or variable not in ctx.variables:
        return spec
    dimensions = list(spec.dimensions)
    # The output name is kept, because a saved sort or a top-N refers to it by
    # name. What is drawn beside the axis is the variable's own label, which
    # follows the new variable.
    dimensions[0] = first.model_copy(
        update={"variable": variable, "alias": first.output_name}
    )
    return spec.model_copy(update={"dimensions": dimensions})


# --- the HTML embed library ------------------------------------------------
#
# An embed is usually a map, a video or a bureau's own banner, and the same one
# belongs on several dashboards, often across surveys. Pasting the markup into
# each widget let the copies drift, so a corrected link was fixed in one place
# and left wrong in four.


def _get_snippet(snippet_id: str, db: DbSession, user: User) -> HtmlSnippet:
    snippet = db.get(HtmlSnippet, snippet_id)
    if snippet is None or not can_view(db, user, snippet.project_id):
        raise HTTPException(status_code=404, detail="Snippet not found")
    return snippet


@router.get("/html-snippets", response_model=list[HtmlSnippetOut])
def list_snippets(
    db: DbSession, user: CurrentUser, project_id: str = ""
) -> list[HtmlSnippet]:
    """The library: this project's snippets plus every shared one.

    Unlike the widget pickers, a project filter here does not hide the shared
    area. Reusing one embed across projects is the whole feature, so narrowing
    to a project must still offer the snippets that belong to everybody.
    """
    statement = restrict(
        select(HtmlSnippet).order_by(HtmlSnippet.name),
        scope_for(db, user).filter(HtmlSnippet.project_id),
    )
    if project_id and project_id != "none":
        statement = statement.where(
            or_(
                HtmlSnippet.project_id == project_id,
                HtmlSnippet.project_id.is_(None),
            )
        )
    elif project_id == "none":
        statement = statement.where(HtmlSnippet.project_id.is_(None))
    return list(db.scalars(statement).all())


@router.post("/html-snippets", response_model=HtmlSnippetOut, status_code=201)
def create_snippet(
    payload: HtmlSnippetIn, db: DbSession, user: RequireAnalyst
) -> HtmlSnippet:
    if payload.project_id and not can_edit(db, user, payload.project_id, Role.analyst):
        raise HTTPException(status_code=404, detail="Project not found")
    snippet = HtmlSnippet(
        name=payload.name,
        description=payload.description,
        html=payload.html,
        project_id=payload.project_id or None,
        created_by=user.id,
    )
    db.add(snippet)
    record(db, user=user, action="create_html_snippet", entity_type="html_snippet")
    db.commit()
    db.refresh(snippet)
    return snippet


@router.patch("/html-snippets/{snippet_id}", response_model=HtmlSnippetOut)
def update_snippet(
    snippet_id: str, payload: HtmlSnippetUpdate, db: DbSession, user: RequireAnalyst
) -> HtmlSnippet:
    snippet = _get_snippet(snippet_id, db, user)
    if snippet.project_id and not can_edit(db, user, snippet.project_id, Role.analyst):
        raise HTTPException(status_code=404, detail="Snippet not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("project_id") and not can_edit(db, user, data["project_id"], Role.analyst):
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in data.items():
        setattr(snippet, field, value or None if field == "project_id" else value)
    record(
        db,
        user=user,
        action="update_html_snippet",
        entity_type="html_snippet",
        entity_id=snippet_id,
    )
    db.commit()
    db.refresh(snippet)
    return snippet


@router.delete("/html-snippets/{snippet_id}", response_model=Message)
def delete_snippet(snippet_id: str, db: DbSession, user: RequireAnalyst) -> Message:
    snippet = _get_snippet(snippet_id, db, user)
    if snippet.project_id and not can_edit(db, user, snippet.project_id, Role.analyst):
        raise HTTPException(status_code=404, detail="Snippet not found")
    name = snippet.name
    db.delete(snippet)
    record(
        db,
        user=user,
        action="delete_html_snippet",
        entity_type="html_snippet",
        entity_id=snippet_id,
    )
    db.commit()
    # Widgets keep the markup they were given, so deleting a snippet takes it
    # out of the library without blanking the dashboards already using it.
    return Message(detail=f"'{name}' removed from the library")


# --- dashboards ------------------------------------------------------------


@router.get("", response_model=list[DashboardOut])
def list_dashboards(
    db: DbSession, user: CurrentUser, project_id: str = ""
) -> list[Dashboard]:
    statement = restrict(
        select(Dashboard).order_by(Dashboard.updated_at.desc()),
        scope_for(db, user).filter(Dashboard.project_id),
    )
    if project_id:
        statement = statement.where(
            Dashboard.project_id.is_(None)
            if project_id == "none"
            else Dashboard.project_id == project_id
        )
    return list(db.scalars(statement).all())


@router.post("", response_model=DashboardDetail, status_code=201)
def create_dashboard(
    payload: DashboardCreate, db: DbSession, user: RequireAnalyst
) -> DashboardDetail:
    if payload.project_id and not can_edit(db, user, payload.project_id, Role.analyst):
        # Same reasoning as everywhere else: do not confirm the project exists.
        raise HTTPException(status_code=404, detail="Project not found")
    dashboard = Dashboard(
        name=payload.name,
        slug=_unique_slug(db, payload.name),
        description=payload.description,
        filters=payload.filters,
        refresh_interval_seconds=payload.refresh_interval_seconds,
        created_by=user.id,
        project_id=payload.project_id,
        theme=payload.theme,
        pages=payload.pages,
        appearance=payload.appearance,
        drilldown=payload.drilldown,
    )
    db.add(dashboard)
    record(db, user=user, action="create_dashboard", entity_type="dashboard")
    db.commit()
    db.refresh(dashboard)
    return DashboardDetail.model_validate(dashboard)


@router.get("/{dashboard_id}", response_model=DashboardDetail)
def read_dashboard(dashboard_id: str, db: DbSession, user: CurrentUser) -> DashboardDetail:
    return DashboardDetail.model_validate(_get_dashboard(dashboard_id, db, user))


@router.patch("/{dashboard_id}", response_model=DashboardDetail)
def update_dashboard(
    dashboard_id: str, payload: DashboardUpdate, db: DbSession, user: RequireAnalyst
) -> DashboardDetail:
    dashboard = _get_dashboard(dashboard_id, db, user)
    data = payload.model_dump(exclude_unset=True)
    widgets = data.pop("widgets", None)

    if data.get("is_public") and not dashboard.public_token:
        dashboard.public_token = new_public_token()
    for field, value in data.items():
        setattr(dashboard, field, value)

    if widgets is not None:
        _replace_widgets(db, dashboard, [WidgetIn.model_validate(w) for w in widgets])

    record(
        db,
        user=user,
        action="update_dashboard",
        entity_type="dashboard",
        entity_id=dashboard_id,
    )
    db.commit()
    db.refresh(dashboard)
    return DashboardDetail.model_validate(dashboard)


@router.delete("/{dashboard_id}", response_model=Message)
def delete_dashboard(dashboard_id: str, db: DbSession, user: RequireAnalyst) -> Message:
    dashboard = _get_dashboard(dashboard_id, db, user)
    name = dashboard.name
    remove_all(dashboard.id)
    db.delete(dashboard)
    record(
        db,
        user=user,
        action="delete_dashboard",
        entity_type="dashboard",
        entity_id=dashboard_id,
    )
    db.commit()
    return Message(detail=f"Dashboard '{name}' deleted")


@router.post("/{dashboard_id}/widgets", response_model=DashboardDetail, status_code=201)
def add_widget(
    dashboard_id: str, payload: WidgetIn, db: DbSession, user: RequireAnalyst
) -> DashboardDetail:
    dashboard = _get_dashboard(dashboard_id, db, user)
    widget = Widget(
        dashboard_id=dashboard.id,
        title=payload.title,
        widget_type=payload.widget_type,
        chart_id=payload.chart_id,
        indicator_id=payload.indicator_id,
        dataset_id=payload.dataset_id,
        config=payload.config,
        layout=payload.layout or _next_layout(dashboard, payload.page),
        position=payload.position or len(dashboard.widgets),
        page=payload.page,
    )
    db.add(widget)
    db.commit()
    db.refresh(dashboard)
    return DashboardDetail.model_validate(dashboard)


@router.delete("/{dashboard_id}/widgets/{widget_id}", response_model=DashboardDetail)
def delete_widget(
    dashboard_id: str, widget_id: str, db: DbSession, user: RequireAnalyst
) -> DashboardDetail:
    dashboard = _get_dashboard(dashboard_id, db, user)
    widget = db.get(Widget, widget_id)
    if widget is None or widget.dashboard_id != dashboard.id:
        raise HTTPException(status_code=404, detail="Widget not found")
    db.delete(widget)
    db.commit()
    db.refresh(dashboard)
    return DashboardDetail.model_validate(dashboard)


@router.patch("/{dashboard_id}/widgets/{widget_id}", response_model=DashboardDetail)
def update_widget(
    dashboard_id: str,
    widget_id: str,
    payload: WidgetPatch,
    db: DbSession,
    user: RequireAnalyst,
) -> DashboardDetail:
    """Change one widget - which is how a widget is moved to another page.

    Pages hold independent layouts, so a widget that arrives on a new page
    without one of its own is put below what is already there. Keeping its old
    coordinates would drop it on top of another widget, or far below the last
    of them on a page that has less on it.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)
    widget = db.get(Widget, widget_id)
    if widget is None or widget.dashboard_id != dashboard.id:
        raise HTTPException(status_code=404, detail="Widget not found")

    data = payload.model_dump(exclude_unset=True)
    moving = "page" in data and int(data["page"]) != (widget.page or 0)
    if moving and not 0 <= int(data["page"]) < max(len(dashboard.pages or []), 1):
        raise HTTPException(status_code=422, detail="That page does not exist")
    for field, value in data.items():
        setattr(widget, field, value)
    if moving and "layout" not in data:
        # Its own size is part of what the widget is - a countdown is not a
        # crosstab - so only where it sits is decided again.
        was = widget.layout or {}
        placed = _next_layout(dashboard, widget.page, exclude=widget.id)
        widget.layout = {
            **placed,
            "w": int(was.get("w", placed["w"])),
            "h": int(was.get("h", placed["h"])),
        }

    db.commit()
    db.refresh(dashboard)
    return DashboardDetail.model_validate(dashboard)


@router.put("/{dashboard_id}/background", response_model=DashboardOut)
async def upload_background(
    dashboard_id: str,
    db: DbSession,
    user: RequireAnalyst,
    file: Annotated[UploadFile, File(description="PNG, JPEG, GIF or WebP image")],
) -> Dashboard:
    dashboard = _get_dashboard(dashboard_id, db, user)
    try:
        name = save_background(dashboard.id, await file.read())
    except BackgroundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    appearance = dict(dashboard.appearance or {})
    appearance["background_image"] = name
    # The file name is stable, so a browser holding the previous image would go
    # on showing it. The stamp is what the frontend hangs a query string on.
    appearance["background_version"] = dt.datetime.now(dt.UTC).isoformat()
    dashboard.appearance = appearance
    db.commit()
    db.refresh(dashboard)
    return dashboard


@router.get("/{dashboard_id}/background")
def read_background(dashboard_id: str, db: DbSession, user: CurrentUser) -> Response:
    dashboard = _get_dashboard(dashboard_id, db, user)
    return background_response(dashboard)


@router.delete("/{dashboard_id}/background", response_model=DashboardOut)
def delete_background(dashboard_id: str, db: DbSession, user: RequireAnalyst) -> Dashboard:
    dashboard = _get_dashboard(dashboard_id, db, user)
    remove_background(dashboard.id)
    appearance = dict(dashboard.appearance or {})
    appearance.pop("background_image", None)
    appearance.pop("background_version", None)
    dashboard.appearance = appearance
    db.commit()
    db.refresh(dashboard)
    return dashboard


@router.put("/{dashboard_id}/logo", response_model=DashboardOut)
async def upload_logo(
    dashboard_id: str,
    db: DbSession,
    user: RequireAnalyst,
    file: Annotated[UploadFile, File(description="PNG, JPEG, GIF or WebP image")],
) -> Dashboard:
    """A logo for the dashboard's own header.

    A dashboard is usually the thing a survey team shows other people, and it
    is theirs rather than the platform's. This is what puts the statistics
    office at the top of it rather than us.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)
    try:
        name = save_background(dashboard.id, await file.read(), kind="logo")
    except BackgroundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    appearance = dict(dashboard.appearance or {})
    appearance["logo_image"] = name
    appearance["logo_version"] = dt.datetime.now(dt.UTC).isoformat()
    dashboard.appearance = appearance
    db.commit()
    db.refresh(dashboard)
    return dashboard


@router.get("/{dashboard_id}/logo")
def read_logo(dashboard_id: str, db: DbSession, user: CurrentUser) -> Response:
    dashboard = _get_dashboard(dashboard_id, db, user)
    return background_response(dashboard, kind="logo")


@router.delete("/{dashboard_id}/logo", response_model=DashboardOut)
def delete_logo(dashboard_id: str, db: DbSession, user: RequireAnalyst) -> Dashboard:
    dashboard = _get_dashboard(dashboard_id, db, user)
    remove_background(dashboard.id, kind="logo")
    appearance = dict(dashboard.appearance or {})
    appearance.pop("logo_image", None)
    appearance.pop("logo_version", None)
    dashboard.appearance = appearance
    db.commit()
    db.refresh(dashboard)
    return dashboard


def background_response(dashboard: Dashboard, kind: str = "background") -> Response:
    """Serve one of a dashboard's images. Shared with the public router."""
    stored = (dashboard.appearance or {}).get(
        "logo_image" if kind == "logo" else "background_image"
    )
    found = background_file(dashboard.id, stored, kind=kind)
    if found is None:
        raise HTTPException(status_code=404, detail=f"This dashboard has no {kind} image")
    path, content_type = found
    return FileResponse(
        path,
        media_type=content_type,
        # The bytes are user-uploaded, so the browser is told exactly what they
        # are and forbidden from guessing something else.
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.post("/{dashboard_id}/data", response_model=dict)
def render_dashboard(
    dashboard_id: str,
    db: DbSession,
    user: CurrentUser,
    filters: FilterGroup | None = None,
    # Query parameters rather than part of the body, so the body stays the
    # bare filter group everything already sends. The values chosen on the way
    # down a hierarchy arrive as ordinary conditions in that group; only how
    # deep the reader has gone has to be said separately, because that changes
    # what the charts group on rather than which rows they count.
    every_widget_but: str = "",
    drill_level: int = 0,
) -> dict[str, Any]:
    """Render every widget in one round trip so the page loads at once."""
    dashboard = _get_dashboard(dashboard_id, db, user)
    return _render_widgets(db, dashboard, filters, every_widget_but, drill_level)


def filter_values_response(
    dashboard: Dashboard, variable: str, db: DbSession, limit: int = 200
) -> list[dict[str, Any]]:
    """The choices in one of this dashboard's own filter dropdowns.

    Served through the dashboard rather than through the dataset because the
    dataset endpoint needs an account, and the reader of a shared link has
    none: the dropdowns on a copied link came up empty for anyone not already
    signed in to this browser, which is what "sometimes there are no options"
    was.

    Only a variable the author actually put a control on is answered, and the
    dataset is taken from that control rather than from the caller. So this
    lists what the dropdown was built to list and nothing else - the same rule
    the shared render already applies to filters arriving from outside.
    """
    control = next(
        (
            item
            for item in (dashboard.filters or [])
            if isinstance(item, dict) and item.get("variable") == variable
        ),
        None,
    )
    if control is None:
        raise HTTPException(status_code=404, detail="This dashboard has no such filter")
    dataset = db.get(Dataset, str(control.get("dataset_id") or ""))
    if dataset is None or not dataset_is_queryable(dataset):
        raise HTTPException(status_code=404, detail="The filter's dataset is unavailable")
    try:
        return distinct_values(DatasetContext.from_model(dataset), variable, limit)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{dashboard_id}/filter-values/{variable}", response_model=list[dict])
def read_dashboard_filter_values(
    dashboard_id: str,
    variable: str,
    db: DbSession,
    user: CurrentUser,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return filter_values_response(
        _get_dashboard(dashboard_id, db, user), variable, db, min(limit, 1000)
    )


def boundary_response(
    dashboard: Dashboard, layer_id: str, db: DbSession
) -> dict[str, Any]:
    """The areas one of this dashboard's map widgets draws.

    Served through the dashboard rather than from the boundary endpoints so a
    shared link can draw its own outlines: the reader of a shared board has no
    account, and the alternative was sending a national frame down with every
    refresh of the widget data. Only a layer some widget here actually names is
    returned, so the route cannot be used to read another project's geography.
    """
    named = {
        str((widget.config or {}).get("boundary_id") or "")
        for widget in dashboard.widgets
        if widget.widget_type.value == "map"
    }
    layer = db.get(BoundaryLayer, layer_id) if layer_id in named else None
    if layer is None:
        raise HTTPException(status_code=404, detail="Boundary layer not found")
    features, _ = boundary_store.load(layer.storage_path)
    return {"type": "FeatureCollection", "features": features}


@router.get("/{dashboard_id}/boundaries/{layer_id}", response_model=dict)
def read_dashboard_boundary(
    dashboard_id: str, layer_id: str, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    return boundary_response(_get_dashboard(dashboard_id, db, user), layer_id, db)


# --- share links -----------------------------------------------------------


class ShareLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    token: str
    is_active: bool
    has_password: bool = False
    expires_at: dt.datetime | None = None
    # Worked out here rather than in the browser, which has its own clock and
    # its own idea of the time zone. A link half an hour past its date has to
    # read as shut in the list that manages it, because it is shut to readers.
    expired: bool = False
    view_count: int = 0
    last_viewed_at: dt.datetime | None = None
    created_at: dt.datetime

    @classmethod
    def of(cls, link: ShareLink) -> ShareLinkOut:
        # The hash never leaves the server; whether there is one does.
        return cls(
            id=link.id,
            name=link.name,
            token=link.token or "",
            is_active=bool(link.is_active),
            has_password=bool(link.password_hash),
            expires_at=link.expires_at,
            expired=link_expired(link),
            view_count=link.view_count or 0,
            last_viewed_at=link.last_viewed_at,
            created_at=link.created_at,
        )


class ShareLinkIn(BaseModel):
    name: str = ""
    password: str = ""
    expires_at: dt.datetime | None = None


class ShareLinkPatch(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    # Like the password below, told apart by exclude_unset: absent leaves the
    # date alone and an explicit null takes it off, so a link can be given an
    # end and then have it removed again.
    expires_at: dt.datetime | None = None
    # Distinguished by exclude_unset: absent leaves the password alone, and an
    # empty string removes it. Without that there is no way to say "take the
    # password off" that does not also mean "leave it as it is".
    password: str | None = None


@router.get("/{dashboard_id}/export.html")
def export_dashboard_html(dashboard_id: str, db: DbSession, user: CurrentUser) -> Response:
    """The dashboard as one HTML file, filters and all.

    A board is often wanted somewhere this platform is not: on a ministry's own
    web host, beside a report, on a laptop taken to a meeting. A picture of it
    loses the one thing that makes it a dashboard, which is that the reader can
    narrow it and watch the numbers move, so the file carries the data behind
    every widget at the grain its filters need rather than a rendering of it.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)
    payload = static_export.build_payload(
        db, dashboard, render=lambda widget: _render_widget(db, widget, None)
    )
    record(
        db,
        user=user,
        action="dashboard.export_html",
        entity_type="dashboard",
        entity_id=dashboard_id,
        detail={"widgets": len(payload["widgets"])},
    )
    db.commit()
    name = slugify(dashboard.name) or "dashboard"
    return Response(
        content=static_export.render_html(payload),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.html"'},
    )


@router.get("/{dashboard_id}/share-links", response_model=list[ShareLinkOut])
def list_share_links(
    dashboard_id: str, db: DbSession, user: RequireAnalyst
) -> list[ShareLinkOut]:
    dashboard = _get_dashboard(dashboard_id, db, user)
    links = db.scalars(
        select(ShareLink)
        .where(ShareLink.dashboard_id == dashboard.id)
        .order_by(ShareLink.created_at)
    ).all()
    return [ShareLinkOut.of(link) for link in links]


@router.post("/{dashboard_id}/share-links", response_model=ShareLinkOut, status_code=201)
def create_share_link(
    dashboard_id: str, payload: ShareLinkIn, db: DbSession, user: RequireAnalyst
) -> ShareLinkOut:
    """Publish another address for this dashboard.

    A board goes to several audiences at once and they do not end together, so
    each gets its own link to close when it is done with.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)
    link = ShareLink(
        dashboard_id=dashboard.id,
        name=payload.name.strip() or "Shared link",
        token=new_public_token(),
        is_active=True,
        expires_at=as_utc(payload.expires_at),
        password_hash=hash_password(payload.password) if payload.password else "",
        created_by=user.id,
    )
    db.add(link)
    # The dashboard's own flag is what every public route checks first, so a
    # board with links on it has to be published.
    dashboard.is_public = True
    db.commit()
    db.refresh(link)
    record(
        db,
        user=user,
        action="share_link.create",
        entity_type="dashboard",
        entity_id=dashboard_id,
        detail={
            "name": link.name,
            "password": bool(link.password_hash),
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        },
    )
    return ShareLinkOut.of(link)


@router.patch("/{dashboard_id}/share-links/{link_id}", response_model=ShareLinkOut)
def update_share_link(
    dashboard_id: str,
    link_id: str,
    payload: ShareLinkPatch,
    db: DbSession,
    user: RequireAnalyst,
) -> ShareLinkOut:
    dashboard = _get_dashboard(dashboard_id, db, user)
    link = db.get(ShareLink, link_id)
    if link is None or link.dashboard_id != dashboard.id:
        raise HTTPException(status_code=404, detail="Share link not found")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        link.name = (changes["name"] or "").strip() or "Shared link"
    if "is_active" in changes:
        link.is_active = bool(changes["is_active"])
    if "expires_at" in changes:
        link.expires_at = as_utc(changes["expires_at"])
    if "password" in changes:
        link.password_hash = (
            hash_password(changes["password"]) if changes["password"] else ""
        )
    db.commit()
    db.refresh(link)
    return ShareLinkOut.of(link)


@router.delete("/{dashboard_id}/share-links/{link_id}", response_model=Message)
def delete_share_link(
    dashboard_id: str, link_id: str, db: DbSession, user: RequireAnalyst
) -> Message:
    """Destroy a link. Closing it is usually what is wanted instead.

    A deleted address can never be reopened; a closed one can, which matters
    when the link is already pasted into somebody's email.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)
    link = db.get(ShareLink, link_id)
    if link is None or link.dashboard_id != dashboard.id:
        raise HTTPException(status_code=404, detail="Share link not found")
    db.delete(link)
    db.commit()
    record(
        db,
        user=user,
        action="share_link.delete",
        entity_type="dashboard",
        entity_id=dashboard_id,
        detail={"name": link.name},
    )
    return Message(detail="Share link deleted")


@router.post("/{dashboard_id}/share", response_model=DashboardOut)
def share_dashboard(
    dashboard_id: str, db: DbSession, user: RequireAnalyst, enable: bool = True
) -> Dashboard:
    """Enable or disable a read-only public link."""
    dashboard = _get_dashboard(dashboard_id, db, user)
    dashboard.is_public = enable
    if enable and not dashboard.public_token:
        dashboard.public_token = new_public_token()
    if not enable:
        dashboard.public_token = None
        # A name pointing at a dashboard nobody may read is a dead address, and
        # a confusing one: the DNS record still resolves. Sharing off takes the
        # name with it.
        dashboard.public_hostname = None
    record(
        db,
        user=user,
        action="share_dashboard" if enable else "unshare_dashboard",
        entity_type="dashboard",
        entity_id=dashboard_id,
    )
    db.commit()
    db.refresh(dashboard)
    return dashboard


# --- saved views -----------------------------------------------------------
#
# A board is read the same few ways over and over. A view is that reading under
# a name: the page, the filter selections, and how far down the hierarchy the
# reader had drilled. Nothing about the board itself is copied, so a view goes
# on working when a widget is added or a chart is restyled.


def _views_for(db: DbSession, dashboard: Dashboard, user: User | None) -> list[DashboardView]:
    """The views this reader may see: the shared ones and their own."""
    return [
        view
        for view in db.scalars(
            select(DashboardView)
            .where(DashboardView.dashboard_id == dashboard.id)
            .order_by(DashboardView.is_default.desc(), DashboardView.name)
        ).all()
        if view.is_shared or (user is not None and view.created_by == user.id)
    ]


def _clear_other_defaults(db: DbSession, dashboard_id: str, keep: str) -> None:
    for other in db.scalars(
        select(DashboardView).where(
            DashboardView.dashboard_id == dashboard_id, DashboardView.id != keep
        )
    ).all():
        other.is_default = False


@router.get("/{dashboard_id}/views", response_model=list[DashboardViewOut])
def list_views(
    dashboard_id: str, db: DbSession, user: CurrentUser
) -> list[DashboardView]:
    return _views_for(db, _get_dashboard(dashboard_id, db, user), user)


@router.post("/{dashboard_id}/views", response_model=DashboardViewOut, status_code=201)
def create_view(
    dashboard_id: str, payload: DashboardViewIn, db: DbSession, user: CurrentUser
) -> DashboardView:
    """Save the current selection under a name.

    Any reader may keep their own, which is the point of a shortcut, but only
    an analyst may publish one to everybody or make it the board's opening
    view - those change what other people see.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)
    may_publish = user.role in (Role.analyst, Role.admin)
    view = DashboardView(
        dashboard_id=dashboard.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        state=payload.state,
        is_default=payload.is_default and may_publish,
        is_shared=payload.is_shared and may_publish,
        created_by=user.id,
    )
    db.add(view)
    db.flush()
    if view.is_default:
        _clear_other_defaults(db, dashboard.id, view.id)
    db.commit()
    db.refresh(view)
    return view


@router.patch("/{dashboard_id}/views/{view_id}", response_model=DashboardViewOut)
def update_view(
    dashboard_id: str,
    view_id: str,
    payload: DashboardViewPatch,
    db: DbSession,
    user: CurrentUser,
) -> DashboardView:
    dashboard = _get_dashboard(dashboard_id, db, user)
    view = _get_view(db, dashboard, view_id, user)
    changes = payload.model_dump(exclude_unset=True)
    may_publish = user.role in (Role.analyst, Role.admin)
    if "name" in changes:
        view.name = (changes["name"] or "").strip() or view.name
    if "description" in changes:
        view.description = (changes["description"] or "").strip()
    if "state" in changes:
        view.state = changes["state"] or {}
    if "is_shared" in changes and may_publish:
        view.is_shared = bool(changes["is_shared"])
    if "is_default" in changes and may_publish:
        view.is_default = bool(changes["is_default"])
        if view.is_default:
            _clear_other_defaults(db, dashboard.id, view.id)
    db.commit()
    db.refresh(view)
    return view


@router.delete("/{dashboard_id}/views/{view_id}", response_model=Message)
def delete_view(
    dashboard_id: str, view_id: str, db: DbSession, user: CurrentUser
) -> Message:
    dashboard = _get_dashboard(dashboard_id, db, user)
    view = _get_view(db, dashboard, view_id, user)
    name = view.name
    db.delete(view)
    db.commit()
    return Message(detail=f"View '{name}' deleted")


def _get_view(
    db: DbSession, dashboard: Dashboard, view_id: str, user: User
) -> DashboardView:
    view = db.get(DashboardView, view_id)
    if view is None or view.dashboard_id != dashboard.id:
        raise HTTPException(status_code=404, detail="View not found")
    # Your own to change, or anybody's if you may edit the board. A reader who
    # can only see it cannot rename or delete what somebody else published.
    if view.created_by != user.id and user.role not in (Role.analyst, Role.admin):
        raise HTTPException(status_code=404, detail="View not found")
    return view


@router.post("/{dashboard_id}/pages/move", response_model=DashboardDetail)
def move_page(
    dashboard_id: str, payload: PageMove, db: DbSession, user: RequireAnalyst
) -> Dashboard:
    """Move a page to another position, taking its widgets with it.

    A widget records the page it is on as an index into the page list, so
    reordering the list without renumbering the widgets would leave every
    widget on the page that happens to sit where its old number now points.
    Both halves have to move together, which is why this is one call rather
    than a page list the browser rewrites.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)
    pages = list(dashboard.pages or [])
    if len(pages) < 2:
        raise HTTPException(status_code=409, detail="There is only one page to move")
    if not (0 <= payload.from_index < len(pages)) or not (0 <= payload.to_index < len(pages)):
        raise HTTPException(status_code=422, detail="That position does not exist")
    if payload.from_index == payload.to_index:
        return dashboard

    moved = pages.pop(payload.from_index)
    pages.insert(payload.to_index, moved)
    dashboard.pages = pages
    _renumber(dashboard, _moved_positions(payload.from_index, payload.to_index))
    db.commit()
    db.refresh(dashboard)
    return dashboard


@router.delete("/{dashboard_id}/pages/{index}", response_model=DashboardDetail)
def delete_page(
    dashboard_id: str, index: int, db: DbSession, user: RequireAnalyst
) -> Dashboard:
    """Remove a page, and renumber the ones after it along with their widgets."""
    dashboard = _get_dashboard(dashboard_id, db, user)
    pages = list(dashboard.pages or [])
    if len(pages) < 2:
        raise HTTPException(
            status_code=409, detail="A dashboard keeps at least one page"
        )
    if not 0 <= index < len(pages):
        raise HTTPException(status_code=422, detail="That page does not exist")
    if any((widget.page or 0) == index for widget in dashboard.widgets):
        raise HTTPException(
            status_code=409,
            detail="Move or remove this page's widgets before deleting it",
        )

    pages.pop(index)
    dashboard.pages = pages
    # Everything after the hole moves down one. Without this the widgets on
    # those pages would keep pointing at the position their page used to hold.
    for widget in dashboard.widgets:
        if (widget.page or 0) > index:
            widget.page = (widget.page or 0) - 1
    db.commit()
    db.refresh(dashboard)
    return dashboard


def _moved_positions(source: int, target: int) -> dict[int, int]:
    """Where each old page index ends up after one page moves."""
    order = list(range(max(source, target) + 1))
    order.insert(target, order.pop(source))
    return {old: new for new, old in enumerate(order)}


def _renumber(dashboard: Dashboard, mapping: dict[int, int]) -> None:
    for widget in dashboard.widgets:
        current = widget.page or 0
        if current in mapping:
            widget.page = mapping[current]


@router.put("/{dashboard_id}/hostname", response_model=DashboardOut)
def set_hostname(
    dashboard_id: str, payload: HostnameIn, db: DbSession, user: RequireAnalyst
) -> Dashboard:
    """Give a shared dashboard its own address, or take it away with "".

    The name is a subdomain of the one configured domain, which is what keeps
    the deployment to a single wildcard DNS record and certificate. Both a bare
    label and the whole hostname are accepted, because both are what people
    paste.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)

    if not (payload.hostname or "").strip():
        dashboard.public_hostname = None
        db.commit()
        db.refresh(dashboard)
        return dashboard

    if not dashboard.is_public:
        raise HTTPException(
            status_code=409,
            detail=(
                "Share the dashboard first. A name is a second way in to a "
                "dashboard that is already public, not a way of publishing it."
            ),
        )
    try:
        hostname = normalise_hostname(payload.hostname)
    except HostnameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    taken = db.scalar(
        select(Dashboard).where(
            Dashboard.public_hostname == hostname, Dashboard.id != dashboard.id
        )
    )
    if taken is not None:
        # Checked here rather than left to the unique index: the column reaches
        # an existing database through ALTER TABLE, which carries no index.
        raise HTTPException(
            status_code=409, detail=f"'{hostname}' already belongs to another dashboard"
        )

    dashboard.public_hostname = hostname
    record(
        db,
        user=user,
        action="name_dashboard",
        entity_type="dashboard",
        entity_id=dashboard_id,
        detail={"hostname": hostname},
    )
    db.commit()
    db.refresh(dashboard)
    return dashboard


def _get_dashboard(dashboard_id: str, db: DbSession, user: User) -> Dashboard:
    dashboard = db.get(Dashboard, dashboard_id)
    # Out of scope reads as missing, not forbidden: see services.projects.
    if dashboard is None or not can_view(db, user, dashboard.project_id):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return dashboard


def _unique_slug(db: DbSession, name: str) -> str:
    base = slugify(name)[:180] or "dashboard"
    candidate, suffix = base, 2
    while db.scalar(select(Dashboard).where(Dashboard.slug == candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _next_layout(
    dashboard: Dashboard, page: int = 0, exclude: str | None = None
) -> dict[str, int]:
    """Space below what is already on that page.

    Pages have independent layouts, so a widget added to the second page must
    not be placed below the first page's content - it would open on an empty
    screen with the widget somewhere far down it.
    """
    bottom = 0
    for widget in dashboard.widgets:
        if (widget.page or 0) != page or widget.id == exclude:
            continue
        layout = widget.layout or {}
        bottom = max(bottom, int(layout.get("y", 0)) + int(layout.get("h", 4)))
    return {"x": 0, "y": bottom, "w": 6, "h": 4}


def _replace_widgets(db: DbSession, dashboard: Dashboard, widgets: list[WidgetIn]) -> None:
    """Apply the widget list from the dashboard editor, preserving existing ids."""
    existing = {w.id: w for w in dashboard.widgets}
    seen: set[str] = set()
    for position, incoming in enumerate(widgets):
        if incoming.id and incoming.id in existing:
            widget = existing[incoming.id]
            seen.add(widget.id)
        else:
            widget = Widget(dashboard_id=dashboard.id)
            db.add(widget)
        widget.title = incoming.title
        widget.widget_type = incoming.widget_type
        widget.chart_id = incoming.chart_id
        widget.indicator_id = incoming.indicator_id
        widget.dataset_id = incoming.dataset_id
        widget.config = incoming.config
        widget.layout = incoming.layout
        widget.position = position
        widget.page = incoming.page
    for widget_id, widget in existing.items():
        if widget_id not in seen:
            db.delete(widget)


def _render_widgets(
    db: DbSession,
    dashboard: Dashboard,
    filters: FilterGroup | None,
    except_widget: str = "",
    drill_level: int = 0,
) -> dict[str, Any]:
    """Every widget's data in one round trip, so a page loads at once.

    except_widget is the widget a click-to-filter selection was made on. It is
    rendered unfiltered, because it is the thing being clicked: narrowing it to
    the one bar just chosen would take away the means of choosing another.
    """
    drill = Drill.of(dashboard, drill_level)
    payload: dict[str, Any] = {
        "dashboard_id": dashboard.id,
        "name": dashboard.name,
        "widgets": {},
    }
    for widget in dashboard.widgets:
        try:
            payload["widgets"][widget.id] = _render_widget(
                db, widget, None if widget.id == except_widget else filters, drill
            )
        except (QueryError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            payload["widgets"][widget.id] = {"error": str(detail)}
    return payload


def _map_boundary(
    db: DbSession, config: dict[str, Any]
) -> tuple[BoundaryLayer, Areas] | None:
    """The boundary layer a map widget draws, if it names one.

    Not checked against the reader, for the same reason a widget's chart is
    not: the dashboard is the unit of access here, and what its author put on
    it is rendered with it. A shared dashboard has no reader to check anyway.
    Which layers may be chosen is decided where they are offered, in the list
    endpoint, which is scoped.
    """
    layer_id = str(config.get("boundary_id") or "")
    if not layer_id:
        return None
    layer = db.get(BoundaryLayer, layer_id)
    if layer is None:
        return None
    _, areas = boundary_store.load(layer.storage_path)
    return layer, areas


def _render_quality(
    db: DbSession, widget: Widget, filters: FilterGroup | None = None
) -> dict[str, Any]:
    """The state of a dataset's data quality checks.

    Unfiltered, this reports what the last run found rather than running the
    checks now: a dashboard opening should not set eight full-table scans
    going, and the results are already stored by the run that produced them.
    The age of the oldest one is reported so a stale panel cannot pass for a
    fresh one.

    Filtered, there is nothing stored to report - no run ever counted only the
    rows the reader is looking at - so the checks are run against them. A panel
    that went on saying "3% missing" while the rest of the page was narrowed to
    one province was answering a question nobody had asked, and there is no way
    to answer the right one from numbers computed over everything.
    """
    dataset_id = widget.dataset_id or (widget.config or {}).get("dataset_id")
    if not dataset_id:
        return {"error": "This panel is not pointed at a dataset"}
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        return {"error": "The dataset no longer exists"}

    rules = list(
        db.scalars(
            select(QualityRule).where(
                QualityRule.dataset_id == dataset_id, QualityRule.is_active.is_(True)
            )
        )
    )

    narrowed: FilterGroup | None = None
    ignored: list[str] = []
    ctx: DatasetContext | None = None
    if filters is not None and not filters.is_empty() and dataset_is_queryable(dataset):
        try:
            ctx = DatasetContext.from_model(dataset)
        except QueryError:
            ctx = None
        if ctx is not None:
            narrowed = _applicable(filters, ctx)
            ignored = _ignored(filters, ctx)

    checks: list[dict[str, Any]] = []
    for rule in rules:
        if narrowed is not None and ctx is not None:
            check = _recheck(ctx, rule, narrowed)
        else:
            check = _stored_check(db, rule)
        checks.append(check)

    checks.sort(key=lambda c: (c["passed"] is not False, -c["failure_rate"]))
    runs = [c["run_at"] for c in checks if c["run_at"]]
    return {
        "type": "quality",
        "name": dataset.name,
        "dataset_id": dataset_id,
        "checks": checks,
        "failing": sum(1 for c in checks if c["passed"] is False),
        "passing": sum(1 for c in checks if c["passed"] is True),
        "never_run": sum(1 for c in checks if c["passed"] is None),
        "oldest_run_at": min(runs) if runs else None,
        # Set when these numbers were counted for this reader's filter rather
        # than read off the last run, so the panel can say so instead of
        # showing a timestamp that belongs to a different question.
        "filtered": narrowed is not None,
        "filters_ignored": ignored,
        # The runs behind the checks, for a panel drawn as a chart of how the
        # rates have moved. Only when the widget asks: a panel showing its
        # findings has no use for them and reading a month of runs for every
        # quality panel on a board would be work done to be thrown away.
        "history": (
            _quality_history(db, rules)
            if (widget.config or {}).get("quality_view") == "trend"
            else None
        ),
    }


def _quality_history(
    db: DbSession, rules: list[QualityRule], days: int = 30
) -> dict[str, Any] | None:
    """Each rule's recent runs, one point per rule per day.

    Checks run every few hours, so a month of them is a hundred points per rule
    and four of them land on top of each other on any axis a widget has room
    for. The last run of each day is the one kept: it is the day's answer, and
    the question a trend is asked is "is this getting better", which is a
    question about days rather than about mornings and afternoons.

    Gaps are kept as gaps. A rule added last week has nothing to say about the
    week before, and a line drawn straight across that would be inventing it.
    """
    if not rules:
        return None
    since = utcnow() - dt.timedelta(days=days)
    rows = db.execute(
        select(
            QualityResult.rule_id,
            QualityResult.run_at,
            QualityResult.failure_rate,
            QualityResult.failed_rows,
            QualityResult.total_rows,
        )
        .where(
            QualityResult.rule_id.in_([rule.id for rule in rules]),
            QualityResult.run_at >= since,
        )
        # Ascending, so the last write for a day is the day's last run.
        .order_by(QualityResult.run_at)
    ).all()
    if not rows:
        return None

    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for rule_id, run_at, rate, failed, total in rows:
        day = as_utc(run_at).date().isoformat() if run_at else ""
        if not day:
            continue
        latest[(rule_id, day)] = {
            "rate": round(float(rate or 0.0) * 100, 2),
            "failed_rows": int(failed or 0),
            "total_rows": int(total or 0),
        }

    day_list = sorted({day for _, day in latest})
    return {
        "days": day_list,
        "series": [
            {
                "id": rule.id,
                "name": rule.name,
                "values": [
                    (latest.get((rule.id, day)) or {}).get("rate") for day in day_list
                ],
            }
            for rule in rules
            if any((rule.id, day) in latest for day in day_list)
        ],
    }


def _stored_check(db: DbSession, rule: QualityRule) -> dict[str, Any]:
    """What the last run of this rule found."""
    latest = db.scalar(
        select(QualityResult)
        .where(QualityResult.rule_id == rule.id)
        .order_by(QualityResult.run_at.desc())
        .limit(1)
    )
    return {
        "id": rule.id,
        "name": rule.name,
        "severity": rule.severity.value,
        "passed": latest.passed if latest else None,
        "failed_rows": latest.failed_rows if latest else 0,
        "total_rows": latest.total_rows if latest else 0,
        "failure_rate": latest.failure_rate if latest else 0.0,
        "message": latest.message if latest else "Not run yet",
        "run_at": latest.run_at.isoformat() if latest else None,
    }


def _recheck(ctx: DatasetContext, rule: QualityRule, filters: FilterGroup) -> dict[str, Any]:
    """Run one rule over the rows the page's filter leaves, without storing it.

    Nothing is written: this is one reader's view of the data, and a stored
    result is the dataset's. The rule's own filters are kept and the page's are
    added to them, so a check restricted to completed interviews stays
    restricted to completed interviews in Shefa.
    """
    own = quality.rule_filters(rule)
    combined = (
        FilterGroup(op="and", conditions=[], groups=[own, filters])
        if own is not None and not own.is_empty()
        else filters
    )
    base = {"id": rule.id, "name": rule.name, "severity": rule.severity.value}
    try:
        with quality.scoped(ctx, combined):
            outcome = quality.run_check(ctx, rule)
    except (QueryError, ExpressionError) as exc:
        return {**base, "passed": None, "failed_rows": 0, "total_rows": 0,
                "failure_rate": 0.0, "message": str(exc), "run_at": None}
    return {
        **base,
        # The threshold is what turns a count into a verdict, and it is the
        # rule's, not the check's - so this asks the same function the stored
        # run asks rather than reimplementing the comparison here.
        "passed": quality.verdict(outcome, rule),
        "failed_rows": outcome.failed_rows,
        "total_rows": outcome.total_rows,
        "failure_rate": outcome.failure_rate,
        "message": outcome.message,
        # No timestamp: it was counted for this request, and a time here would
        # read as "last run at", which it is not.
        "run_at": None,
    }


def _variance(target: float | None, value: float | None) -> dict[str, Any]:
    """The gap between a value and its target, as a number and as a share."""
    if target is None or value is None:
        return {"variance": None, "variance_percent": None}
    gap = float(value) - float(target)
    return {
        "variance": gap,
        # Against a target of zero there is no meaningful percentage, only the
        # gap itself, so the share is left out rather than divided by nothing.
        "variance_percent": (gap / abs(float(target)) * 100) if target else None,
    }


# How much history a sparkline draws. Enough to show the shape of a field
# period without turning a tile-sized line into a smear.
TREND_POINTS = 30


def _indicator_trend(db: DbSession, indicator: Indicator) -> list[dict[str, Any]]:
    """The recent stored values of an indicator, oldest first."""
    snapshots = db.scalars(
        select(IndicatorSnapshot)
        .where(
            IndicatorSnapshot.indicator_id == indicator.id,
            IndicatorSnapshot.value.is_not(None),
        )
        .order_by(IndicatorSnapshot.computed_at.desc())
        .limit(TREND_POINTS)
    ).all()
    return [
        {"at": snapshot.computed_at.isoformat(), "value": snapshot.value}
        for snapshot in reversed(snapshots)
    ]


def _render_widget(
    db: DbSession,
    widget: Widget,
    filters: FilterGroup | None,
    drill: Drill | None = None,
) -> dict[str, Any]:
    if widget.widget_type.value == "text":
        return {"type": "text", "content": (widget.config or {}).get("content", "")}

    if widget.widget_type.value == "indicator" and widget.indicator_id:
        indicator = db.get(Indicator, widget.indicator_id)
        if indicator is None:
            return {"error": "Indicator no longer exists"}

        value = indicator.last_value
        computed_at = indicator.last_computed_at
        breakdown: dict[str, float] = {}
        wants_breakdown = bool((widget.config or {}).get("show_breakdown"))

        # A filter on the page is a question about the rows it leaves, and the
        # stored value answers a different one - it was computed over the whole
        # dataset by the last scheduled run. So a filter this indicator's
        # dataset can honour sends the tile back to the data; without one it
        # goes on reporting the stored value, which is what keeps opening a
        # dashboard from setting a query going for every tile on it.
        narrowed: FilterGroup | None = None
        ignored: list[str] = []
        dataset = db.get(Dataset, indicator.dataset_id)
        if (
            filters is not None
            and not filters.is_empty()
            and dataset is not None
            and dataset_is_queryable(dataset)
        ):
            try:
                ctx = DatasetContext.from_model(dataset)
            except QueryError:
                ctx = None
            if ctx is not None:
                narrowed = _applicable(filters, ctx)
                ignored = _ignored(filters, ctx)

        if narrowed is not None or (wants_breakdown and indicator.breakdown_variable):
            # Evaluated rather than read off the stored value, because a
            # breakdown that was computed at a different moment from the
            # headline above it would not add up to it - and the two sitting in
            # one tile invite exactly that comparison.
            outcome = evaluate_indicator(db, indicator, narrowed)
            if outcome.get("error"):
                return {"error": outcome["error"]}
            value = outcome["value"]
            # A filtered tile is recomputed whether or not it shows a
            # breakdown, and the one it did not ask for is not passed on.
            breakdown = outcome["breakdown"] if wants_breakdown else {}
            computed_at = utcnow()

        return {
            "type": "indicator",
            "name": indicator.name,
            "value": value,
            # How far off the target this is, and which way. A tile that shows
            # only the number and the target leaves the subtraction to the
            # reader, and the answer to "are we behind" is the whole reason the
            # tile is on the wall.
            **_variance(indicator.target_value, value),
            # The last few scheduled runs, for the sparkline under the number.
            # Only when the widget asks, and never beside a filtered value: the
            # snapshots were computed over the whole dataset, so a line drawn
            # from them under a number that is not would be two different
            # questions in one tile.
            "trend": (
                []
                if narrowed is not None or not (widget.config or {}).get("show_trend")
                else _indicator_trend(db, indicator)
            ),
            "unit": indicator.unit,
            "value_format": indicator.value_format,
            "target_value": indicator.target_value,
            "progress_percent": progress_percent(indicator, value),
            "status": indicator_status(indicator, value),
            "breakdown": breakdown,
            # Each category against its own quota, so a tile broken down by
            # region can say which regions are behind rather than only what
            # the totals are.
            "breakdown_progress": breakdown_progress(indicator, breakdown),
            "breakdown_variable": indicator.breakdown_variable if wants_breakdown else "",
            # Which way the indicator is meant to move. A quota chart reads
            # differently for each: with "higher is better" the bar is progress
            # towards the target and the shortfall is what is left to do; with
            # "lower is better" the target is a ceiling and the headroom under
            # it is not something anyone is trying to fill.
            "direction": indicator.direction.value,
            "computed_at": computed_at.isoformat() if computed_at else None,
            # Set when this value was computed for the filter on this page
            # rather than read off the last scheduled run, so the tile can say
            # so instead of presenting a whole-dataset number as the answer to
            # a narrowed question.
            "filtered": narrowed is not None,
            "filters_ignored": ignored,
        }

    if widget.widget_type.value == "freshness":
        config = widget.config or {}
        chosen = list(config.get("dataset_ids") or [])
        if widget.dataset_id and not chosen:
            chosen = [widget.dataset_id]
        now = utcnow()
        lines = []
        for dataset_id in chosen[:20]:
            dataset = db.get(Dataset, dataset_id)
            if dataset is None:
                continue
            lines.append(
                freshness_report(
                    dataset,
                    now,
                    date_column=str((config.get("date_variables") or {}).get(dataset_id, "")),
                    warn_hours=float(config.get("warn_hours") or DEFAULT_WARN_HOURS),
                    critical_hours=float(
                        config.get("critical_hours") or DEFAULT_CRITICAL_HOURS
                    ),
                )
            )
        if not lines:
            return {"error": "This widget has no datasets to watch"}
        return {"type": "freshness", "datasets": lines, "as_of": now.isoformat()}

    if widget.widget_type.value == "html":
        # Sent as written and rendered by the browser in a sandboxed frame, so
        # what it contains is between its author and that frame - it cannot
        # reach the page around it. See the widget component.
        return {"type": "html", "html": (widget.config or {}).get("html", "")}

    if widget.widget_type.value == "map":
        config = widget.config or {}
        dataset = db.get(Dataset, widget.dataset_id or config.get("dataset_id") or "")
        if dataset is None or not dataset_is_queryable(dataset):
            return {"error": "The map's dataset is unavailable"}
        ctx = DatasetContext.from_model(dataset)
        ignored = _ignored(filters, ctx)
        # Checking a recorded area against where the point actually is needs
        # three things together: a layer to check against, which of its
        # attributes carries the code, and which variable holds what the
        # interviewer recorded. Any one missing and the map is just a map.
        boundary = _map_boundary(db, config)
        area_variable = str(config.get("area_variable") or "") if boundary else ""
        try:
            found = geo_points(
                ctx,
                latitude=config.get("latitude", ""),
                longitude=config.get("longitude", ""),
                detail=config.get("detail") or [],
                measure_agg=config.get("measure_agg", "count"),
                measure_variable=config.get("measure_variable", ""),
                filters=_applicable(filters, ctx),
                area_variable=area_variable,
            )
        except QueryError as exc:
            return {"error": str(exc)}
        payload: dict[str, Any] = {"type": "map", "filters_ignored": ignored, **found}
        if boundary and area_variable:
            layer, areas = boundary
            payload["area_check"] = {
                "boundary_id": layer.id,
                "boundary_name": layer.name,
                "variable": area_variable,
                "counts": check_areas(
                    payload["points"], areas, str(config.get("boundary_key") or "")
                ),
            }
        if boundary:
            payload["boundary"] = {
                "id": boundary[0].id,
                "name": boundary[0].name,
                "label": str(config.get("boundary_label") or ""),
                "bbox": boundary[0].bbox or [],
            }
        return payload

    if widget.widget_type.value == "countdown":
        config = widget.config or {}
        return {
            "type": "countdown",
            "target": config.get("target"),
            "label": config.get("label", ""),
            "expired_text": config.get("expired_text", ""),
        }

    if widget.widget_type.value == "quality":
        return _render_quality(db, widget, filters)

    if widget.chart_id:
        chart = db.get(Chart, widget.chart_id)
        if chart is None:
            return {"error": "Chart no longer exists"}
        dataset = db.get(Dataset, chart.dataset_id)
        if dataset is None or not dataset_is_queryable(dataset):
            return {"error": "The chart's dataset is unavailable"}
        ctx = DatasetContext.from_model(dataset)
        ignored = _ignored(filters, ctx)
        filters = _applicable(filters, ctx)
        if _is_crosstab(chart.spec or {}):
            crosstab = execute_crosstab(ctx, _crosstab_from_chart(chart, filters))
            return {
                "type": "crosstab",
                "chart_type": "crosstab",
                "name": chart.name,
                "filters_ignored": ignored,
                "result": crosstab.model_dump(mode="json"),
            }
        if _is_multiselect(chart.spec or {}):
            return {
                "type": "chart",
                "chart_type": chart.chart_type.value,
                "name": chart.name,
                "filters_ignored": ignored,
                "display": (chart.spec or {}).get("options") or {},
                # Nothing to click through to: the categories are columns of
                # the file, not values of one variable, so there is no filter a
                # click could stand for.
                "grouped_on": [],
                "result": _multiselect_result(ctx, chart.spec or {}, filters).model_dump(
                    mode="json"
                ),
            }
        spec = _drilled(_spec_from_chart(chart, filters), ctx, drill)
        result = execute_query(ctx, spec)
        return {
            "type": "chart",
            "chart_type": chart.chart_type.value,
            "name": chart.name,
            "filters_ignored": ignored,
            # How it is drawn - order, top-N, a target line - saved with the
            # chart, so a dashboard shows what its author built rather than a
            # default rendering of the same numbers.
            "display": (chart.spec or {}).get("options") or {},
            # What the chart groups on, so clicking a mark can say which
            # variable the category belongs to and filter the page by it. Read
            # through the same accessor the query goes through: a saved chart
            # nests its query, an older one does not.
            # Drilled if the board is deeper than this chart was built for, so
            # a click on it filters by the level it is actually showing.
            "grouped_on": [
                dimension.variable for dimension in spec.dimensions if dimension.variable
            ],
            "result": result.model_dump(mode="json"),
        }

    # Inline widget definition (no saved chart)
    config = widget.config or {}
    dataset_id = widget.dataset_id or config.get("dataset_id")
    if not dataset_id:
        return {"error": "This widget has no data source configured"}
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or not dataset_is_queryable(dataset):
        return {"error": "The widget's dataset is unavailable"}
    ctx = DatasetContext.from_model(dataset)
    ignored = _ignored(filters, ctx)
    filters = _applicable(filters, ctx)
    spec = QuerySpec.model_validate(config.get("query", {}))
    if filters and not filters.is_empty():
        spec = spec.model_copy(
            update={
                "filters": FilterGroup(op="and", groups=[spec.filters, filters], conditions=[])
            }
        )
    spec = _drilled(spec, ctx, drill)
    result = execute_query(ctx, spec)
    return {
        "type": widget.widget_type.value,
        "chart_type": config.get("chart_type", "bar"),
        "filters_ignored": ignored,
        "grouped_on": [
            dimension.variable for dimension in spec.dimensions if dimension.variable
        ],
        "result": result.model_dump(mode="json"),
    }
