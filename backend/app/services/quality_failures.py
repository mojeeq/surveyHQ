"""Rows behind a quality-rule failure.

The quality page stores counts and a compact explanation. Investigation needs the
actual rows as well. This module builds those row queries from the same rule
configuration, while applying the rule's own filters before checking anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import CheckType, Dataset, QualityRule
from app.services.quality import rule_filters
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    SQLBuilder,
    _quote_path,
    quote_ident,
    run_sql,
)


@dataclass
class FailureRows:
    columns: list[str]
    rows: list[list[Any]]
    total: int
    truncated: bool


def _scoped_source(ctx: DatasetContext, rule: QualityRule) -> tuple[str, list[Any]]:
    filters = rule_filters(rule)
    builder = SQLBuilder(ctx)
    where = builder.filter_sql(filters) if filters and not filters.is_empty() else ""
    sql = f"SELECT * FROM read_parquet({_quote_path(ctx.parquet_path)})"
    if where:
        sql += f" WHERE {where}"
    return sql, list(builder.params)


def _simple_failure_sql(scoped_sql: str, condition: str) -> str:
    return f"WITH scoped AS ({scoped_sql}) SELECT * FROM scoped WHERE {condition}"


def _outlier_bounds(
    scoped_sql: str,
    scope_params: list[Any],
    col: str,
    method: str,
    factor: float,
) -> tuple[float, float] | None:
    if method == "zscore":
        _, rows = run_sql(
            f"SELECT AVG({col}), STDDEV_SAMP({col}) FROM ({scoped_sql}) scoped",
            scope_params,
        )
        mean, std = rows[0] if rows else (None, None)
        if mean is None or not std:
            return None
        return float(mean) - factor * float(std), float(mean) + factor * float(std)

    _, rows = run_sql(
        f"SELECT QUANTILE_CONT({col}, 0.25), QUANTILE_CONT({col}, 0.75) "
        f"FROM ({scoped_sql}) scoped",
        scope_params,
    )
    q1, q3 = rows[0] if rows else (None, None)
    if q1 is None or q3 is None:
        return None
    iqr = float(q3) - float(q1)
    return float(q1) - factor * iqr, float(q3) + factor * iqr


def _failure_sql(ctx: DatasetContext, rule: QualityRule) -> tuple[str, list[Any]]:
    config = rule.config or {}
    scoped_sql, scope_params = _scoped_source(ctx, rule)
    check = rule.check_type

    if check == CheckType.missing_rate:
        col = quote_ident(ctx.require(str(config.get("variable"))).name)
        return (
            _simple_failure_sql(
                scoped_sql,
                f"{col} IS NULL OR CAST({col} AS VARCHAR) = ''",
            ),
            scope_params,
        )

    if check == CheckType.value_range:
        col = quote_ident(ctx.require(str(config.get("variable"))).name)
        clauses: list[str] = []
        params = list(scope_params)
        if config.get("min") is not None:
            clauses.append(f"{col} < ?")
            params.append(float(config["min"]))
        if config.get("max") is not None:
            clauses.append(f"{col} > ?")
            params.append(float(config["max"]))
        if not clauses:
            raise QueryError("A range check needs a min and/or a max value.")
        condition = f"{col} IS NOT NULL AND (" + " OR ".join(clauses) + ")"
        return _simple_failure_sql(scoped_sql, condition), params

    if check == CheckType.interview_duration:
        col = quote_ident(ctx.require(str(config.get("variable"))).name)
        minimum = float(config.get("min_minutes", 10))
        params = [*scope_params, minimum]
        clauses = [f"{col} < ?"]
        if config.get("max_minutes") is not None:
            clauses.append(f"{col} > ?")
            params.append(float(config["max_minutes"]))
        condition = f"{col} IS NOT NULL AND (" + " OR ".join(clauses) + ")"
        return _simple_failure_sql(scoped_sql, condition), params

    if check == CheckType.gps_missing:
        lat = quote_ident(ctx.require(str(config.get("latitude_variable"))).name)
        lon = quote_ident(ctx.require(str(config.get("longitude_variable"))).name)
        condition = f"{lat} IS NULL OR {lon} IS NULL OR ({lat} = 0 AND {lon} = 0)"
        return _simple_failure_sql(scoped_sql, condition), scope_params

    if check == CheckType.consistency:
        left = quote_ident(ctx.require(str(config.get("variable"))).name)
        right = quote_ident(ctx.require(str(config.get("other_variable"))).name)
        operator = str(config.get("operator", "lte"))
        symbols = {
            "lt": "<",
            "lte": "<=",
            "gt": ">",
            "gte": ">=",
            "eq": "=",
            "ne": "!=",
        }
        if operator not in symbols:
            raise QueryError(f"Unsupported consistency operator '{operator}'.")
        condition = (
            f"{left} IS NOT NULL AND {right} IS NOT NULL "
            f"AND NOT ({left} {symbols[operator]} {right})"
        )
        return _simple_failure_sql(scoped_sql, condition), scope_params

    if check == CheckType.outliers:
        col = quote_ident(ctx.require(str(config.get("variable"))).name)
        method = str(config.get("method", "iqr"))
        factor = float(config.get("factor", 1.5))
        bounds = _outlier_bounds(scoped_sql, scope_params, col, method, factor)
        if bounds is None:
            return (
                f"WITH scoped AS ({scoped_sql}) SELECT * FROM scoped WHERE FALSE",
                scope_params,
            )
        low, high = bounds
        return (
            _simple_failure_sql(
                scoped_sql,
                f"{col} IS NOT NULL AND ({col} < ? OR {col} > ?)",
            ),
            [*scope_params, low, high],
        )

    if check == CheckType.duplicates:
        variables = config.get("variables") or (
            [config["variable"]] if config.get("variable") else []
        )
        if not variables:
            raise QueryError("A duplicate check needs at least one variable.")
        columns = ", ".join(quote_ident(ctx.require(str(v)).name) for v in variables)
        # Keep every member of a duplicate group for investigation. The stored
        # quality result counts only the extra rows (n-1), while this view shows
        # the whole group so the analyst can see which copy should survive.
        sql = (
            f"WITH scoped AS ({scoped_sql}), marked AS ("
            f"SELECT *, COUNT(*) OVER (PARTITION BY {columns}) AS __duplicate_group_size "
            f"FROM scoped) "
            f"SELECT * EXCLUDE (__duplicate_group_size), "
            f"__duplicate_group_size AS duplicate_group_size "
            f"FROM marked WHERE __duplicate_group_size > 1"
        )
        return sql, scope_params

    if check == CheckType.constant_value:
        variable = str(config.get("variable"))
        col = quote_ident(ctx.require(variable).name)
        group_by = config.get("group_variable")
        if not group_by:
            _, rows = run_sql(
                f"SELECT COUNT(DISTINCT {col}) FROM ({scoped_sql}) scoped",
                scope_params,
            )
            distinct = int(rows[0][0]) if rows else 0
            if distinct > 1:
                return (
                    f"WITH scoped AS ({scoped_sql}) SELECT * FROM scoped WHERE FALSE",
                    scope_params,
                )
            return f"WITH scoped AS ({scoped_sql}) SELECT * FROM scoped", scope_params

        group_col = quote_ident(ctx.require(str(group_by)).name)
        minimum = int(config.get("min_records", 5))
        sql = (
            f"WITH scoped AS ({scoped_sql}), bad_groups AS ("
            f"SELECT {group_col} AS __quality_group, COUNT(*) AS constant_group_size "
            f"FROM scoped WHERE {group_col} IS NOT NULL GROUP BY {group_col} "
            f"HAVING COUNT(*) >= ? AND COUNT(DISTINCT {col}) = 1) "
            f"SELECT scoped.*, bad_groups.constant_group_size FROM scoped "
            f"JOIN bad_groups ON scoped.{group_col} "
            f"IS NOT DISTINCT FROM bad_groups.__quality_group"
        )
        return sql, [*scope_params, minimum]

    raise QueryError(f"Unsupported quality check '{check.value}'.")


def failed_records(
    dataset: Dataset,
    rule: QualityRule,
    *,
    limit: int = 200,
    offset: int = 0,
) -> FailureRows:
    """Return the records implicated by a rule, with a stable total count."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset cannot be negative")
    ctx = DatasetContext.from_model(dataset)
    sql, params = _failure_sql(ctx, rule)
    _, count_rows = run_sql(f"SELECT COUNT(*) FROM ({sql}) failures", params)
    total = int(count_rows[0][0]) if count_rows else 0
    columns, rows = run_sql(
        f"SELECT * FROM ({sql}) failures LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return FailureRows(
        columns=columns,
        rows=[list(row) for row in rows],
        total=total,
        truncated=offset + len(rows) < total,
    )
