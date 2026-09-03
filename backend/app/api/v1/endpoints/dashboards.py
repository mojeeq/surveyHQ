"""Charts, dashboards, widgets and public sharing."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from slugify import slugify
from sqlalchemy import select

from app.api.deps import (
    CurrentUser,
    DbSession,
    RequireAnalyst,
    get_ready_dataset,
)
from app.core.security import new_public_token
from app.db.base import utcnow
from app.models import (
    Chart,
    Dashboard,
    Dataset,
    Indicator,
    QualityResult,
    QualityRule,
    Role,
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
from app.services.audit import record
from app.services.dashboard_assets import (
    BackgroundError,
    background_file,
    remove_background,
    save_background,
)
from app.services.datasets import dataset_is_queryable
from app.services.monitoring import (
    evaluate_indicator,
    indicator_status,
    progress_percent,
)
from app.services.projects import can_edit, can_view, dataset_clause, restrict, scope_for
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    execute_crosstab,
    execute_query,
)

router = APIRouter()


# --- charts ----------------------------------------------------------------


@router.get("/charts", response_model=list[ChartOut])
def list_charts(db: DbSession, user: CurrentUser, dataset_id: str = "") -> list[Chart]:
    statement = restrict(
        select(Chart).order_by(Chart.created_at.desc()),
        dataset_clause(db, user, Chart.dataset_id),
    )
    if dataset_id:
        statement = statement.where(Chart.dataset_id == dataset_id)
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


def _is_crosstab(spec: dict[str, Any]) -> bool:
    return bool(spec.get("crosstab"))


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
    remove_background(dashboard.id)
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


def background_response(dashboard: Dashboard) -> Response:
    """Serve a dashboard's background image. Shared with the public router."""
    found = background_file(dashboard.id, (dashboard.appearance or {}).get("background_image"))
    if found is None:
        raise HTTPException(status_code=404, detail="This dashboard has no background image")
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
    dashboard_id: str, db: DbSession, user: CurrentUser, filters: FilterGroup | None = None
) -> dict[str, Any]:
    """Render every widget in one round trip so the page loads at once."""
    dashboard = _get_dashboard(dashboard_id, db, user)
    return _render_widgets(db, dashboard, filters)


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
    db: DbSession, dashboard: Dashboard, filters: FilterGroup | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "dashboard_id": dashboard.id,
        "name": dashboard.name,
        "widgets": {},
    }
    for widget in dashboard.widgets:
        try:
            payload["widgets"][widget.id] = _render_widget(db, widget, filters)
        except (QueryError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            payload["widgets"][widget.id] = {"error": str(detail)}
    return payload


def _render_quality(db: DbSession, widget: Widget) -> dict[str, Any]:
    """The state of a dataset's data quality checks.

    Reports what the last run found rather than running the checks now: a
    dashboard opening should not set eight full-table scans going, and the
    results are already stored by the run that produced them. The age of the
    oldest one is reported so a stale panel cannot pass for a fresh one.
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
    checks: list[dict[str, Any]] = []
    for rule in rules:
        latest = db.scalar(
            select(QualityResult)
            .where(QualityResult.rule_id == rule.id)
            .order_by(QualityResult.run_at.desc())
            .limit(1)
        )
        checks.append(
            {
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
        )

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
    }


def _render_widget(
    db: DbSession, widget: Widget, filters: FilterGroup | None
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
        if wants_breakdown and indicator.breakdown_variable:
            # Evaluated rather than read off the stored value, because a
            # breakdown that was computed at a different moment from the
            # headline above it would not add up to it - and the two sitting in
            # one tile invite exactly that comparison.
            outcome = evaluate_indicator(db, indicator)
            if outcome.get("error"):
                return {"error": outcome["error"]}
            value = outcome["value"]
            breakdown = outcome["breakdown"]
            computed_at = utcnow()

        return {
            "type": "indicator",
            "name": indicator.name,
            "value": value,
            "unit": indicator.unit,
            "value_format": indicator.value_format,
            "target_value": indicator.target_value,
            "progress_percent": progress_percent(indicator, value),
            "status": indicator_status(indicator, value),
            "breakdown": breakdown,
            "breakdown_variable": indicator.breakdown_variable if wants_breakdown else "",
            "computed_at": computed_at.isoformat() if computed_at else None,
        }

    if widget.widget_type.value == "countdown":
        config = widget.config or {}
        return {
            "type": "countdown",
            "target": config.get("target"),
            "label": config.get("label", ""),
            "expired_text": config.get("expired_text", ""),
        }

    if widget.widget_type.value == "quality":
        return _render_quality(db, widget)

    if widget.chart_id:
        chart = db.get(Chart, widget.chart_id)
        if chart is None:
            return {"error": "Chart no longer exists"}
        dataset = db.get(Dataset, chart.dataset_id)
        if dataset is None or not dataset_is_queryable(dataset):
            return {"error": "The chart's dataset is unavailable"}
        ctx = DatasetContext.from_model(dataset)
        filters = _applicable(filters, ctx)
        if _is_crosstab(chart.spec or {}):
            crosstab = execute_crosstab(ctx, _crosstab_from_chart(chart, filters))
            return {
                "type": "crosstab",
                "chart_type": "crosstab",
                "name": chart.name,
                "result": crosstab.model_dump(mode="json"),
            }
        result = execute_query(ctx, _spec_from_chart(chart, filters))
        return {
            "type": "chart",
            "chart_type": chart.chart_type.value,
            "name": chart.name,
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
    spec = QuerySpec.model_validate(config.get("query", {}))
    if filters and not filters.is_empty():
        spec = spec.model_copy(
            update={
                "filters": FilterGroup(op="and", groups=[spec.filters, filters], conditions=[])
            }
        )
    result = execute_query(DatasetContext.from_model(dataset), spec)
    return {
        "type": widget.widget_type.value,
        "chart_type": config.get("chart_type", "bar"),
        "result": result.model_dump(mode="json"),
    }
