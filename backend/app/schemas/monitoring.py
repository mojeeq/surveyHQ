from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.monitoring import (
    AlertStatus,
    CheckType,
    Direction,
    Severity,
)
from app.schemas.query import Aggregation, FilterGroup, Measure, QuerySpec
from app.services.formula import NAME, FormulaError, names_in, parse

#: How many parts one formula may have.
#:
#: A rate is two parts and a stubborn one is four. Twenty would be a query per
#: part on every refresh, for a number nobody could read back off the tile.
MAX_PARTS = 12


class FormulaPart(BaseModel):
    """One counted thing in a formula, under its own name.

    The filters are this part's own: "done" is a count where the status says
    so, "issued" is a count of everything. That is the difference between the
    two halves of a completion rate, and it is why a formula needs parts at all
    rather than one filter for the whole indicator.
    """

    name: str
    measure: Measure = Field(default_factory=Measure)
    filters: FilterGroup = Field(default_factory=FilterGroup)

    @field_validator("name")
    @classmethod
    def _a_name_a_formula_can_refer_to(cls, value: str) -> str:
        name = (value or "").strip()
        if not NAME.fullmatch(name):
            raise ValueError(
                f"{value!r} cannot be used in a formula: a part is named with "
                "letters, digits and underscores, and does not start with a digit"
            )
        return name

    @model_validator(mode="after")
    def _a_share_is_already_a_percentage(self) -> FormulaPart:
        # It is a count over the grand total, so dividing it by another part
        # gives a ratio of two percentages, which is not what anybody means.
        if self.measure.agg == Aggregation.share:
            raise ValueError(
                "a share cannot be a part of a formula - count the rows and "
                "divide by the other part instead, which is the same question "
                "asked where it can be read"
            )
        return self


class Formula(BaseModel):
    """Named parts and the sum that combines them.

    Both empty is the ordinary case: the indicator is one aggregate, defined
    the way it always was. Set, and the parts are what is counted and the
    expression is the indicator.
    """

    expression: str = ""
    parts: list[FormulaPart] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.expression.strip() and not self.parts

    @model_validator(mode="after")
    def _it_adds_up(self) -> Formula:
        if self.is_empty:
            return self
        if not self.parts:
            raise ValueError("a formula needs at least one part to count")
        if len(self.parts) > MAX_PARTS:
            raise ValueError(f"a formula may have at most {MAX_PARTS} parts")
        named = [part.name for part in self.parts]
        repeated = {name for name in named if named.count(name) > 1}
        if repeated:
            raise ValueError(
                f"two parts are both called {sorted(repeated)[0]!r}, so the "
                "formula cannot say which one it means"
            )
        try:
            parse(self.expression)
            asked = names_in(self.expression)
        except FormulaError as exc:
            raise ValueError(str(exc)) from exc
        missing = sorted(asked - set(named))
        if missing:
            raise ValueError(
                f"the formula uses {missing[0]!r}, which is not one of its parts"
            )
        # All weighted alike or none of them. A weighted count over an
        # unweighted one divides an estimated population by a number of
        # interviews, which comes out as a figure and means nothing.
        weights = {part.measure.weight or "" for part in self.parts}
        if len(weights) > 1:
            raise ValueError(
                "some parts are weighted and some are not, or by different "
                "weights; a formula's parts have to be weighted the same way"
            )
        return self


class FormulaCheck(BaseModel):
    """A formula asked about before it is saved."""

    dataset_id: str
    formula: Formula


class FormulaPreview(BaseModel):
    """What it says, and what each of its parts counted.

    The parts are the useful half: "17 over 0" says which side of the fraction
    is wrong, where a blank answer says only that something is.
    """

    value: float | None = None
    parts: dict[str, float | None] = Field(default_factory=dict)
    error: str | None = None


class IndicatorCreate(BaseModel):
    name: str
    description: str = ""
    dataset_id: str
    spec: QuerySpec
    unit: str = ""
    value_format: str = "number"
    target_value: float | None = None
    target_date: dt.date | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    direction: Direction = Direction.higher_is_better
    breakdown_variable: str = ""
    # {"North": 400, "South": 600} - a quota per category of that breakdown.
    breakdown_targets: dict[str, float] = Field(default_factory=dict)
    # A shared target set instead, which wins over the inline quotas above.
    target_set_id: str | None = None
    percent_of: Literal["", "all_rows", "answered"] = ""
    # Named parts and a sum over them, instead of the single measure above.
    formula: Formula = Field(default_factory=Formula)
    display_order: int = 0


class IndicatorUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    # An indicator can be pointed at another dataset, which is what editing one
    # onto this round's data amounts to. The spec travels with it, because the
    # variables it names belong to the dataset it came from.
    dataset_id: str | None = None
    spec: QuerySpec | None = None
    unit: str | None = None
    value_format: str | None = None
    target_value: float | None = None
    target_date: dt.date | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    direction: Direction | None = None
    breakdown_variable: str | None = None
    breakdown_targets: dict[str, float] | None = None
    # "" clears the link and goes back to this indicator's own quotas.
    target_set_id: str | None = None
    percent_of: Literal["", "all_rows", "answered"] | None = None
    # An empty formula clears one, and goes back to the single measure.
    formula: Formula | None = None
    is_active: bool | None = None
    display_order: int | None = None


class IndicatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    dataset_id: str
    spec: dict[str, Any] = Field(default_factory=dict)
    unit: str = ""
    value_format: str = "number"
    target_value: float | None = None
    target_date: dt.date | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    direction: Direction
    breakdown_variable: str = ""
    # {"North": 400, "South": 600} - a quota per category of that breakdown.
    breakdown_targets: dict[str, float] = Field(default_factory=dict)
    target_set_id: str | None = None
    percent_of: str = ""
    formula: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    display_order: int = 0
    last_value: float | None = None
    last_computed_at: dt.datetime | None = None
    created_at: dt.datetime


class IndicatorValue(BaseModel):
    indicator_id: str
    name: str
    value: float | None = None
    unit: str = ""
    value_format: str = "number"
    target_value: float | None = None
    target_date: dt.date | None = None
    progress_percent: float | None = None
    status: str = "unknown"
    direction: Direction = Direction.higher_is_better
    breakdown: dict[str, float] = Field(default_factory=dict)
    # Per group: its value, its own quota, how far through it is and what that
    # makes it. Beside the raw breakdown rather than instead of it, so a reader
    # that only wants the numbers is unaffected.
    breakdown_progress: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # True where the breakdown has more groups than one answer reports.
    breakdown_truncated: bool = False
    breakdown_variable: str = ""
    computed_at: dt.datetime | None = None
    error: str | None = None
    trend: list[dict[str, Any]] = Field(default_factory=list)
    # How it has moved and where it is heading: the change since yesterday
    # and since last week, the pace, and when that pace reaches the target.
    # Read off the stored history, so empty until there is some.
    movement: dict[str, Any] = Field(default_factory=dict)


class TargetSetCreate(BaseModel):
    """A quota per category of one variable, as its own record."""

    name: str
    description: str = ""
    dataset_id: str
    variable: str = ""
    # Keyed by the value as the data holds it. Two thousand entries is normal
    # for a census, so this is never rendered as a form field per key.
    targets: dict[str, float] = Field(default_factory=dict)


class TargetSetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    variable: str | None = None
    # Replaces the lot. A pasted list is the whole list, and merging would make
    # removing a category impossible.
    targets: dict[str, float] | None = None


class TargetSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    dataset_id: str
    variable: str
    targets: dict[str, float]
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class TargetSetSummary(BaseModel):
    """A set without its two thousand rows, for the list and the pickers."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    dataset_id: str
    dataset_name: str = ""
    variable: str
    categories: int = 0
    total: float = 0.0
    used_by: int = 0
    updated_at: dt.datetime | None = None



class AlertRuleCreate(BaseModel):
    name: str
    description: str = ""
    indicator_id: str | None = None
    dataset_id: str | None = None
    condition: dict[str, Any] = Field(default_factory=lambda: {"operator": "lt", "value": 0})
    severity: Severity = Severity.warning
    channels: list[str] = Field(default_factory=lambda: ["in_app"])
    recipients: list[str] = Field(default_factory=list)
    cooldown_minutes: int = 60


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    # Which indicator the rule watches is editable, not only set at creation:
    # a rule aimed at the wrong one is the commonest thing to want to correct,
    # and the alternative is deleting it and losing when it last fired. The
    # route checks the destination the same way creating against it would.
    indicator_id: str | None = None
    condition: dict[str, Any] | None = None
    severity: Severity | None = None
    channels: list[str] | None = None
    recipients: list[str] | None = None
    cooldown_minutes: int | None = None
    is_active: bool | None = None


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    indicator_id: str | None = None
    dataset_id: str | None = None
    condition: dict[str, Any] = Field(default_factory=dict)
    severity: Severity
    channels: list[str] = Field(default_factory=list)
    recipients: list[str] = Field(default_factory=list)
    cooldown_minutes: int
    is_active: bool
    last_triggered_at: dt.datetime | None = None
    created_at: dt.datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_id: str | None = None
    title: str = ""
    message: str = ""
    severity: Severity
    status: AlertStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime
    acknowledged_at: dt.datetime | None = None
    resolved_at: dt.datetime | None = None


class QualityRuleCreate(BaseModel):
    name: str
    dataset_id: str
    check_type: CheckType
    config: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = Severity.warning
    threshold: float = 0.0
    # Restricts the check to part of the dataset. Both the failing rows and the
    # total are counted inside it, so the failure rate stays a rate of what the
    # check actually looked at.
    filters: FilterGroup = Field(default_factory=FilterGroup)


class QualityRuleUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    severity: Severity | None = None
    threshold: float | None = None
    is_active: bool | None = None
    filters: FilterGroup | None = None


class QualityRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    dataset_id: str
    check_type: CheckType
    config: dict[str, Any] = Field(default_factory=dict)
    severity: Severity
    threshold: float
    is_active: bool
    filters: FilterGroup = Field(default_factory=FilterGroup)
    created_at: dt.datetime


class QualityResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_id: str
    run_at: dt.datetime
    passed: bool
    failed_rows: int
    total_rows: int
    failure_rate: float
    details: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class QualityRuleWithResult(QualityRuleOut):
    latest_result: QualityResultOut | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str = ""
    body: str = ""
    level: str = "info"
    link: str = ""
    created_at: dt.datetime
    read_at: dt.datetime | None = None


class ActivityJob(BaseModel):
    """A job as the activity panel shows it: its steps, never its parameters."""

    id: str
    job_type: str
    status: str
    title: str = ""
    progress: float = 0.0
    stages: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""
    warnings: list[str] = Field(default_factory=list)
    project_name: str = ""
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    created_at: dt.datetime


class ScheduledSync(BaseModel):
    """When a connection will next import, and so when its dashboards move."""

    connection_id: str
    name: str
    project_name: str = ""
    due_at: dt.datetime


class ActivityOut(BaseModel):
    jobs: list[ActivityJob] = Field(default_factory=list)
    upcoming: list[ScheduledSync] = Field(default_factory=list)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: str
    status: str
    title: str = ""
    progress: float = 0.0
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    stages: list[dict[str, Any]] | None = None
    error: str = ""
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    created_at: dt.datetime
