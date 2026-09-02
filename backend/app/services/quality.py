"""Data quality checks - the field-monitoring side of the platform.

Each check turns a rule into a DuckDB query and reports the share of rows that
violate it. Checks are deliberately simple and explainable: a supervisor needs
to know exactly which interviews to look at.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import CheckType, Dataset, QualityResult, QualityRule
from app.services.datasets import dataset_is_queryable
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    _quote_path,
    quote_ident,
    run_sql,
)

logger = get_logger(__name__)


@dataclass
class CheckOutcome:
    passed: bool
    failed_rows: int
    total_rows: int
    message: str
    details: dict[str, Any]

    @property
    def failure_rate(self) -> float:
        return self.failed_rows / self.total_rows if self.total_rows else 0.0


def _total_rows(ctx: DatasetContext) -> int:
    _, rows = run_sql(f"SELECT COUNT(*) FROM read_parquet({_quote_path(ctx.parquet_path)})")
    return int(rows[0][0]) if rows else 0


def _count_where(ctx: DatasetContext, where: str, params: list[Any] | None = None) -> int:
    sql = (
        f"SELECT COUNT(*) FROM read_parquet({_quote_path(ctx.parquet_path)}) WHERE {where}"
    )
    _, rows = run_sql(sql, params or [])
    return int(rows[0][0]) if rows else 0


def run_check(ctx: DatasetContext, rule: QualityRule) -> CheckOutcome:
    config = rule.config or {}
    total = _total_rows(ctx)
    if total == 0:
        return CheckOutcome(True, 0, 0, "Dataset has no rows to check.", {})

    handler = {
        CheckType.missing_rate: _check_missing,
        CheckType.value_range: _check_range,
        CheckType.duplicates: _check_duplicates,
        CheckType.outliers: _check_outliers,
        CheckType.consistency: _check_consistency,
        CheckType.interview_duration: _check_duration,
        CheckType.gps_missing: _check_gps,
        CheckType.constant_value: _check_constant,
    }[rule.check_type]
    return handler(ctx, config, total)


def _check_missing(ctx: DatasetContext, config: dict, total: int) -> CheckOutcome:
    variable = config.get("variable")
    info = ctx.require(str(variable))
    col = quote_ident(info.name)
    failed = _count_where(ctx, f"{col} IS NULL OR CAST({col} AS VARCHAR) = ''")
    rate = failed / total
    return CheckOutcome(
        passed=True,
        failed_rows=failed,
        total_rows=total,
        message=f"{failed:,} of {total:,} rows ({rate:.1%}) are missing {info.name}.",
        details={"variable": info.name, "missing": failed},
    )


def _check_range(ctx: DatasetContext, config: dict, total: int) -> CheckOutcome:
    variable = config.get("variable")
    info = ctx.require(str(variable))
    col = quote_ident(info.name)
    minimum = config.get("min")
    maximum = config.get("max")
    clauses: list[str] = []
    params: list[Any] = []
    if minimum is not None:
        clauses.append(f"{col} < ?")
        params.append(float(minimum))
    if maximum is not None:
        clauses.append(f"{col} > ?")
        params.append(float(maximum))
    if not clauses:
        raise QueryError("A range check needs a min and/or a max value.")
    where = f"{col} IS NOT NULL AND (" + " OR ".join(clauses) + ")"
    failed = _count_where(ctx, where, params)
    return CheckOutcome(
        passed=True,
        failed_rows=failed,
        total_rows=total,
        message=(
            f"{failed:,} rows fall outside the allowed range for {info.name} "
            f"[{minimum if minimum is not None else '-inf'}, "
            f"{maximum if maximum is not None else 'inf'}]."
        ),
        details={"variable": info.name, "min": minimum, "max": maximum},
    )


def _check_duplicates(ctx: DatasetContext, config: dict, total: int) -> CheckOutcome:
    variables = config.get("variables") or ([config["variable"]] if config.get("variable") else [])
    if not variables:
        raise QueryError("A duplicate check needs at least one variable.")
    columns = ", ".join(quote_ident(ctx.require(str(v)).name) for v in variables)
    sql = (
        f"SELECT COUNT(*) FROM (SELECT {columns}, COUNT(*) AS n "
        f"FROM read_parquet({_quote_path(ctx.parquet_path)}) GROUP BY {columns} "
        f"HAVING COUNT(*) > 1) t"
    )
    _, rows = run_sql(sql)
    duplicate_groups = int(rows[0][0]) if rows else 0

    detail_sql = (
        f"SELECT {columns}, COUNT(*) AS n FROM read_parquet({_quote_path(ctx.parquet_path)}) "
        f"GROUP BY {columns} HAVING COUNT(*) > 1 ORDER BY n DESC LIMIT 20"
    )
    detail_columns, detail_rows = run_sql(detail_sql)
    extra_rows = sum(int(r[-1]) - 1 for r in detail_rows)

    return CheckOutcome(
        passed=duplicate_groups == 0,
        failed_rows=extra_rows,
        total_rows=total,
        message=(
            f"{duplicate_groups:,} duplicated key combination(s) found on "
            f"{', '.join(str(v) for v in variables)}."
        ),
        details={
            "variables": variables,
            "duplicate_groups": duplicate_groups,
            "examples": {"columns": detail_columns, "rows": detail_rows},
        },
    )


def _check_outliers(ctx: DatasetContext, config: dict, total: int) -> CheckOutcome:
    variable = config.get("variable")
    info = ctx.require(str(variable))
    col = quote_ident(info.name)
    method = str(config.get("method", "iqr"))
    factor = float(config.get("factor", 1.5))

    if method == "zscore":
        stats_sql = (
            f"SELECT AVG({col}), STDDEV_SAMP({col}) "
            f"FROM read_parquet({_quote_path(ctx.parquet_path)})"
        )
        _, rows = run_sql(stats_sql)
        mean, std = (rows[0] if rows else (None, None))
        if mean is None or not std:
            return CheckOutcome(True, 0, total, "Not enough variation to detect outliers.", {})
        low, high = float(mean) - factor * float(std), float(mean) + factor * float(std)
    else:
        stats_sql = (
            f"SELECT QUANTILE_CONT({col}, 0.25), QUANTILE_CONT({col}, 0.75) "
            f"FROM read_parquet({_quote_path(ctx.parquet_path)})"
        )
        _, rows = run_sql(stats_sql)
        q1, q3 = (rows[0] if rows else (None, None))
        if q1 is None or q3 is None:
            return CheckOutcome(True, 0, total, "Not enough data to detect outliers.", {})
        iqr = float(q3) - float(q1)
        low, high = float(q1) - factor * iqr, float(q3) + factor * iqr

    failed = _count_where(
        ctx, f"{col} IS NOT NULL AND ({col} < ? OR {col} > ?)", [low, high]
    )
    return CheckOutcome(
        passed=True,
        failed_rows=failed,
        total_rows=total,
        message=(
            f"{failed:,} outlying values in {info.name} "
            f"(outside {low:,.2f} to {high:,.2f}, {method})."
        ),
        details={"variable": info.name, "lower_bound": low, "upper_bound": high, "method": method},
    )


def _check_consistency(ctx: DatasetContext, config: dict, total: int) -> CheckOutcome:
    """Flags rows where variable A holds but variable B does not.

    Example: 'age < 18' should imply 'marital_status is missing'.
    """
    left = config.get("variable")
    right = config.get("other_variable")
    operator = str(config.get("operator", "lte"))
    symbols = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "eq": "=", "ne": "!="}
    if operator not in symbols:
        raise QueryError(f"Unsupported consistency operator '{operator}'.")
    left_col = quote_ident(ctx.require(str(left)).name)
    right_col = quote_ident(ctx.require(str(right)).name)
    # Count rows where the expected relationship is violated
    where = (
        f"{left_col} IS NOT NULL AND {right_col} IS NOT NULL "
        f"AND NOT ({left_col} {symbols[operator]} {right_col})"
    )
    failed = _count_where(ctx, where)
    return CheckOutcome(
        passed=True,
        failed_rows=failed,
        total_rows=total,
        message=(
            f"{failed:,} rows violate the rule "
            f"{left} {symbols[operator]} {right}."
        ),
        details={"variable": left, "other_variable": right, "operator": operator},
    )


def _check_duration(ctx: DatasetContext, config: dict, total: int) -> CheckOutcome:
    """Interviews finished suspiciously fast are the classic fabrication signal."""
    variable = config.get("variable")
    info = ctx.require(str(variable))
    col = quote_ident(info.name)
    minimum = float(config.get("min_minutes", 10))
    maximum = config.get("max_minutes")
    clauses = [f"{col} < ?"]
    params: list[Any] = [minimum]
    if maximum is not None:
        clauses.append(f"{col} > ?")
        params.append(float(maximum))
    failed = _count_where(ctx, f"{col} IS NOT NULL AND (" + " OR ".join(clauses) + ")", params)
    return CheckOutcome(
        passed=True,
        failed_rows=failed,
        total_rows=total,
        message=(
            f"{failed:,} interviews are shorter than {minimum:g} minutes"
            + (f" or longer than {float(maximum):g} minutes." if maximum else ".")
        ),
        details={"variable": info.name, "min_minutes": minimum, "max_minutes": maximum},
    )


def _check_gps(ctx: DatasetContext, config: dict, total: int) -> CheckOutcome:
    latitude = config.get("latitude_variable")
    longitude = config.get("longitude_variable")
    lat_col = quote_ident(ctx.require(str(latitude)).name)
    lon_col = quote_ident(ctx.require(str(longitude)).name)
    failed = _count_where(
        ctx,
        f"{lat_col} IS NULL OR {lon_col} IS NULL OR ({lat_col} = 0 AND {lon_col} = 0)",
    )
    return CheckOutcome(
        passed=True,
        failed_rows=failed,
        total_rows=total,
        message=f"{failed:,} of {total:,} records have no usable GPS coordinates.",
        details={"latitude": latitude, "longitude": longitude},
    )


def _check_constant(ctx: DatasetContext, config: dict, total: int) -> CheckOutcome:
    """Detects interviewers who give the same answer to everyone."""
    variable = config.get("variable")
    group_by = config.get("group_variable")
    col = quote_ident(ctx.require(str(variable)).name)
    if not group_by:
        sql = (
            f"SELECT COUNT(DISTINCT {col}) FROM read_parquet({_quote_path(ctx.parquet_path)})"
        )
        _, rows = run_sql(sql)
        distinct = int(rows[0][0]) if rows else 0
        return CheckOutcome(
            passed=distinct > 1,
            failed_rows=0 if distinct > 1 else total,
            total_rows=total,
            message=f"{variable} has {distinct} distinct value(s) across the dataset.",
            details={"variable": variable, "distinct": distinct},
        )

    group_col = quote_ident(ctx.require(str(group_by)).name)
    min_records = int(config.get("min_records", 5))
    sql = (
        f"SELECT {group_col}, COUNT(*) AS n, COUNT(DISTINCT {col}) AS distinct_values "
        f"FROM read_parquet({_quote_path(ctx.parquet_path)}) "
        f"WHERE {group_col} IS NOT NULL GROUP BY 1 HAVING COUNT(*) >= {min_records} "
        f"AND COUNT(DISTINCT {col}) = 1 ORDER BY n DESC LIMIT 50"
    )
    columns, rows = run_sql(sql)
    affected = sum(int(r[1]) for r in rows)
    return CheckOutcome(
        passed=len(rows) == 0,
        failed_rows=affected,
        total_rows=total,
        message=(
            f"{len(rows)} group(s) of {group_by} recorded a single constant value for "
            f"{variable} across all their interviews."
        ),
        details={
            "variable": variable,
            "group_variable": group_by,
            "groups": {"columns": columns, "rows": rows},
        },
    )


def execute_rule(db: Session, rule: QualityRule) -> QualityResult:
    dataset = db.get(Dataset, rule.dataset_id)
    now = utcnow()
    if dataset is None or not dataset_is_queryable(dataset):
        result = QualityResult(
            rule_id=rule.id,
            run_at=now,
            passed=False,
            message="Dataset is not available for checking.",
        )
        db.add(result)
        db.flush()
        return result

    ctx = DatasetContext.from_model(dataset)
    try:
        outcome = run_check(ctx, rule)
        passed = outcome.passed and outcome.failure_rate <= (rule.threshold or 0.0)
        result = QualityResult(
            rule_id=rule.id,
            run_at=now,
            passed=passed,
            failed_rows=outcome.failed_rows,
            total_rows=outcome.total_rows,
            failure_rate=round(outcome.failure_rate, 6),
            details=outcome.details,
            message=outcome.message,
        )
    except (QueryError, KeyError, ValueError) as exc:
        result = QualityResult(
            rule_id=rule.id,
            run_at=now,
            passed=False,
            message=f"Check could not run: {exc}",
        )
    db.add(result)
    db.flush()
    return result


def suggested_rules(dataset: Dataset) -> list[dict[str, Any]]:
    """Propose sensible checks based on what the dataset looks like.

    Saves a supervisor from configuring a dozen rules by hand on day one.
    """
    fields = (dataset.meta or {}).get("monitoring_fields", {})
    suggestions: list[dict[str, Any]] = []

    if fields.get("interview_key"):
        suggestions.append(
            {
                "name": "Duplicate interview keys",
                "check_type": CheckType.duplicates.value,
                "config": {"variables": [fields["interview_key"]]},
                "severity": "critical",
                "threshold": 0.0,
                "rationale": "Every interview key should appear exactly once.",
            }
        )
    if fields.get("duration"):
        suggestions.append(
            {
                "name": "Unusually short interviews",
                "check_type": CheckType.interview_duration.value,
                "config": {"variable": fields["duration"], "min_minutes": 10},
                "severity": "warning",
                "threshold": 0.05,
                "rationale": "Very fast interviews can indicate rushed or fabricated data.",
            }
        )
    if fields.get("latitude") and fields.get("longitude"):
        suggestions.append(
            {
                "name": "Missing GPS coordinates",
                "check_type": CheckType.gps_missing.value,
                "config": {
                    "latitude_variable": fields["latitude"],
                    "longitude_variable": fields["longitude"],
                },
                "severity": "warning",
                "threshold": 0.02,
                "rationale": "Location is needed to verify visits took place.",
            }
        )

    # Flag any variable that is missing for more than a fifth of records
    for variable in dataset.variables[:200]:
        if dataset.row_count and variable.n_missing / dataset.row_count > 0.2:
            suggestions.append(
                {
                    "name": f"High missingness: {variable.name}",
                    "check_type": CheckType.missing_rate.value,
                    "config": {"variable": variable.name},
                    "severity": "info",
                    "threshold": 0.2,
                    "rationale": (
                        f"{variable.n_missing:,} of {dataset.row_count:,} records are "
                        "missing this value."
                    ),
                }
            )
        if len(suggestions) >= 12:
            break
    return suggestions
