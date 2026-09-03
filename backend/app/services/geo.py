"""Interview locations for the map widget.

A monitoring map answers two questions: where has the fieldwork been, and what
happened at this spot. So points are grouped by coordinate rather than drawn one
per row - several interviews at one household, or a roster's many people at one
address, are one pin carrying a number rather than a pile of pins hiding each
other.
"""

from __future__ import annotations

from typing import Any

from app.schemas.query import FilterGroup
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    SQLBuilder,
    _label_value,
    _quote_path,
    quote_ident,
    run_sql,
)

# A dashboard map is read at a glance; past a few thousand pins it is a smear,
# and the browser is doing the work of drawing them.
MAX_POINTS = 5000

AGGREGATIONS = {
    "count": None,
    "sum": "SUM",
    "mean": "AVG",
    "min": "MIN",
    "max": "MAX",
}


def points(
    ctx: DatasetContext,
    latitude: str,
    longitude: str,
    detail: list[str] | None = None,
    measure_agg: str = "count",
    measure_variable: str = "",
    filters: FilterGroup | None = None,
    limit: int = MAX_POINTS,
) -> dict[str, Any]:
    """Grouped coordinates, each with a value and the details to show on click."""
    for name in (latitude, longitude):
        if name not in ctx.variables:
            raise QueryError(f"'{name}' is not a variable in this dataset")
    if measure_agg not in AGGREGATIONS:
        raise QueryError(f"'{measure_agg}' is not an aggregation this map can show")

    lat = quote_ident(ctx.require(latitude).name)
    lon = quote_ident(ctx.require(longitude).name)

    function = AGGREGATIONS[measure_agg]
    if function and measure_variable:
        if measure_variable not in ctx.variables:
            raise QueryError(f"'{measure_variable}' is not a variable in this dataset")
        value = f"{function}(try_cast({quote_ident(measure_variable)} AS DOUBLE))"
    else:
        # No variable to aggregate is not an error: how many interviews are at
        # this spot is the question a map is usually asked first.
        measure_agg, measure_variable = "count", ""
        value = "COUNT(*)"

    # One row of each group carries the details, which is what a popup shows.
    # ANY_VALUE rather than MIN so a text column is not silently alphabetised
    # into a value from a different row than the rest.
    details = [name for name in (detail or []) if name in ctx.variables]
    selected = "".join(
        f", ANY_VALUE({quote_ident(name)}) AS {quote_ident(name)}" for name in details
    )

    builder = SQLBuilder(ctx)
    where = builder.filter_sql(filters) if filters else ""
    params = list(builder.params)
    conditions = [
        f"{lat} IS NOT NULL",
        f"{lon} IS NOT NULL",
        f"{lat} BETWEEN -90 AND 90",
        f"{lon} BETWEEN -180 AND 180",
        # Null Island is what a device with no fix records, not a place anybody
        # interviewed anyone.
        f"NOT ({lat} = 0 AND {lon} = 0)",
    ]
    if where:
        conditions.append(f"({where})")

    sql = (
        f"SELECT {lat} AS lat, {lon} AS lon, {value} AS value, COUNT(*) AS rows{selected} "
        f"FROM read_parquet({_quote_path(ctx.parquet_path)}) "
        f"WHERE {' AND '.join(conditions)} "
        f"GROUP BY 1, 2 ORDER BY 3 DESC LIMIT {int(limit) + 1}"
    )
    columns, rows = run_sql(sql, params)
    found = [dict(zip(columns, row, strict=False)) for row in rows]
    # A popup reading "province: 3" is the code, not the answer.
    for name in details:
        info = ctx.variables.get(name)
        if not info or not info.value_labels:
            continue
        for point in found:
            point[name] = _label_value(info, point[name])
    truncated = len(found) > limit
    return {
        "points": found[:limit],
        "detail": details,
        "measure": {"agg": measure_agg, "variable": measure_variable},
        "truncated": truncated,
    }
