"""A dashboard as one HTML file, with its filters still working.

A monitoring board is often wanted somewhere this platform is not: on a
ministry's own web host, attached to a report, on a laptop taken to a meeting
where the survey server is not reachable. Sending a picture of it loses the one
thing that makes a dashboard a dashboard, which is that the reader can narrow
it and see the numbers move.

So the export carries data rather than pictures. For each widget it takes the
same query the widget is drawn from and runs it at a finer grain: grouped by
what the widget groups on *and* by every variable the page's filter controls
name. That table is the cube. Choosing "Shefa" in the exported page keeps the
rows where province is Shefa and adds the measures back up, which gives exactly
the number the platform would have returned for that filter - no approximation,
because sums of counts are counts.

What cannot be added back up is not pretended to be. A median of medians is not
a median and a count of distinct interviewers cannot be recovered from group
counts, so a widget resting on one of those is exported as it stands, with a
line on it saying the filters do not reach it. The same goes for the data
quality and freshness panels, which are not queries over the data at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (
    Chart,
    Dashboard,
    Dataset,
    Indicator,
    Widget,
)
from app.schemas.query import (
    Aggregation,
    CrosstabRequest,
    Dimension,
    Measure,
    QuerySpec,
)
from app.services.datasets import dataset_is_queryable
from app.services.query_engine import DatasetContext, QueryError, execute_query

TEMPLATE = Path(__file__).parent / "export_assets" / "dashboard.html"

# How many rows of cube one widget may carry. A cube is the widget's own
# grouping crossed with every filter variable, so a chart by day filtered by
# province and interviewer is days x provinces x interviewers - which is fine
# until one of those is an identifier. Past this the widget is exported as it
# stands rather than quietly turning a 3 MB page into a 300 MB one.
MAX_CUBE_ROWS = 20_000

# Aggregations whose group results can be combined into the result for a union
# of those groups. Everything else needs the rows themselves.
COMBINABLE = {
    Aggregation.count: "sum",
    Aggregation.share: "sum",
    Aggregation.sum: "sum",
    Aggregation.min: "min",
    Aggregation.max: "max",
    Aggregation.mean: "mean",
}


def _label(measure: Measure) -> str:
    """What to call this measure on the exported page."""
    if measure.alias:
        return measure.alias
    if measure.agg == Aggregation.count and not measure.variable:
        return "Count"
    return f"{measure.agg.value} of {measure.variable}" if measure.variable else measure.agg.value


class NotExportable(Exception):
    """This widget cannot be recomputed offline, and why."""


def _recipe(measures: list[Measure]) -> tuple[list[Measure], list[dict[str, Any]]]:
    """The measures to ask the database for, and how to rebuild the real ones.

    A mean is the one that needs taking apart: the average of a set of group
    averages is not the average of the set, so the export asks for the total
    and the number of values behind each group and divides them again in the
    browser. Everything else combines as itself.
    """
    asked: list[Measure] = []
    recipes: list[dict[str, Any]] = []
    for index, measure in enumerate(measures):
        if measure.agg not in COMBINABLE:
            raise NotExportable(
                f"a {measure.agg.value} cannot be worked out again from grouped totals"
            )
        if measure.weight and measure.agg == Aggregation.mean:
            raise NotExportable("a weighted mean cannot be worked out again from group totals")
        name = measure.output_name
        if measure.agg == Aggregation.mean:
            total = f"__x{index}_total"
            count = f"__x{index}_count"
            asked.append(Measure(agg=Aggregation.sum, variable=measure.variable, alias=total))
            asked.append(
                Measure(agg=Aggregation.count, variable=measure.variable, alias=count)
            )
            recipes.append(
                {"name": name, "label": _label(measure), "how": "mean", "parts": [total, count]}
            )
            continue
        asked.append(measure.model_copy(update={"alias": name}))
        recipes.append(
            {
                "name": name,
                "label": _label(measure),
                "how": COMBINABLE[measure.agg],
                "parts": [name],
            }
        )
    return asked, recipes


def _cube(
    ctx: DatasetContext,
    spec: QuerySpec,
    filter_variables: list[str],
) -> dict[str, Any]:
    """One widget's numbers, at the grain its filters need.

    The widget's own top-N is deliberately not applied here. "The ten busiest
    interviewers" is a different ten once the page is narrowed to one province,
    and a cube holding only the national ten could not produce the provincial
    ones. The whole grouping is exported and the top-N is taken in the browser,
    after the filter.
    """
    own = [dimension.output_name for dimension in spec.dimensions]
    # A filter variable the widget already groups on needs no column of its
    # own: the grouping is the grain. Matched on the variable rather than the
    # output name, because a cross-tab groups by its row and column variables
    # under aliases of its own and would otherwise carry each of them twice.
    grouped = {
        dimension.variable: dimension.output_name for dimension in spec.dimensions
    }
    extra = [name for name in filter_variables if name not in grouped]
    # Which column answers for which control: a selection is made against a
    # variable, and the column holding it may be one of the widget's own
    # groupings under an alias of its own.
    against = [
        {"variable": name, "column": grouped.get(name, name)} for name in filter_variables
    ]
    asked, recipes = _recipe(list(spec.measures))
    grained = spec.model_copy(
        update={
            "dimensions": [
                *[d.model_copy(update={"limit": None}) for d in spec.dimensions],
                *[Dimension(variable=name) for name in extra],
            ],
            "measures": asked,
            "limit": MAX_CUBE_ROWS + 1,
            "offset": 0,
        }
    )
    result = execute_query(ctx, grained)
    if len(result.rows) > MAX_CUBE_ROWS:
        raise NotExportable(
            "there are too many combinations of its groups and this page's filters"
        )
    return {
        "dimensions": own,
        # The columns a selection is tested against: the extra ones just added,
        # plus the widget's own grouping where it already covers a filter.
        "filters": against,
        "measures": recipes,
        "columns": [
            {
                "name": column.name,
                "label": column.label,
                "type": column.type,
                # A date axis is read in order, not biggest first, and the
                # browser has no other way to tell a date from a category.
                "data_type": column.data_type,
            }
            for column in result.columns
        ],
        "rows": result.rows,
        # The sort and the top-N the chart was saved with, applied again in the
        # browser once the rows have been added back up.
        "top": spec.dimensions[0].limit if spec.dimensions else None,
        "sort": [{"field": s.field, "direction": s.direction} for s in spec.sort],
    }


def _filters_for(dashboard: Dashboard) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for raw in dashboard.filters or []:
        if not isinstance(raw, dict):
            continue
        variable = str(raw.get("variable") or "")
        if not variable:
            continue
        controls.append(
            {
                "variable": variable,
                "label": str(raw.get("label") or variable),
                "dataset_id": str(raw.get("dataset_id") or ""),
                "page": int(raw.get("page") or 0),
                "values": [],
            }
        )
    return controls


def _values_for(ctx: DatasetContext, variable: str, limit: int = 200) -> list[str]:
    """The choices a dropdown offers, in the order the live page offers them."""
    spec = QuerySpec(
        dimensions=[Dimension(variable=variable)],
        measures=[Measure(agg=Aggregation.count, alias="n")],
        sort=[],
        limit=limit,
        use_labels=True,
        drop_missing=True,
    )
    try:
        result = execute_query(ctx, spec)
    except QueryError:
        return []
    seen: list[str] = []
    for row in result.rows:
        value = row[0]
        if value is None:
            continue
        text = str(value)
        if text and text not in seen:
            seen.append(text)
    return sorted(seen)


def _ctx_for(db: Session, dataset_id: str | None) -> DatasetContext | None:
    if not dataset_id:
        return None
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or not dataset_is_queryable(dataset):
        return None
    try:
        return DatasetContext.from_model(dataset)
    except QueryError:
        return None


def _applicable_names(ctx: DatasetContext, controls: list[dict[str, Any]]) -> list[str]:
    """The filter variables this widget's dataset actually has.

    The same rule the live page follows: a control naming a variable the
    widget's dataset does not carry leaves that widget alone rather than
    emptying it.
    """
    known = set(ctx.variables)
    names: list[str] = []
    for control in controls:
        variable = control["variable"]
        if variable in known and variable not in names:
            names.append(variable)
    return names


def _crosstab_spec(request: CrosstabRequest) -> QuerySpec:
    """The cross-tab as an ordinary grouped query, which is what it is.

    Rebuilt in the browser from the same counts: the totals and percentages a
    cross-tab shows are arithmetic on the cells, so they follow the filter
    without anything else having to be exported.
    """
    dimensions = []
    if request.row_variable:
        dimensions.append(Dimension(variable=request.row_variable, alias="__row"))
    if request.column_variable:
        dimensions.append(Dimension(variable=request.column_variable, alias="__column"))
    return QuerySpec(
        dimensions=dimensions,
        measures=[request.measure.model_copy(update={"alias": "__value"})],
        filters=request.filters,
        use_labels=request.use_labels,
        limit=MAX_CUBE_ROWS + 1,
    )


def _chart_widget(
    db: Session, widget: Widget, controls: list[dict[str, Any]]
) -> dict[str, Any]:
    chart = db.get(Chart, widget.chart_id or "")
    if chart is None:
        raise NotExportable("the chart it draws is no longer here")
    spec_raw = chart.spec or {}
    ctx = _ctx_for(db, chart.dataset_id)
    if ctx is None:
        raise NotExportable("its dataset is not available")
    names = _applicable_names(ctx, controls)

    if spec_raw.get("multiselect", {}).get("columns"):
        raise NotExportable(
            "a tick-all-that-apply chart is built from columns rather than groups"
        )

    if spec_raw.get("crosstab"):
        request = CrosstabRequest.model_validate(spec_raw["crosstab"])
        cube = _cube(ctx, _crosstab_spec(request), names)
        return {
            "kind": "crosstab",
            "chart_type": "crosstab",
            "crosstab": {
                "row_variable": request.row_variable,
                "column_variable": request.column_variable,
                "percentages": request.percentages,
                "include_totals": request.include_totals,
                "measure_label": (
                    "Count"
                    if request.measure.agg == Aggregation.count
                    else f"{request.measure.agg.value} of {request.measure.variable}"
                ),
            },
            "cube": cube,
        }

    spec = QuerySpec.model_validate(spec_raw.get("query", spec_raw))
    return {
        "kind": "chart",
        "chart_type": chart.chart_type.value,
        "display": spec_raw.get("options") or {},
        "cube": _cube(ctx, spec, names),
    }


def _inline_widget(
    db: Session, widget: Widget, controls: list[dict[str, Any]]
) -> dict[str, Any]:
    config = widget.config or {}
    ctx = _ctx_for(db, widget.dataset_id or config.get("dataset_id"))
    if ctx is None:
        raise NotExportable("its dataset is not available")
    spec = QuerySpec.model_validate(config.get("query", {}))
    return {
        "kind": "chart",
        "chart_type": config.get("chart_type", "bar")
        if widget.widget_type.value == "chart"
        else widget.widget_type.value,
        "display": config.get("options") or {},
        "cube": _cube(ctx, spec, _applicable_names(ctx, controls)),
    }


def _indicator_widget(
    db: Session, widget: Widget, controls: list[dict[str, Any]]
) -> dict[str, Any]:
    indicator = db.get(Indicator, widget.indicator_id or "")
    if indicator is None:
        raise NotExportable("the indicator behind it is no longer here")
    ctx = _ctx_for(db, indicator.dataset_id)
    if ctx is None:
        raise NotExportable("its dataset is not available")
    spec = QuerySpec.model_validate(indicator.spec or {})
    names = _applicable_names(ctx, controls)
    shows_breakdown = bool((widget.config or {}).get("show_breakdown"))
    breakdown = indicator.breakdown_variable if shows_breakdown else ""
    headline = spec.model_copy(
        update={
            "dimensions": [Dimension(variable=breakdown)] if breakdown else [],
            "limit": MAX_CUBE_ROWS + 1,
        }
    )
    payload: dict[str, Any] = {
        "kind": "indicator",
        "indicator": {
            "name": indicator.name,
            "unit": indicator.unit,
            "value_format": indicator.value_format,
            "target_value": indicator.target_value,
            "warning_threshold": indicator.warning_threshold,
            "critical_threshold": indicator.critical_threshold,
            "direction": indicator.direction.value,
            "breakdown_variable": breakdown,
            "breakdown_targets": indicator.breakdown_targets or {},
            "percent_of": indicator.percent_of or "",
        },
        "cube": _cube(ctx, headline, names),
    }
    if indicator.percent_of:
        # The rows the indicator's own count is a share of. Its filters are
        # dropped and the page's are not, exactly as the live tile does it, so
        # a filtered percentage stays a rate rather than becoming a share of
        # the national total.
        keep = QuerySpec(
            dimensions=[Dimension(variable=breakdown)] if breakdown else [],
            measures=[Measure(agg=Aggregation.count, alias="value")],
            filters=_denominator_filters(indicator, spec),
            limit=MAX_CUBE_ROWS + 1,
        )
        payload["denominator"] = _cube(ctx, keep, names)
    return payload


def _denominator_filters(indicator: Indicator, spec: QuerySpec):
    from app.schemas.query import Condition, FilterGroup

    if indicator.percent_of == "answered":
        measured = next((m.variable for m in spec.measures if m.variable), None)
        if measured:
            return FilterGroup(
                conditions=[Condition(variable=measured, operator="is_not_null")]
            )
    return FilterGroup()


def _map_widget(db: Session, widget: Widget, controls: list[dict[str, Any]]) -> dict[str, Any]:
    config = widget.config or {}
    ctx = _ctx_for(db, widget.dataset_id or config.get("dataset_id"))
    if ctx is None:
        raise NotExportable("its dataset is not available")
    latitude = str(config.get("latitude") or "")
    longitude = str(config.get("longitude") or "")
    if latitude not in ctx.variables or longitude not in ctx.variables:
        raise NotExportable("its coordinate variables are not in the dataset")
    detail = [name for name in (config.get("detail") or []) if name in ctx.variables]
    agg = str(config.get("measure_agg") or "count")
    variable = str(config.get("measure_variable") or "")
    measure = (
        Measure(agg=Aggregation(agg), variable=variable, alias="value")
        if variable and agg != "count"
        else Measure(agg=Aggregation.count, alias="value")
    )
    spec = QuerySpec(
        dimensions=[
            Dimension(variable=latitude, alias="__lat"),
            Dimension(variable=longitude, alias="__lon"),
            *[Dimension(variable=name) for name in detail],
        ],
        measures=[measure],
        limit=MAX_CUBE_ROWS + 1,
    )
    return {
        "kind": "map",
        "map": {
            "detail": detail,
            "measure_label": "Interviews here" if agg == "count" else f"{agg} of {variable}",
            "point_color": config.get("point_color") or "",
            "point_size": config.get("point_size") or 0,
            "point_opacity": config.get("point_opacity"),
            "size_by_value": config.get("size_by_value", True),
        },
        "cube": _cube(ctx, spec, _applicable_names(ctx, controls)),
    }


BUILDERS = {
    "chart": _chart_widget,
    "crosstab": _chart_widget,
    "table": _inline_widget,
    "kpi": _inline_widget,
    "indicator": _indicator_widget,
    "map": _map_widget,
}

# Panels that are not a query over the survey data at all, and so have nothing
# a filter could narrow offline. They are exported as they stand.
AS_THEY_STAND = {
    "quality": "a data quality panel reports what the last run of its checks found",
    "freshness": "a freshness panel reports when data last arrived",
}


def build_payload(
    db: Session,
    dashboard: Dashboard,
    render: Any,
) -> dict[str, Any]:
    """Everything the exported page needs, as plain JSON.

    `render` is the dashboard renderer, handed in rather than imported: it
    lives with the API and importing it here would tie a service to an
    endpoint. It draws the widgets that cannot be recomputed offline, exactly
    as they stand right now.
    """
    controls = _filters_for(dashboard)
    for control in controls:
        ctx = _ctx_for(db, control["dataset_id"])
        control["values"] = _values_for(ctx, control["variable"]) if ctx else []
    # A control nothing can answer is worse than no control: it would sit on
    # the page offering choices that move nothing.
    controls = [control for control in controls if control["values"]]

    widgets: list[dict[str, Any]] = []
    for widget in sorted(dashboard.widgets, key=lambda w: (w.page or 0, w.position or 0)):
        page = widget.page or 0
        mine = [control for control in controls if control["page"] == page]
        entry: dict[str, Any] = {
            "id": widget.id,
            "title": widget.title or "",
            "type": widget.widget_type.value,
            "page": page,
            "layout": widget.layout or {},
            # A widget's styling lives among its config, which also holds its
            # query: only the part that says how it looks is carried over.
            "style": {
                key: value
                for key, value in (widget.config or {}).items()
                if key in ("background", "font_family", "font_color", "caption")
            },
            "config": {
                key: value
                for key, value in (widget.config or {}).items()
                # The whole query and its options are already in the cube; what
                # is kept here is what the page draws with.
                if key in ("content", "html", "target", "label", "expired_text",
                           "show_breakdown", "columns")
            },
        }
        builder = BUILDERS.get(widget.widget_type.value)
        reason = AS_THEY_STAND.get(widget.widget_type.value)
        if builder is not None and reason is None:
            try:
                entry.update(builder(db, widget, mine))
            except NotExportable as exc:
                reason = str(exc)
            except QueryError as exc:
                reason = str(exc)
        if reason is not None or builder is None:
            entry["kind"] = "snapshot"
            entry["snapshot"] = render(widget)
            # Only worth saying where a filter exists that the reader will
            # expect to move it. A text box is not "not filtered"; it simply
            # has nothing to filter.
            entry["frozen_because"] = reason if (reason and mine) else ""
        widgets.append(entry)

    pages = [
        {"name": str((page or {}).get("name") or f"Page {index + 1}")}
        for index, page in enumerate(dashboard.pages or [{"name": "Page 1"}])
    ]
    return {
        "name": dashboard.name,
        "description": dashboard.description or "",
        "generated_at": utcnow().isoformat(),
        "theme": dashboard.theme or "default",
        "appearance": dashboard.appearance or {},
        "pages": pages,
        "filters": controls,
        "widgets": widgets,
    }


def render_html(payload: dict[str, Any]) -> str:
    """The payload wrapped in the page that draws it.

    The data goes in as JSON inside a script tag of a type the browser does not
    execute, so nothing in a survey answer can become code on the page. The
    only sequence that could end that tag early is escaped.
    """
    data = json.dumps(payload, default=str, separators=(",", ":"))
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = TEMPLATE.read_text(encoding="utf-8")
    return template.replace("__TITLE__", _escape(payload["name"])).replace(
        '"__PAYLOAD__"', data
    )


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
