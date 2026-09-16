"""Compiles QuerySpec objects into DuckDB SQL and runs them over Parquet files.

Safety model: every identifier that reaches the SQL string is first checked
against the dataset's registered variable names, so a caller can never inject a
column expression. Literal values are always bound as parameters.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import duckdb

from app.core.config import settings
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
    # How the column is stored, as the ingest that wrote it named the type.
    # Two vocabularies reach this, because two ingest paths write it: a pandas
    # dtype ("float64", "object") for a file read whole, and a DuckDB type
    # ("DOUBLE", "VARCHAR") for one read through Parquet.
    storage_type: str = ""

    @property
    def is_numeric(self) -> bool:
        """Whether this behaves as a quantity: what to measure, how to summarise.

        An analytical judgement, not a fact about the file. A column of whole
        numbers carrying value labels is stored as a number and read as a code
        set, and this says code set.
        """
        return self.var_type in ("numeric", "boolean")

    @property
    def number_kind(self) -> str:
        """Which family of number the stored column is: integer, decimal, float.

        Empty for a column that holds something else. The distinction matters
        because a filter value is bound as a Python object and the binding has
        to be exact: an integer wider than 2**53 or a decimal with more digits
        than a double can carry comes back changed if it goes through `float`,
        and then matches the wrong rows rather than failing.
        """
        kind = self.storage_type.lower()
        if not kind:
            # Written by an ingest old enough not to have recorded it. The
            # analytical type is the best that is left, which is what this
            # decision used on its own before.
            return "float" if self.is_numeric else ""
        if "datetime" in kind or "timestamp" in kind or "date" in kind:
            return ""
        if "int" in kind:
            return "integer"
        if "decimal" in kind or "numeric" in kind:
            return "decimal"
        if "float" in kind or "double" in kind or "real" in kind:
            return "float"
        return ""

    @property
    def holds_numbers(self) -> bool:
        """Whether the stored column is a number, whatever kind of variable it is.

        The other question entirely, and the one a filter has to ask. A value
        compared against a DOUBLE column has to be bound as a number; bound as
        text, DuckDB refuses the comparison outright rather than guessing which
        side to convert, and the whole query fails.
        """
        return bool(self.number_kind)

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
                storage_type=str(getattr(v, "storage_type", "") or ""),
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
            if agg not in (Aggregation.count, Aggregation.share, Aggregation.sum, Aggregation.mean):
                raise QueryError(f"Survey weights are not supported for {agg.value}")
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
        """A filter value in the type the stored column will compare against.

        Decided by what the column holds rather than by what kind of variable
        it is. Those are different questions, and asking the second one here is
        what made "age over 15" fail on a census: age is stored as a number and
        classified as a code set, because it carries labels for "don't know"
        and "refused" - so the 15 stayed a string and DuckDB refused to compare
        it with a DOUBLE.

        A column that genuinely holds text is left alone, which is the other
        half of the same rule: an identifier stored as "007" has to go on
        matching "007" rather than becoming 7.

        The number is read exactly and bound in its own family. Going through
        `float` would be enough for most survey data and wrong for the rest: a
        household id past 2**53 and a decimal carrying more digits than a
        double holds both come back as a near neighbour, and a near neighbour
        does not fail - it quietly matches the wrong rows.
        """
        kind = info.number_kind
        if value is None or not kind or isinstance(value, bool):
            return value
        try:
            exact = Decimal(str(value))
        except (TypeError, ValueError, ArithmeticError):
            # Not a number at all. Bound as it came, so the filter either does
            # something sensible or says so, rather than turning into a 0.
            return value
        if not exact.is_finite():
            # NaN and the infinities have no exact form to preserve.
            return float(exact)
        if kind == "integer":
            # "2.5" against a column of whole numbers is still a real
            # comparison; it is only the whole ones that must stay whole.
            return int(exact) if exact == exact.to_integral_value() else exact
        if kind == "decimal":
            return exact
        return float(exact)

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
            first = spec.dimensions[0]
            if self._reads_as_a_scale(first):
                # A date or a numeric band only means anything in its own order.
                # Sorting those by size draws a line that says fieldwork is
                # collapsing when it is really just the busiest days first.
                clauses.append(f"{quote_ident(first.output_name)} ASC NULLS LAST")
            else:
                # Sensible default: biggest groups first
                clauses.append(f"{quote_ident(spec.measures[0].output_name)} DESC NULLS LAST")
        return " ORDER BY " + ", ".join(clauses) if clauses else ""

    def _reads_as_a_scale(self, dim: Dimension) -> bool:
        """True when the axis runs along a scale rather than across categories."""
        if dim.limit:
            # An explicit "keep the N largest" asks for the ranking, and the
            # collapse into "Other" reads the rows in that order.
            return False
        if dim.grain or dim.bin_width:
            return True
        info = self.ctx.variables.get(dim.variable)
        return bool(info and info.is_datetime)

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


# The single axis a one-way table gets in place of the variable it does not
# have. It is a sentinel rather than a real value, so it can never collide with
# a category that happens to be called "Count".
_ONE_WAY = object()


def _measure_label(measure: Measure) -> str:
    """What to call the one column of a one-way table.

    A weighted count is not a count. It is an estimate of how many there are
    in the population the sample stands for, and heading it "Count" invites a
    reader to add it to an unweighted one or quote it as a number of
    interviews.
    """
    if measure.agg == Aggregation.count:
        return f"Estimated total ({measure.weight})" if measure.weight else "Count"
    base = (
        f"{measure.agg.value} of {measure.variable}"
        if measure.variable
        else measure.agg.value
    )
    return f"weighted {base}" if measure.weight else base


def _suppression_mask(
    frequencies: list[list[float]], threshold: int
) -> list[list[bool]]:
    """Which cells must be withheld, given how many records each rests on.

    Primary suppression is the rule itself: a cell resting on fewer records
    than the floor can identify them. A zero is left alone - an absence
    identifies nobody, and blanking it would only tell the reader that
    somebody is being protected where nobody is.

    Secondary suppression is the part that is easy to forget and fatal to
    skip. A row whose only withheld cell sits beside published cells and a
    published total gives that cell back by subtraction, so the withholding
    was decorative. Where that is the case a second cell goes too, and the
    smallest one is chosen because it is the one whose loss costs the reader
    least. Columns are read the same way, which is also what protects a
    one-way table: its single column is the only direction a reader can
    subtract along.

    Iterating rather than solving: choosing the cheapest possible set of
    secondary cells is a hard problem, and the greedy pass is what statistical
    offices actually use. It terminates because every round withholds at least
    one more cell, and it stops early if a line has nothing left to give.
    """
    rows = len(frequencies)
    columns = len(frequencies[0]) if rows else 0
    mask = [
        [1 <= frequencies[i][j] < threshold for j in range(columns)] for i in range(rows)
    ]
    if rows == 0 or columns == 0:
        return mask

    def protect(line: list[tuple[int, int]]) -> bool:
        """One row or column. True if this pass withheld another cell."""
        hidden = [(i, j) for i, j in line if mask[i][j]]
        if len(hidden) != 1 or len(line) < 2:
            # Nothing withheld, or two already withheld and neither can be
            # recovered. A line of one cell has no second cell to subtract
            # from and is handled by the other direction.
            return False
        candidates = [(i, j) for i, j in line if not mask[i][j]]
        if not candidates:
            return False
        i, j = min(candidates, key=lambda cell: frequencies[cell[0]][cell[1]])
        mask[i][j] = True
        return True

    # Bounded by the number of cells: each round withholds at least one more.
    for _ in range(rows * columns + 1):
        moved = False
        for i in range(rows):
            moved |= protect([(i, j) for j in range(columns)])
        for j in range(columns):
            moved |= protect([(i, j) for i in range(rows)])
        if not moved:
            break
    return mask


def execute_crosstab(ctx: DatasetContext, request: CrosstabRequest) -> CrosstabResult:
    """A table of one or two variables.

    With both a row and a column variable this is the two-way cross-tabulation
    it has always been, percentages and chi-square included. With only one it
    is that variable's frequencies, which is what "tabulate this" means before
    anybody wants it crossed with something - and which used to require picking
    a second variable you did not want and reading around it.

    A one-way table keeps the two-way shape, with the missing side standing in
    as a single row or column named after the measure. That way everything
    downstream - the renderer, the export, the dashboard widget - needs to know
    nothing about it.

    With no measure at all the stand-in side is dropped instead of printed, and
    the table is the categories of the one variable it has: no counts, no
    totals, no chi-square. The values still have to be queried to know which
    categories occurred, so this is a question about what is shown rather than
    about what is asked of the data.
    """
    row_info = ctx.require(request.row_variable) if request.row_variable else None
    col_info = ctx.require(request.column_variable) if request.column_variable else None
    if row_info is None and col_info is None:  # pragma: no cover - schema catches this
        raise QueryError("A tabulation needs a row variable, a column variable, or both")

    dimensions = []
    if row_info is not None:
        dimensions.append(Dimension(variable=request.row_variable, alias="__row"))
    if col_info is not None:
        dimensions.append(Dimension(variable=request.column_variable, alias="__col"))

    # With no measure the query still counts: that is how it learns which
    # categories the data actually has. The counts are simply not shown.
    measure = request.measure or Measure()
    spec = QuerySpec(
        dimensions=dimensions,
        measures=[Measure(**{**measure.model_dump(), "alias": "__value"})],
        filters=request.filters,
        limit=MAX_ROWS,
        use_labels=False,
        sort=[],
    )
    builder = SQLBuilder(ctx)
    sql, params = builder.build_aggregate(spec)
    _, raw = run_sql(sql, params)

    # How many records each cell rests on, which is a different question from
    # what the cell shows. A mean of two incomes discloses those two people
    # however large the mean is, and a weighted count of 4,000 can rest on
    # three households - so disclosure is judged on the unweighted frequency
    # and a second query is what it takes to know it. Skipped entirely when no
    # floor is set, which is every deployment that has not asked for one.
    threshold = max(0, settings.disclosure_threshold)
    frequency: dict[tuple[Any, Any], float] = {}
    if threshold:
        # Only the records that reach the statistic. Every aggregate ignores
        # nulls, and a weighted one ignores a null weight as well, so a
        # category of a hundred people with one reported wage shows that one
        # person's wage - and counting the hundred would call it safe.
        guards = [name for name in (measure.variable, measure.weight) if name]
        counts_filters = (
            FilterGroup(
                op="and",
                conditions=[
                    Condition(variable=name, operator="is_not_null", value=None)
                    for name in guards
                ],
                groups=[request.filters],
            )
            if guards
            else request.filters
        )
        counts_sql, counts_params = builder.build_aggregate(
            spec.model_copy(
                update={"measures": [Measure(alias="__value")], "filters": counts_filters}
            )
        )
        _, counted = run_sql(counts_sql, counts_params)
        for record in counted:
            if row_info is not None and col_info is not None:
                frequency[(record[0], record[1])] = float(record[2] or 0)
            elif row_info is not None:
                frequency[(record[0], _ONE_WAY)] = float(record[1] or 0)
            else:
                frequency[(_ONE_WAY, record[0])] = float(record[1] or 0)

    # Normalise to (row key, column key, value) whichever way round it came, so
    # the counting below is the same for one variable and for two.
    if row_info is not None and col_info is not None:
        triples = list(raw)
    elif row_info is not None:
        triples = [(r, _ONE_WAY, v) for r, v in raw]
    else:
        triples = [(_ONE_WAY, c, v) for c, v in raw]

    measure_name = _measure_label(measure)

    def cell_label(info: Any, value: Any) -> str:
        if value is _ONE_WAY:
            return measure_name
        if value is None:
            return MISSING_LABEL
        return str(_label_value(info, value) if request.use_labels else value)

    row_keys: list[Any] = []
    col_keys: list[Any] = []
    table: dict[tuple[Any, Any], float] = {}
    for row_value, col_value, value in triples:
        if row_value not in row_keys:
            row_keys.append(row_value)
        if col_value not in col_keys:
            col_keys.append(col_value)
        table[(row_value, col_value)] = float(value or 0)

    all_rows = _sorted_keys(row_keys, row_info)
    all_cols = _sorted_keys(col_keys, col_info)
    rows_withheld = 0
    if request.measure is None:
        # The axis the table does not have carried a single column of counts.
        # Nobody asked for those, so it goes rather than being printed empty,
        # and an empty label list is what tells every renderer downstream that
        # this table has no value columns.
        if row_info is None:
            all_rows = []
        else:
            all_cols = []
        if threshold:
            # A listing has no cell to blank. Naming a category that three
            # people are in still says those three exist and where they are,
            # so a category below the floor is left out of the list instead.
            listed = all_cols if row_info is None else all_rows
            kept = []
            for key in listed:
                cell = (_ONE_WAY, key) if row_info is None else (key, _ONE_WAY)
                if not 1 <= frequency.get(cell, 0) < threshold:
                    kept.append(key)
            rows_withheld = len(listed) - len(kept)
            if row_info is None:
                all_cols = kept
            else:
                all_rows = kept
    row_keys = all_rows[: request.max_rows]
    col_keys = all_cols[: request.max_columns]
    rows_omitted = len(all_rows) - len(row_keys)
    columns_omitted = len(all_cols) - len(col_keys)

    values = [[table.get((r, c)) for c in col_keys] for r in row_keys]
    row_totals = [sum(v or 0 for v in row) for row in values]
    column_totals = [
        sum((values[i][j] or 0) for i in range(len(row_keys))) for j in range(len(col_keys))
    ]
    grand_total = sum(row_totals)

    # The totals are the true ones and stay published; that is exactly why a
    # withheld cell has to be protected from being recovered by subtracting
    # from them, which is what the secondary pass above does.
    # The margins are protected in the same pass as the cells, by being part of
    # the same matrix.
    #
    # They have to be. A margin is a line sum, so it is recoverable arithmetic
    # in both directions: a one-way table's row total is its single cell
    # exactly, and a totals row is one equation over the column totals. Bolting
    # a separate rule onto the margins would leave the next chain open, whereas
    # an extra row and column mean every relationship a reader can subtract
    # along is a line of one matrix, and the rule above already knows what to
    # do with a line.
    #
    # It is also why the margins come last in the matrix and are the largest
    # numbers in it: the pass prefers to withhold the smallest candidate, so a
    # cell goes before a total does.
    suppressed = [[False] * len(col_keys) for _ in row_keys]
    row_totals_hidden = [False] * len(row_keys)
    column_totals_hidden = [False] * len(col_keys)
    grand_total_hidden = False
    if threshold and row_keys and col_keys:
        counts = [[frequency.get((r, c), 0) for c in col_keys] for r in row_keys]
        extended = [line + [sum(line)] for line in counts]
        extended.append(
            [sum(counts[i][j] for i in range(len(row_keys))) for j in range(len(col_keys))]
            + [sum(sum(line) for line in counts)]
        )
        mask = _suppression_mask(extended, threshold)
        suppressed = [line[: len(col_keys)] for line in mask[: len(row_keys)]]
        row_totals_hidden = [line[len(col_keys)] for line in mask[: len(row_keys)]]
        column_totals_hidden = mask[len(row_keys)][: len(col_keys)]
        grand_total_hidden = mask[len(row_keys)][len(col_keys)]

        values = [
            [None if suppressed[i][j] else value for j, value in enumerate(row)]
            for i, row in enumerate(values)
        ]

    # Pearson's test counts observations. Weighted cells are an estimate of a
    # population, so feeding them in claims a sample the size of the country
    # and calls a coin toss significant at four decimal places. A design-based
    # test is not arithmetic on the finished table, so the honest thing is to
    # report nothing rather than something confident and wrong.
    #
    # It also goes when cells were actually withheld, because a statistic
    # computed over the full table is a statement about numbers the reader has
    # been refused. Merely having a floor configured is not enough: a table
    # with nothing small in it has nothing to protect.
    withheld_any = any(any(row) for row in suppressed)
    chi_square = (
        None
        if measure.weight or withheld_any
        else _chi_square(values, row_totals, column_totals, grand_total)
    )

    one_way = row_info is None or col_info is None
    if request.percentages != "none" and grand_total:
        # A one-way table has one meaningful denominator - the total - because
        # the axis it does not have is a single cell. Asking for "% of row" on
        # a table one column wide would print 100% down the page.
        basis = "total" if one_way else request.percentages
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
                }[basis]
                new_row.append(round(value / base * 100, 2) if base else None)
            percent_values.append(new_row)
        values = percent_values

    return CrosstabResult(
        row_variable=request.row_variable,
        column_variable=request.column_variable,
        row_variable_label=(row_info.label if row_info else "") or request.row_variable,
        column_variable_label=(
            (col_info.label if col_info else "") or request.column_variable
        ),
        row_labels=[cell_label(row_info, k) for k in row_keys],
        column_labels=[cell_label(col_info, k) for k in col_keys],
        values=values,
        row_totals=[
            None if row_totals_hidden[i] else total for i, total in enumerate(row_totals)
        ],
        column_totals=[
            None if column_totals_hidden[j] else total
            for j, total in enumerate(column_totals)
        ],
        grand_total=None if grand_total_hidden else grand_total,
        percentages=request.percentages,
        chi_square=chi_square,
        rows_omitted=rows_omitted,
        columns_omitted=columns_omitted,
        suppressed=suppressed,
        row_totals_suppressed=row_totals_hidden,
        column_totals_suppressed=column_totals_hidden,
        grand_total_suppressed=grand_total_hidden,
        rows_withheld=rows_withheld,
        disclosure_threshold=threshold,
    )


def _sorted_keys(keys: list[Any], info: VariableInfo | None) -> list[Any]:
    # The one-way sentinel is the only key on its axis, so there is nothing to
    # sort and nothing it could be compared against.
    if info is None:
        return list(keys)
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
            math.sqrt(statistic / (grand_total * min(len(row_totals) - 1, len(column_totals) - 1)))
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
