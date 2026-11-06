"""Survey-specific views built automatically from a dataset's detected fields.

When a dataset comes from Survey Solutions (or an upload with the same column
names) the platform can offer field-progress views with no configuration:
submissions over time, productivity per interviewer, status breakdown and a map
of visited points.
"""

from __future__ import annotations

from typing import Any

from app.models import Dataset
from app.schemas.query import (
    Aggregation,
    Dimension,
    FilterGroup,
    Measure,
    QuerySpec,
    SortSpec,
)
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    _quote_path,
    execute_query,
    quote_ident,
    run_sql,
)


def monitoring_fields(dataset: Dataset) -> dict[str, str]:
    return dict((dataset.meta or {}).get("monitoring_fields", {}))


def _rows_to_dicts(result: Any) -> list[dict[str, Any]]:
    names = [column.name for column in result.columns]
    return [dict(zip(names, row, strict=False)) for row in result.rows]


def status_breakdown(
    ctx: DatasetContext, fields: dict[str, str], filters: FilterGroup
) -> list[dict[str, Any]]:
    variable = fields.get("status")
    if not variable or variable not in ctx.variables:
        return []
    spec = QuerySpec(
        dimensions=[Dimension(variable=variable, alias="status")],
        measures=[Measure(agg=Aggregation.count, alias="count")],
        filters=filters,
        sort=[SortSpec(field="count", direction="desc")],
        limit=50,
    )
    return _rows_to_dicts(execute_query(ctx, spec))


def submissions_over_time(
    ctx: DatasetContext, fields: dict[str, str], filters: FilterGroup, grain: str = "day"
) -> list[dict[str, Any]]:
    variable = fields.get("date")
    if not variable or variable not in ctx.variables:
        return []
    spec = QuerySpec(
        dimensions=[Dimension(variable=variable, alias="period", grain=grain)],  # type: ignore[arg-type]
        measures=[Measure(agg=Aggregation.count, alias="count")],
        filters=filters,
        sort=[SortSpec(field="period", direction="asc")],
        limit=2000,
    )
    rows = _rows_to_dicts(execute_query(ctx, spec))
    running = 0
    for row in rows:
        running += int(row.get("count") or 0)
        row["cumulative"] = running
    return rows


def productivity(
    ctx: DatasetContext,
    fields: dict[str, str],
    filters: FilterGroup,
    by: str = "interviewer",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Interviews completed per interviewer or team, with mean duration."""
    variable = fields.get(by)
    if not variable or variable not in ctx.variables:
        return []
    measures = [Measure(agg=Aggregation.count, alias="interviews")]
    duration = fields.get("duration")
    if duration and duration in ctx.variables:
        measures.append(
            Measure(agg=Aggregation.mean, variable=duration, alias="mean_duration")
        )
        measures.append(
            Measure(agg=Aggregation.median, variable=duration, alias="median_duration")
        )
    spec = QuerySpec(
        dimensions=[Dimension(variable=variable, alias=by)],
        measures=measures,
        filters=filters,
        sort=[SortSpec(field="interviews", direction="desc")],
        limit=limit,
    )
    return _rows_to_dicts(execute_query(ctx, spec))


def geo_points(
    ctx: DatasetContext, fields: dict[str, str], filters: FilterGroup, limit: int = 5000
) -> list[dict[str, Any]]:
    """Interview locations for the map widget."""
    latitude = fields.get("latitude")
    longitude = fields.get("longitude")
    if not latitude or not longitude:
        return []
    if latitude not in ctx.variables or longitude not in ctx.variables:
        return []

    lat_col = quote_ident(latitude)
    lon_col = quote_ident(longitude)
    label_parts = []
    for key in ("interview_key", "interviewer", "status"):
        name = fields.get(key)
        if name and name in ctx.variables:
            label_parts.append((key, quote_ident(name)))

    selected = f"{lat_col} AS lat, {lon_col} AS lon" + "".join(
        f", {column} AS {quote_ident(key)}" for key, column in label_parts
    )
    sql = (
        f"SELECT {selected} FROM read_parquet({_quote_path(ctx.parquet_path)}) "
        f"WHERE {lat_col} IS NOT NULL AND {lon_col} IS NOT NULL "
        f"AND {lat_col} BETWEEN -90 AND 90 AND {lon_col} BETWEEN -180 AND 180 "
        f"AND NOT ({lat_col} = 0 AND {lon_col} = 0) LIMIT {int(limit)}"
    )
    columns, rows = run_sql(sql)
    return [dict(zip(columns, row, strict=False)) for row in rows]


def coverage_by_area(
    ctx: DatasetContext, fields: dict[str, str], filters: FilterGroup, limit: int = 100
) -> list[dict[str, Any]]:
    variable = fields.get("region")
    if not variable or variable not in ctx.variables:
        return []
    spec = QuerySpec(
        dimensions=[Dimension(variable=variable, alias="area")],
        measures=[Measure(agg=Aggregation.count, alias="interviews")],
        filters=filters,
        sort=[SortSpec(field="interviews", direction="desc")],
        limit=limit,
    )
    return _rows_to_dicts(execute_query(ctx, spec))


def build_overview(
    dataset: Dataset, filters: FilterGroup | None = None, grain: str = "day"
) -> dict[str, Any]:
    """Assemble every field-progress view the dataset supports."""
    ctx = DatasetContext.from_model(dataset)
    fields = monitoring_fields(dataset)
    filters = filters or FilterGroup()

    overview: dict[str, Any] = {
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "total_records": dataset.row_count,
        "detected_fields": fields,
        "available_views": [],
    }

    def attempt(key: str, function: Any, *args: Any) -> None:
        try:
            value = function(ctx, fields, filters, *args)
        except QueryError:
            value = []
        overview[key] = value
        if value:
            overview["available_views"].append(key)

    attempt("status_breakdown", status_breakdown)
    attempt("submissions_over_time", submissions_over_time, grain)
    attempt("by_interviewer", productivity, "interviewer")
    attempt("by_supervisor", productivity, "supervisor")
    attempt("coverage_by_area", coverage_by_area)
    attempt("geo_points", geo_points)

    completed = 0
    for row in overview.get("status_breakdown") or []:
        label = str(row.get("status") or "").lower()
        if "complet" in label or "approv" in label:
            completed += int(row.get("count") or 0)
    overview["completed_records"] = completed
    overview["completion_rate"] = (
        round(completed / dataset.row_count * 100, 2) if dataset.row_count else None
    )
    return overview
