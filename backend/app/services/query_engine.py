"""Compiles QuerySpec objects into DuckDB SQL and runs them over Parquet files.

Safety model: every identifier that reaches the SQL string is first checked
against the dataset's registered variable names, so a caller can never inject a
column expression. Literal values are always bound as parameters.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import duckdb

from app.core.logging import get_logger
from app.schemas.query import (
    Aggregation,
    Condition,
    CrosstabRequest,
    CrosstabResult,
    Dimension,
    FilterGroup,
    FilterOperator,
    FrequencyResult,
    FrequencyRow,
    Measure,
    QueryColumn,
    QueryResult,
    QuerySpec,
    SummaryStats,
)

logger = get_logger(__name__)

MAX_ROWS = 100_000
OTHER_LABEL = "Other"
# System missing. Stata's tagged missings (.a to .z) keep their own tag and are
# reported as separate categories beside this one.
MISSING_LABEL = "(blank)"
# Companion column written by the ingest step; see ingest.MISSING_TAG_SUFFIX.
MISSING_TAG_SUFFIX = "__mv"


class QueryError(ValueError):
    """Raised for specs that reference unknown variables or invalid options."""


@dataclass
class VariableInfo:
    name: str
    label: str = ""
    var_type: str = "text"
    value_labels: dict[str, str] = field(default_factory=dict)
    # Stata tagged missings present on this variable, e.g. [".a", ".b"]
    missing_tags: list[str] = field(default_factory=list)

    @property
    def is_numeric(self) -> bool:
        return self.var_type in ("numeric", "boolean")

    @property
    def is_datetime(self) -> bool:
        return self.var_type == "datetime"


@dataclass
class DatasetContext:
    """Everything the engine needs to query one dataset."""

    dataset_id: str
    parquet_path: str
    variables: dict[str, VariableInfo]

    @classmethod
    def from_model(cls, dataset: Any) -> DatasetContext:
        variables = {
            v.name: VariableInfo(
                name=v.name,
                label=v.label or "",
                var_type=getattr(v.var_type, "value", str(v.var_type)),
                value_labels=v.value_labels or {},
                missing_tags=list(v.missing_tags or []),
            )
            for v in dataset.variables
        }
        return cls(
            dataset_id=dataset.id,
            parquet_path=dataset.storage_path,
            variables=variables,
        )

    def require(self, name: str) -> VariableInfo:
        info = self.variables.get(name)
        if info is None:
            raise QueryError(f"Unknown variable '{name}' in this dataset")
        return info


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_path(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


class SQLBuilder:
    """Turns a spec into (sql, params)."""

    def __init__(self, ctx: DatasetContext):
        self.ctx = ctx
        self.params: list[Any] = []

    # -- column expressions ------------------------------------------------
    def dimension_expr(self, dim: Dimension) -> str:
        info = self.ctx.require(dim.variable)
        col = quote_ident(info.name)
        if dim.grain:
            source = col if info.is_datetime else f"try_cast({col} AS TIMESTAMP)"
            return f"date_trunc('{dim.grain.value}', {source})"
        if dim.bin_width:
            if not info.is_numeric:
                raise QueryError(f"'{dim.variable}' is not numeric, cannot be binned")
            width = float(dim.bin_width)
            if width <= 0:
                raise QueryError("bin_width must be greater than zero")
            return f"floor({col} / {width}) * {width}"
        if info.missing_tags and f"{info.name}{MISSING_TAG_SUFFIX}" in self.ctx.variables:
            # Grouping collapses every kind of missing into one null. Reading the
            # companion column keeps ".a" apart from a plain blank, which is the
            # difference between "asked and refused" and "never asked".
            tag_col = quote_ident(f"{info.name}{MISSING_TAG_SUFFIX}")
            # Stata only tags missings on numeric variables, so the stored column
            # is numeric here whatever its semantic type. A whole number must
            # render as "1", not "1.0": value label keys are written that way,
            # and a coded variable would otherwise lose every label it had.
            as_text = (
                f"CASE WHEN {col} = floor({col}) "
                f"THEN CAST(CAST({col} AS BIGINT) AS VARCHAR) "
                f"ELSE CAST({col} AS VARCHAR) END"
            )
            return (
                f"CASE WHEN {col} IS NOT NULL THEN {as_text} "
                f"ELSE COALESCE({tag_col}, '{MISSING_LABEL}') END"
            )
        return col

    def measure_expr(self, measure: Measure) -> str:
        agg = measure.agg
        weight_col = None
        if measure.weight:
            weight_info = self.ctx.require(measure.weight)
            if not weight_info.is_numeric:
                raise QueryError(f"Weight '{measure.weight}' must be a numeric variable")
            weight_col = quote_ident(weight_info.name)

        if agg in (Aggregation.count, Aggregation.share):
            if weight_col:
                return f"COALESCE(SUM({weight_col}), 0)"
            if measure.variable:
                col = quote_ident(self.ctx.require(measure.variable).name)
                return f"COUNT({col})"
            return "COUNT(*)"

        info = self.ctx.require(measure.variable or "")
        col = quote_ident(info.name)
        if agg == Aggregation.count_distinct:
            return f"COUNT(DISTINCT {col})"

        if not info.is_numeric:
            # Allow aggregating numeric-looking text columns rather than failing
            col = f"try_cast({col} AS DOUBLE)"

        if agg == Aggregation.sum:
            return f"SUM({col} * {weight_col})" if weight_col else f"SUM({col})"
        if agg == Aggregation.mean:
            if weight_col:
                return (
                    f"SUM({col} * {weight_col}) / NULLIF(SUM(CASE WHEN {col} IS NULL "
                    f"THEN 0 ELSE {weight_col} END), 0)"
                )
            return f"AVG({col})"
        if agg == Aggregation.median:
            return f"MEDIAN({col})"
        if agg == Aggregation.min:
            return f"MIN({col})"
        if agg == Aggregation.max:
            return f"MAX({col})"
        if agg == Aggregation.stddev:
            return f"STDDEV_SAMP({col})"
        if agg in (Aggregation.p25, Aggregation.p75, Aggregation.p90):
            q = {"p25": 0.25, "p75": 0.75, "p90": 0.90}[agg.value]
            return f"QUANTILE_CONT({col}, {q})"
        raise QueryError(f"Unsupported aggregation '{agg}'")

    # -- filters -----------------------------------------------------------
    def filter_sql(self, group: FilterGroup) -> str:
        if group.is_empty():
            return ""
        parts: list[str] = []
        for condition in group.conditions:
            sql = self._condition_sql(condition)
            if sql:
                parts.append(sql)
        for nested in group.groups:
            sql = self.filter_sql(nested)
            if sql:
                parts.append(f"({sql})")
        if not parts:
            return ""
        joiner = " AND " if group.op == "and" else " OR "
        return joiner.join(parts)

    def _condition_sql(self, condition: Condition) -> str:
        info = self.ctx.require(condition.variable)
        col = quote_ident(info.name)
        op = condition.operator
        value = condition.value

        if condition.use_label and info.value_labels:
            # Translate labels back to the stored codes before filtering
            reverse = {str(v): k for k, v in info.value_labels.items()}
            if isinstance(value, list):
                value = [reverse.get(str(v), v) for v in value]
            else:
                value = reverse.get(str(value), value)

        if op == FilterOperator.is_null:
            return f"{col} IS NULL"
        if op == FilterOperator.is_not_null:
            return f"{col} IS NOT NULL"

        if op in (FilterOperator.in_, FilterOperator.not_in):
            values = value if isinstance(value, list) else [value]
            if not values:
                return ""
            placeholders = ", ".join("?" for _ in values)
            self.params.extend(self._coerce(info, v) for v in values)
            negate = "NOT " if op == FilterOperator.not_in else ""
            return f"{col} {negate}IN ({placeholders})"

        if op == FilterOperator.between:
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise QueryError("'between' expects a two element list")
            self.params.extend([self._coerce(info, value[0]), self._coerce(info, value[1])])
            return f"{col} BETWEEN ? AND ?"

        if op in (
            FilterOperator.contains,
            FilterOperator.not_contains,
            FilterOperator.starts_with,
            FilterOperator.ends_with,
        ):
            text = str(value or "").replace("%", r"\%").replace("_", r"\_")
            pattern = {
                FilterOperator.contains: f"%{text}%",
                FilterOperator.not_contains: f"%{text}%",
                FilterOperator.starts_with: f"{text}%",
                FilterOperator.ends_with: f"%{text}",
            }[op]
            self.params.append(pattern)
            negate = "NOT " if op == FilterOperator.not_contains else ""
            return f"CAST({col} AS VARCHAR) {negate}ILIKE ? ESCAPE '\\'"

        comparison = {
            FilterOperator.eq: "=",
            FilterOperator.ne: "!=",
            FilterOperator.gt: ">",
            FilterOperator.gte: ">=",
            FilterOperator.lt: "<",
            FilterOperator.lte: "<=",
        }[op]
        self.params.append(self._coerce(info, value))
        if op == FilterOperator.ne:
            # Keep NULLs out of "not equal" results the way analysts expect
            return f"({col} IS NULL OR {col} != ?)"
        return f"{col} {comparison} ?"

    @staticmethod
    def _coerce(info: VariableInfo, value: Any) -> Any:
        if value is None or not info.is_numeric:
            return value
        if isinstance(value, bool):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            return value

    # -- full statements ---------------------------------------------------
    def build_aggregate(self, spec: QuerySpec) -> tuple[str, list[Any]]:
        self.params = []
        select_parts: list[str] = []
        group_parts: list[str] = []

        for index, dim in enumerate(spec.dimensions, start=1):
            expr = self.dimension_expr(dim)
            select_parts.append(f"{expr} AS {quote_ident(dim.output_name)}")
            group_parts.append(str(index))

        for measure in spec.measures:
            select_parts.append(
                f"{self.measure_expr(measure)} AS {quote_ident(measure.output_name)}"
            )

        source = f"read_parquet({_quote_path(self.ctx.parquet_path)})"
        sql = f"SELECT {', '.join(select_parts)} FROM {source}"

        where = self.filter_sql(spec.filters)
        conditions = [where] if where else []
        if spec.drop_missing:
            for dim in spec.dimensions:
                conditions.append(f"{quote_ident(dim.variable)} IS NOT NULL")
        if conditions:
            sql += " WHERE " + " AND ".join(f"({c})" for c in conditions)

        if group_parts:
            sql += " GROUP BY " + ", ".join(group_parts)

        sql += self._order_by(spec)
        sql += f" LIMIT {min(spec.limit, MAX_ROWS)}"
        if spec.offset:
            sql += f" OFFSET {spec.offset}"
        return sql, list(self.params)

    def _order_by(self, spec: QuerySpec) -> str:
        output_names = {d.output_name for d in spec.dimensions} | {
            m.output_name for m in spec.measures
        }
        clauses: list[str] = []
        for item in spec.sort:
            if item.field not in output_names:
                raise QueryError(f"Cannot sort by unknown field '{item.field}'")
            direction = "DESC" if item.direction == "desc" else "ASC"
            clauses.append(f"{quote_ident(item.field)} {direction} NULLS LAST")
        if not clauses and spec.dimensions and spec.measures:
            # Sensible default: biggest groups first
            clauses.append(f"{quote_ident(spec.measures[0].output_name)} DESC NULLS LAST")
        return " ORDER BY " + ", ".join(clauses) if clauses else ""

    def build_rows(
        self,
        columns: list[str] | None,
        filters: FilterGroup,
        limit: int,
        offset: int,
        sort: list[tuple[str, str]] | None = None,
    ) -> tuple[str, list[Any]]:
        """Raw row listing used by the data preview."""
        self.params = []
        if columns:
            selected = ", ".join(quote_ident(self.ctx.require(c).name) for c in columns)
        else:
            selected = "*"
        sql = f"SELECT {selected} FROM read_parquet({_quote_path(self.ctx.parquet_path)})"
        where = self.filter_sql(filters)
        if where:
            sql += f" WHERE {where}"
        if sort:
            clauses = []
            for name, direction in sort:
                col = quote_ident(self.ctx.require(name).name)
                clauses.append(f"{col} {'DESC' if direction == 'desc' else 'ASC'} NULLS LAST")
            sql += " ORDER BY " + ", ".join(clauses)
        sql += f" LIMIT {min(limit, MAX_ROWS)} OFFSET {max(offset, 0)}"
        return sql, list(self.params)

    def build_count(self, filters: FilterGroup) -> tuple[str, list[Any]]:
        self.params = []
        sql = f"SELECT COUNT(*) FROM read_parquet({_quote_path(self.ctx.parquet_path)})"
        where = self.filter_sql(filters)
        if where:
            sql += f" WHERE {where}"
        return sql, list(self.params)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    con.execute("SET threads TO 4")
    con.execute("SET memory_limit = '2GB'")
    return con


def run_sql(sql: str, params: list[Any] | None = None) -> tuple[list[str], list[list[Any]]]:
    con = _connect()
    try:
        cursor = con.execute(sql, params or [])
        columns = [d[0] for d in cursor.description or []]
        rows = [list(row) for row in cursor.fetchall()]
        return columns, rows
    except duckdb.Error as exc:
        logger.warning("DuckDB query failed: %s | sql=%s", exc, sql)
        raise QueryError(f"Query failed: {exc}") from exc
    finally:
        con.close()


def _is_missing(info: VariableInfo, value: Any) -> bool:
    """True for a null, a blank, or one of Stata's tagged missings."""
    if value is None:
        return True
    text = str(value)
    return text == MISSING_LABEL or text in info.missing_tags


def _label_value(info: VariableInfo, value: Any) -> Any:
    if value is None:
        return None
    if not info.value_labels:
        return value
    key = value
    if isinstance(value, float) and value.is_integer():
        key = int(value)
    return info.value_labels.get(str(key), value)


def execute_query(ctx: DatasetContext, spec: QuerySpec) -> QueryResult:
    """Run an aggregate query and post-process labels, shares and top-N."""
    started = time.perf_counter()
    builder = SQLBuilder(ctx)
    sql, params = builder.build_aggregate(spec)
    column_names, rows = run_sql(sql, params)

    dim_names = [d.output_name for d in spec.dimensions]

    # Replace codes with labels
    if spec.use_labels:
        for dim in spec.dimensions:
            if dim.grain or dim.bin_width:
                continue
            info = ctx.variables.get(dim.variable)
            if not info or not info.value_labels:
                continue
            index = column_names.index(dim.output_name)
            for row in rows:
                row[index] = _label_value(info, row[index])

    # share measures are computed against the grand total of the result set
    for measure in spec.measures:
        if measure.agg != Aggregation.share:
            continue
        index = column_names.index(measure.output_name)
        total = sum(float(r[index] or 0) for r in rows)
        for row in rows:
            row[index] = round(float(row[index] or 0) / total * 100, 4) if total else None

    # Top-N collapsing for a single dimension
    if len(spec.dimensions) == 1 and spec.dimensions[0].limit and spec.measures:
        rows = _collapse_top_n(rows, column_names, spec)

    columns = [
        QueryColumn(
            name=name,
            label=_column_label(ctx, spec, name),
            type="dimension" if name in dim_names else "measure",
            data_type=_column_data_type(ctx, spec, name),
        )
        for name in column_names
    ]
    duration = int((time.perf_counter() - started) * 1000)
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=len(rows) >= min(spec.limit, MAX_ROWS),
        sql=sql,
        duration_ms=duration,
    )


def _collapse_top_n(
    rows: list[list[Any]], column_names: list[str], spec: QuerySpec
) -> list[list[Any]]:
    keep = spec.dimensions[0].limit or len(rows)
    if len(rows) <= keep:
        return rows
    measure_indexes = [
        column_names.index(m.output_name)
        for m in spec.measures
        if m.agg in (Aggregation.count, Aggregation.sum, Aggregation.share)
    ]
    head, tail = rows[:keep], rows[keep:]
    if not tail:
        return head
    other = [None] * len(column_names)
    other[column_names.index(spec.dimensions[0].output_name)] = OTHER_LABEL
    for index in measure_indexes:
        other[index] = sum(float(r[index] or 0) for r in tail)
    return head + [other]


def _column_label(ctx: DatasetContext, spec: QuerySpec, name: str) -> str:
    for dim in spec.dimensions:
        if dim.output_name == name:
            info = ctx.variables.get(dim.variable)
            return info.label if info and info.label else dim.variable
    for measure in spec.measures:
        if measure.output_name == name:
            if measure.variable:
                info = ctx.variables.get(measure.variable)
                base = info.label if info and info.label else measure.variable
                return f"{measure.agg.value.replace('_', ' ').title()} of {base}"
            return measure.agg.value.title()
    return name


def _column_data_type(ctx: DatasetContext, spec: QuerySpec, name: str) -> str:
    for dim in spec.dimensions:
        if dim.output_name == name:
            if dim.grain:
                return "datetime"
            info = ctx.variables.get(dim.variable)
            return info.var_type if info else "text"
    return "number"


def execute_frequency(
    ctx: DatasetContext,
    variable: str,
    filters: FilterGroup | None = None,
    limit: int = 200,
    use_labels: bool = True,
) -> FrequencyResult:
    """One-way frequency table with valid and cumulative percentages."""
    info = ctx.require(variable)
    spec = QuerySpec(
        dimensions=[Dimension(variable=variable, alias="value")],
        measures=[Measure(agg=Aggregation.count, alias="count")],
        filters=filters or FilterGroup(),
        limit=limit,
        use_labels=False,
        sort=[],
    )
    builder = SQLBuilder(ctx)
    sql, params = builder.build_aggregate(spec)
    _, rows = run_sql(sql, params)

    total = sum(int(r[1] or 0) for r in rows)
    missing = sum(int(r[1] or 0) for r in rows if _is_missing(info, r[0]))
    valid_total = total - missing

    # Real answers first, then blanks and tagged missings. Numeric-looking values
    # sort by value, everything else by frequency.
    def sort_key(row: list[Any]) -> Any:
        blank = _is_missing(info, row[0])
        try:
            natural = float(row[0]) if row[0] is not None else 0.0
        except (TypeError, ValueError):
            natural = None
        if blank:
            # "(blank)" first, then .a, .b, ... rather than by count
            return (True, 0.0, str(row[0]))
        if natural is not None and info.is_numeric:
            return (False, natural, "")
        return (False, float(-int(row[1] or 0)), "")

    try:
        rows.sort(key=sort_key)
    except TypeError:
        rows.sort(key=lambda r: (_is_missing(info, r[0]), str(r[0])))

    result_rows: list[FrequencyRow] = []
    cumulative = 0.0
    for value, count in rows:
        count = int(count or 0)
        blank = _is_missing(info, value)
        percent = (count / total * 100) if total else 0.0
        valid_percent = (count / valid_total * 100) if valid_total and not blank else 0.0
        if not blank:
            cumulative += valid_percent
        if value is None:
            label = MISSING_LABEL
        elif blank:
            # A tag such as ".a" is its own answer category; show it as it is
            label = str(value)
        else:
            label = str(_label_value(info, value) if use_labels else value)
        result_rows.append(
            FrequencyRow(
                value=value,
                label=label,
                count=count,
                percent=round(percent, 3),
                valid_percent=round(valid_percent, 3),
                cumulative_percent=round(min(cumulative, 100.0), 3),
            )
        )

    return FrequencyResult(
        variable=variable,
        label=info.label or variable,
        rows=result_rows,
        total=total,
        missing=missing,
        distinct=len([r for r in rows if not _is_missing(info, r[0])]),
    )


def execute_crosstab(ctx: DatasetContext, request: CrosstabRequest) -> CrosstabResult:
    """Two-way table with optional row/column/total percentages and chi-square."""
    row_info = ctx.require(request.row_variable)
    col_info = ctx.require(request.column_variable)

    spec = QuerySpec(
        dimensions=[
            Dimension(variable=request.row_variable, alias="__row"),
            Dimension(variable=request.column_variable, alias="__col"),
        ],
        measures=[Measure(**{**request.measure.model_dump(), "alias": "__value"})],
        filters=request.filters,
        limit=MAX_ROWS,
        use_labels=False,
        sort=[],
    )
    builder = SQLBuilder(ctx)
    sql, params = builder.build_aggregate(spec)
    _, raw = run_sql(sql, params)

    def cell_label(info: Any, value: Any) -> str:
        if value is None:
            return MISSING_LABEL
        return str(_label_value(info, value) if request.use_labels else value)

    row_keys: list[Any] = []
    col_keys: list[Any] = []
    table: dict[tuple[Any, Any], float] = {}
    for row_value, col_value, value in raw:
        if row_value not in row_keys:
            row_keys.append(row_value)
        if col_value not in col_keys:
            col_keys.append(col_value)
        table[(row_value, col_value)] = float(value or 0)

    row_keys = _sorted_keys(row_keys, row_info)[: request.max_categories]
    col_keys = _sorted_keys(col_keys, col_info)[: request.max_categories]

    values = [[table.get((r, c)) for c in col_keys] for r in row_keys]
    row_totals = [sum(v or 0 for v in row) for row in values]
    column_totals = [
        sum((values[i][j] or 0) for i in range(len(row_keys))) for j in range(len(col_keys))
    ]
    grand_total = sum(row_totals)

    chi_square = _chi_square(values, row_totals, column_totals, grand_total)

    if request.percentages != "none" and grand_total:
        percent_values: list[list[float | None]] = []
        for i, row in enumerate(values):
            new_row: list[float | None] = []
            for j, value in enumerate(row):
                if value is None:
                    new_row.append(None)
                    continue
                base = {
                    "row": row_totals[i],
                    "column": column_totals[j],
                    "total": grand_total,
                }[request.percentages]
                new_row.append(round(value / base * 100, 2) if base else None)
            percent_values.append(new_row)
        values = percent_values

    return CrosstabResult(
        row_variable=request.row_variable,
        column_variable=request.column_variable,
        row_labels=[cell_label(row_info, k) for k in row_keys],
        column_labels=[cell_label(col_info, k) for k in col_keys],
        values=values,
        row_totals=row_totals,
        column_totals=column_totals,
        grand_total=grand_total,
        percentages=request.percentages,
        chi_square=chi_square,
    )


def _sorted_keys(keys: list[Any], info: VariableInfo) -> list[Any]:
    non_null = [k for k in keys if k is not None]
    try:
        non_null.sort()
    except TypeError:
        non_null.sort(key=str)
    return non_null + ([None] if None in keys else [])


def _chi_square(
    values: list[list[float | None]],
    row_totals: list[float],
    column_totals: list[float],
    grand_total: float,
) -> dict[str, Any] | None:
    """Pearson chi-square of independence; useful for quick significance checks."""
    if grand_total <= 0 or len(row_totals) < 2 or len(column_totals) < 2:
        return None
    statistic = 0.0
    for i, row_total in enumerate(row_totals):
        for j, col_total in enumerate(column_totals):
            expected = row_total * col_total / grand_total
            if expected <= 0:
                continue
            observed = values[i][j] or 0
            statistic += (observed - expected) ** 2 / expected
    dof = (len(row_totals) - 1) * (len(column_totals) - 1)
    return {
        "statistic": round(statistic, 4),
        "dof": dof,
        "cramers_v": round(
            math.sqrt(statistic / (grand_total * min(len(row_totals), len(column_totals) - 1)))
            if grand_total and min(len(row_totals), len(column_totals)) > 1
            else 0.0,
            4,
        ),
    }


def execute_summary(
    ctx: DatasetContext, variables: list[str], filters: FilterGroup | None = None
) -> list[SummaryStats]:
    """Descriptive statistics for numeric variables."""
    results: list[SummaryStats] = []
    builder = SQLBuilder(ctx)
    where = builder.filter_sql(filters or FilterGroup())
    params = list(builder.params)
    for name in variables:
        info = ctx.require(name)
        col = quote_ident(info.name)
        cast = col if info.is_numeric else f"try_cast({col} AS DOUBLE)"
        sql = (
            f"SELECT COUNT({cast}), COUNT(*) - COUNT({cast}), AVG({cast}), "
            f"STDDEV_SAMP({cast}), MIN({cast}), QUANTILE_CONT({cast}, 0.25), "
            f"MEDIAN({cast}), QUANTILE_CONT({cast}, 0.75), MAX({cast}), SUM({cast}) "
            f"FROM read_parquet({_quote_path(ctx.parquet_path)})"
        )
        if where:
            sql += f" WHERE {where}"
        _, rows = run_sql(sql, params)
        row = rows[0] if rows else [0] * 10

        def num(value: Any) -> float | None:
            if value is None:
                return None
            try:
                out = float(value)
            except (TypeError, ValueError):
                return None
            return None if math.isnan(out) or math.isinf(out) else round(out, 6)

        results.append(
            SummaryStats(
                variable=name,
                label=info.label or name,
                count=int(row[0] or 0),
                missing=int(row[1] or 0),
                mean=num(row[2]),
                std=num(row[3]),
                min=num(row[4]),
                p25=num(row[5]),
                median=num(row[6]),
                p75=num(row[7]),
                max=num(row[8]),
                sum=num(row[9]),
            )
        )
    return results


def distinct_values(ctx: DatasetContext, variable: str, limit: int = 500) -> list[Any]:
    """Populate filter dropdowns in the UI."""
    info = ctx.require(variable)
    col = quote_ident(info.name)
    sql = (
        f"SELECT {col}, COUNT(*) AS n FROM read_parquet({_quote_path(ctx.parquet_path)}) "
        f"WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT {int(limit)}"
    )
    _, rows = run_sql(sql)
    return [
        {"value": value, "label": str(_label_value(info, value)), "count": int(count or 0)}
        for value, count in rows
    ]
