"""The query specification shared by explore, charts, indicators and widgets.

A spec is deliberately declarative JSON so it can be stored on a chart, replayed
by a scheduled job, and rebuilt in the UI without server-side templating.
"""

from __future__ import annotations

import enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Aggregation(str, enum.Enum):
    count = "count"
    count_distinct = "count_distinct"
    sum = "sum"
    mean = "mean"
    median = "median"
    min = "min"
    max = "max"
    stddev = "stddev"
    p25 = "p25"
    p75 = "p75"
    p90 = "p90"
    share = "share"  # count as a percentage of the grand total


class DateGrain(str, enum.Enum):
    day = "day"
    week = "week"
    month = "month"
    quarter = "quarter"
    year = "year"


class FilterOperator(str, enum.Enum):
    eq = "eq"
    ne = "ne"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    in_ = "in"
    not_in = "not_in"
    contains = "contains"
    not_contains = "not_contains"
    starts_with = "starts_with"
    ends_with = "ends_with"
    between = "between"
    is_null = "is_null"
    is_not_null = "is_not_null"


class Dimension(BaseModel):
    """A grouping column."""

    variable: str
    alias: str | None = None
    grain: DateGrain | None = None
    # Numeric binning: bucket width, e.g. 10 turns age into 0-9, 10-19, ...
    bin_width: float | None = None
    # Keep only the N largest groups, the rest collapse into "Other"
    limit: int | None = None
    sort: Literal["asc", "desc", "value_asc", "value_desc"] | None = None

    @property
    def output_name(self) -> str:
        return self.alias or self.variable


class Measure(BaseModel):
    agg: Aggregation = Aggregation.count
    variable: str | None = None
    alias: str | None = None
    # Numeric variable holding the survey weight
    weight: str | None = None

    @model_validator(mode="after")
    def _check_variable(self) -> Measure:
        needs_variable = {
            Aggregation.sum,
            Aggregation.mean,
            Aggregation.median,
            Aggregation.min,
            Aggregation.max,
            Aggregation.stddev,
            Aggregation.p25,
            Aggregation.p75,
            Aggregation.p90,
            Aggregation.count_distinct,
        }
        if self.agg in needs_variable and not self.variable:
            raise ValueError(f"aggregation '{self.agg.value}' requires a variable")
        return self

    @property
    def output_name(self) -> str:
        if self.alias:
            return self.alias
        if self.variable:
            return f"{self.agg.value}_{self.variable}"
        return self.agg.value


class Condition(BaseModel):
    variable: str
    operator: FilterOperator = FilterOperator.eq
    value: Any = None
    # Compare against the labelled value rather than the stored code
    use_label: bool = False


class FilterGroup(BaseModel):
    op: Literal["and", "or"] = "and"
    conditions: list[Condition] = Field(default_factory=list)
    groups: list[FilterGroup] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.conditions and all(g.is_empty() for g in self.groups)


FilterGroup.model_rebuild()


class SortSpec(BaseModel):
    field: str
    direction: Literal["asc", "desc"] = "desc"


class QuerySpec(BaseModel):
    """Full description of an aggregate query over one dataset."""

    dimensions: list[Dimension] = Field(default_factory=list)
    measures: list[Measure] = Field(default_factory=list)
    filters: FilterGroup = Field(default_factory=FilterGroup)
    sort: list[SortSpec] = Field(default_factory=list)
    limit: int = Field(default=1000, ge=1, le=100_000)
    offset: int = Field(default=0, ge=0)
    # Replace stored codes with value labels in the response
    use_labels: bool = True
    # Drop rows where any dimension is null
    drop_missing: bool = False

    @model_validator(mode="after")
    def _default_measure(self) -> QuerySpec:
        if not self.measures:
            self.measures = [Measure(agg=Aggregation.count, alias="count")]
        return self


class QueryColumn(BaseModel):
    name: str
    label: str = ""
    type: Literal["dimension", "measure"] = "measure"
    data_type: str = "number"


class QueryResult(BaseModel):
    columns: list[QueryColumn]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    sql: str = ""
    duration_ms: int = 0
    total_rows_scanned: int | None = None


class CrosstabRequest(BaseModel):
    row_variable: str
    column_variable: str
    measure: Measure = Field(default_factory=Measure)
    filters: FilterGroup = Field(default_factory=FilterGroup)
    percentages: Literal["none", "row", "column", "total"] = "none"
    include_totals: bool = True
    use_labels: bool = True
    # Rows and columns are not the same question. A table is read down: 5,000
    # rows scroll perfectly well and export whole, which is what tabulating by
    # interview key or enumeration area needs. Columns are read across, and a
    # thousand of them is a scroll bar rather than a table - but it still
    # exports, so the ceiling is generous rather than tasteful.
    max_rows: int = Field(default=5_000, ge=2, le=100_000)
    max_columns: int = Field(default=1_000, ge=2, le=10_000)


class CrosstabResult(BaseModel):
    row_variable: str
    column_variable: str
    row_labels: list[str]
    column_labels: list[str]
    values: list[list[float | None]]
    row_totals: list[float]
    column_totals: list[float]
    grand_total: float
    percentages: str = "none"
    chi_square: dict[str, Any] | None = None
    # How many categories the data actually had, when that is more than was
    # returned. Silently cutting a table is worse than a small table: the
    # totals still add up, so nothing on screen says the rest is missing.
    rows_omitted: int = 0
    columns_omitted: int = 0


class FrequencyRow(BaseModel):
    value: Any
    label: str
    count: int
    percent: float
    valid_percent: float
    cumulative_percent: float


class FrequencyResult(BaseModel):
    variable: str
    label: str
    rows: list[FrequencyRow]
    total: int
    missing: int
    distinct: int


class SummaryStats(BaseModel):
    variable: str
    label: str = ""
    count: int = 0
    missing: int = 0
    mean: float | None = None
    std: float | None = None
    min: float | None = None
    p25: float | None = None
    median: float | None = None
    p75: float | None = None
    max: float | None = None
    sum: float | None = None
