"""Indicator evaluation, threshold logic and alert firing."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import (
    Alert,
    AlertRule,
    AlertStatus,
    Dataset,
    Direction,
    Indicator,
    IndicatorSnapshot,
    Notification,
    Role,
    User,
)
from app.schemas.query import Aggregation, Condition, Dimension, FilterGroup, Measure, QuerySpec
from app.services import formula as arithmetic
from app.services.datasets import dataset_is_queryable
from app.services.query_engine import DatasetContext, QueryError, execute_query

logger = get_logger(__name__)

COMPARATORS = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


class IndicatorStatus(str):
    ok = "ok"
    warning = "warning"
    critical = "critical"
    unknown = "unknown"


def and_also(left: FilterGroup | None, right: FilterGroup | None) -> FilterGroup:
    """Both filters, or whichever of them says anything.

    Nesting rather than concatenating the conditions: either side may be an
    "or", and flattening one of those into a list of "and" conditions would
    quietly widen or narrow it into a different question.
    """
    parts = [g for g in (left, right) if g is not None and not g.is_empty()]
    if not parts:
        return FilterGroup()
    if len(parts) == 1:
        return parts[0]
    return FilterGroup(op="and", conditions=[], groups=parts)


#: How many groups a breakdown reports.
#:
#: Two hundred was a dropdown's worth, and an indicator broken down by
#: enumeration area has two thousand groups in a small census: nine tenths of
#: the country was quietly left out of the tile, the chart and the quota
#: comparison, with nothing saying so. There is still a ceiling, because a
#: breakdown by interview key is one row per interview and that is not a
#: breakdown; where it bites the answer says so rather than being short in
#: silence.
BREAKDOWN_LIMIT = 5_000


#: Aggregations whose answer for a group that matched nothing is zero.
#:
#: A province where no interview was refused has nought refusals, and a rate
#: with nought on top is a real nought per cent. The mean of no rows, on the
#: other hand, is not zero - there is nothing to take the mean of - so those
#: leave the group with no value at all and the whole sum reports none.
COUNTED = {Aggregation.count, Aggregation.count_distinct, Aggregation.sum}


def formula_of(indicator: Indicator) -> Any:
    """The indicator's formula, or None where it is defined the plain way."""
    from app.schemas.monitoring import Formula

    raw = indicator.formula or {}
    if not raw:
        return None
    try:
        parsed = Formula.model_validate(raw)
    except Exception:  # noqa: BLE001 - a stored formula may predate a rule
        return None
    return None if parsed.is_empty else parsed


def part_spec(
    part: Any,
    indicator: Indicator,
    filters: FilterGroup | None,
    breakdown: bool,
) -> QuerySpec:
    """The query behind one part of a formula.

    The part's own filters are what make it a part - "done" counts the rows
    whose status says so - and the page's filters narrow every part alike, so
    a rate stays a rate when the board is filtered to one province rather than
    becoming that province's share of the country.
    """
    return QuerySpec(
        dimensions=(
            [Dimension(variable=indicator.breakdown_variable)] if breakdown else []
        ),
        measures=[part.measure.model_copy(update={"alias": "value"})],
        filters=and_also(part.filters, filters),
        limit=BREAKDOWN_LIMIT + 1 if breakdown else 1,
    )


def part_values(
    ctx: DatasetContext,
    indicator: Indicator,
    spec: Any,
    filters: FilterGroup | None = None,
) -> dict[str, float | None]:
    """Each part of a formula, counted over the whole of what is being looked at.

    A part that matched nothing is nought where it counts things and nothing
    at all where it averages them: no refusals is nought refusals, but the
    mean of no rows is not nought, and a rate built on one would be a number
    about rows that are not there.
    """
    values: dict[str, float | None] = {}
    for part in spec.parts:
        result = execute_query(ctx, part_spec(part, indicator, filters, breakdown=False))
        raw = result.rows[0][0] if result.rows and result.rows[0] else None
        if raw is None:
            values[part.name] = 0.0 if part.measure.agg in COUNTED else None
        else:
            values[part.name] = float(raw)
    return values


def preview_formula(
    db: Session, dataset_id: str, spec: Any, breakdown_variable: str = ""
) -> dict[str, Any]:
    """What a formula would report, before anybody saves it.

    A formula is typed, and a typed formula is wrong until it is not: a part
    counting nothing, a denominator that is the wrong rows, a bracket in the
    wrong place. The parts are reported beside the answer, because "17 over 0"
    says which half is wrong where a blank tile says only that something is.
    """
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or not dataset_is_queryable(dataset):
        return {"value": None, "parts": {}, "error": "Dataset is not available"}
    held = Indicator(dataset_id=dataset_id, breakdown_variable=breakdown_variable)
    ctx = DatasetContext.from_model(dataset)
    try:
        arithmetic.parse(spec.expression)
        values = part_values(ctx, held, spec)
    except arithmetic.FormulaError as exc:
        return {"value": None, "parts": {}, "error": str(exc)}
    except QueryError as exc:
        return {"value": None, "parts": {}, "error": str(exc)}
    return {
        "value": arithmetic.compute(spec.expression, values),
        "parts": values,
        "error": None,
    }


def _by_formula(
    ctx: DatasetContext,
    indicator: Indicator,
    spec: Any,
    filters: FilterGroup | None,
) -> dict[str, Any]:
    """An indicator computed as arithmetic over its parts.

    One query per part, twice over where there is a breakdown: the parts are
    counted separately because each carries its own filter, and no one query
    can answer "how many were done" and "how many were issued" at once.
    """
    try:
        tree = arithmetic.parse(spec.expression)
    except arithmetic.FormulaError as exc:
        return {"value": None, "error": f"Invalid formula: {exc}", "breakdown": {}}

    try:
        headline = part_values(ctx, indicator, spec, filters)
    except QueryError as exc:
        return {"value": None, "error": str(exc), "breakdown": {}}

    value = arithmetic.evaluate(tree, headline)

    breakdown: dict[str, float] = {}
    truncated = False
    if indicator.breakdown_variable:
        per_part: dict[str, dict[str, float]] = {}
        # Every group any part saw, in the order they were first seen, so the
        # list is not silently shortened to whichever part matched fewest rows
        # and not reordered by which part was counted first.
        groups: list[str] = []
        seen: set[str] = set()
        for part in spec.parts:
            try:
                rows = execute_query(
                    ctx, part_spec(part, indicator, filters, breakdown=True)
                ).rows
            except QueryError as exc:
                logger.warning("Breakdown failed for indicator %s: %s", indicator.name, exc)
                return {
                    "value": value,
                    "breakdown": {},
                    "breakdown_truncated": False,
                    "error": None,
                }
            truncated = truncated or len(rows) > BREAKDOWN_LIMIT
            found: dict[str, float] = {}
            for row in rows[:BREAKDOWN_LIMIT]:
                key = "(missing)" if row[0] is None else str(row[0])
                if key not in seen:
                    seen.add(key)
                    groups.append(key)
                found[key] = float(row[1]) if row[1] is not None else 0.0
            per_part[part.name] = found
        for key in groups:
            here = {
                part.name: (
                    per_part[part.name].get(key)
                    if key in per_part[part.name]
                    else (0.0 if part.measure.agg in COUNTED else None)
                )
                for part in spec.parts
            }
            group_value = arithmetic.evaluate(tree, here)
            # A group the sum has nothing to say about - nothing issued there,
            # so no rate - is left out rather than drawn as a nought.
            if group_value is not None:
                breakdown[key] = round(group_value, 4)

    return {
        "value": value,
        "breakdown": breakdown,
        "breakdown_truncated": truncated,
        "error": None,
    }


def evaluate_indicator(
    db: Session, indicator: Indicator, filters: FilterGroup | None = None
) -> dict[str, Any]:
    """Compute an indicator's current value plus its optional breakdown.

    An extra filter narrows the rows the indicator is computed over, which is
    what a dashboard's filter controls pass in: "interviews completed" becomes
    "interviews completed in Northern" without the indicator itself being
    redefined. It is applied to the denominator as well, so a percentage stays
    a share of the rows being looked at rather than of the whole file.
    """
    dataset = db.get(Dataset, indicator.dataset_id)
    if dataset is None or not dataset_is_queryable(dataset):
        return {"value": None, "error": "Dataset is not available", "breakdown": {}}

    ctx = DatasetContext.from_model(dataset)

    # An indicator defined as arithmetic over named parts is computed from
    # those parts, and the single measure below is not consulted at all: the
    # formula is the definition, not an adjustment to one.
    written = formula_of(indicator)
    if written is not None:
        return _by_formula(ctx, indicator, written, filters)

    try:
        spec = QuerySpec.model_validate(indicator.spec or {})
    except Exception as exc:  # noqa: BLE001 - stored spec may predate a schema change
        return {"value": None, "error": f"Invalid indicator definition: {exc}", "breakdown": {}}

    if filters is not None and not filters.is_empty():
        spec = spec.model_copy(update={"filters": and_also(spec.filters, filters)})

    # The headline value ignores any dimensions in the stored spec
    headline_spec = spec.model_copy(update={"dimensions": [], "limit": 1})
    try:
        result = execute_query(ctx, headline_spec)
    except QueryError as exc:
        return {"value": None, "error": str(exc), "breakdown": {}}

    value: float | None = None
    if result.rows and result.rows[0]:
        raw = result.rows[0][0]
        value = float(raw) if raw is not None else None

    breakdown: dict[str, float] = {}
    truncated = False
    if indicator.breakdown_variable:
        breakdown_spec = spec.model_copy(
            update={
                "dimensions": [Dimension(variable=indicator.breakdown_variable)],
                # One more than the ceiling, which is how a short answer is
                # told apart from a truncated one.
                "limit": BREAKDOWN_LIMIT + 1,
            }
        )
        try:
            breakdown_result = execute_query(ctx, breakdown_spec)
            truncated = len(breakdown_result.rows) > BREAKDOWN_LIMIT
            for row in breakdown_result.rows[:BREAKDOWN_LIMIT]:
                key = "(missing)" if row[0] is None else str(row[0])
                breakdown[key] = float(row[1]) if row[1] is not None else 0.0
        except QueryError as exc:
            logger.warning("Breakdown failed for indicator %s: %s", indicator.name, exc)

    if indicator.percent_of:
        try:
            value, breakdown = _as_percentages(ctx, indicator, spec, value, breakdown, filters)
        except QueryError as exc:
            return {"value": None, "error": str(exc), "breakdown": {}}

    return {
        "value": value,
        "breakdown": breakdown,
        # Said rather than left to be noticed: a tile reporting five
        # thousand of six thousand areas looks exactly like one reporting
        # all of them.
        "breakdown_truncated": truncated,
        "error": None,
    }


def _denominator_spec(
    indicator: Indicator, spec: QuerySpec, filters: FilterGroup | None = None
) -> QuerySpec:
    """The query the indicator's own count is a share of.

    Its filters are dropped, which is the whole point: the indicator's filters
    are what select the rows being counted - completed interviews, households
    with electricity - and the share is of the rows those were chosen from.

    A filter arriving from a dashboard is not dropped: it says which rows the
    reader is looking at, not which of them count as a success, so it belongs
    on both halves of the fraction.
    """
    keep = FilterGroup()
    if indicator.percent_of == "answered":
        # "Of those who answered" needs the rows where the measured variable is
        # present. Without a measured variable there is nothing to have
        # answered, so this falls back to every row.
        measured = next((m.variable for m in spec.measures if m.variable), None)
        if measured:
            keep = FilterGroup(conditions=[Condition(variable=measured, operator="is_not_null")])
    return QuerySpec(
        dimensions=[],
        # Weighted as the count is: a weighted count over an unweighted total
        # is an estimated population divided by a number of interviews, which
        # is no share of anything.
        measures=[Measure(agg=Aggregation.count, alias="value", weight=weight_of(spec))],
        filters=and_also(keep, filters),
        limit=1,
    )


def weight_of(spec: QuerySpec) -> str | None:
    """The survey weight an indicator is measured with, if any."""
    return next((m.weight for m in spec.measures if m.weight), None)


def _as_percentages(
    ctx: DatasetContext,
    indicator: Indicator,
    spec: QuerySpec,
    value: float | None,
    breakdown: dict[str, float],
    filters: FilterGroup | None = None,
) -> tuple[float | None, dict[str, float]]:
    """Turn a count and its breakdown into percentages of their own totals.

    Each group is divided by its own total rather than by the whole: "72% in
    Northern" means 72% of Northern's interviews, not that Northern holds 72% of the
    completed ones. The second reading is what a share-of-total chart already
    says, and it answers a different question from the one a target is set on.
    """
    denominator = _denominator_spec(indicator, spec, filters)
    total_result = execute_query(ctx, denominator)
    total = 0.0
    if total_result.rows and total_result.rows[0] and total_result.rows[0][0] is not None:
        total = float(total_result.rows[0][0])
    percent = round(value / total * 100, 2) if total and value is not None else None

    if not breakdown:
        return percent, {}

    per_group = denominator.model_copy(
        update={
            "dimensions": [Dimension(variable=indicator.breakdown_variable)],
            "limit": BREAKDOWN_LIMIT,
        }
    )
    totals: dict[str, float] = {}
    for row in execute_query(ctx, per_group).rows:
        key = "(missing)" if row[0] is None else str(row[0])
        totals[key] = float(row[1]) if row[1] is not None else 0.0

    shares: dict[str, float] = {}
    # Driven by the denominator, not the numerator: a region where nothing
    # matched still has a rate, and it is 0%. Leaving it out would read as
    # "no data from there", which is the opposite of what happened.
    for key, group_total in totals.items():
        # A group with no rows behind it genuinely has no rate to report.
        if group_total:
            shares[key] = round(breakdown.get(key, 0.0) / group_total * 100, 2)
    return percent, shares


def indicator_status(indicator: Indicator, value: float | None) -> str:
    """Map a value onto ok / warning / critical using the configured thresholds."""
    if value is None:
        return IndicatorStatus.unknown
    warning = indicator.warning_threshold
    critical = indicator.critical_threshold
    if warning is None and critical is None:
        return IndicatorStatus.ok

    if indicator.direction == Direction.lower_is_better:
        if critical is not None and value >= critical:
            return IndicatorStatus.critical
        if warning is not None and value >= warning:
            return IndicatorStatus.warning
        return IndicatorStatus.ok

    if indicator.direction == Direction.higher_is_better:
        if critical is not None and value <= critical:
            return IndicatorStatus.critical
        if warning is not None and value <= warning:
            return IndicatorStatus.warning
        return IndicatorStatus.ok

    return IndicatorStatus.ok


def progress_percent(indicator: Indicator, value: float | None) -> float | None:
    if value is None or not indicator.target_value:
        return None
    return round(value / indicator.target_value * 100, 2)


def quotas(indicator: Indicator) -> dict[str, Any]:
    """The quotas this indicator is judged by: a linked set's, or its own.

    A target set is the same list kept once and read by several indicators -
    households enumerated, questionnaires received and interviews verified all
    against the same area quotas. Where one is linked it wins outright rather
    than merging with the indicator's own: two lists half-applied is a number
    nobody can account for, and the set is the one somebody maintains.

    A set that has been deleted leaves the link empty, and the indicator falls
    back to whatever it carries itself.
    """
    linked = getattr(indicator, "target_set", None)
    if linked is not None and linked.targets:
        return dict(linked.targets)
    return dict(indicator.breakdown_targets or {})


def label_map(db: Session, indicator: Indicator) -> dict[str, str]:
    """{code: label} for the breakdown variable, where it is a labelled one.

    A labelled variable is reported by its label - "0405" - and the quotas
    were stored against the code behind it - 405 - because that is what the
    list of values offers. The two never met, so an enumeration area whose
    label is its code with a zero in front of it had a quota that was never
    applied and no sign that it was not.
    """
    if not indicator.breakdown_variable:
        return {}
    dataset = db.get(Dataset, indicator.dataset_id)
    if dataset is None:
        return {}
    try:
        info = DatasetContext.from_model(dataset).variables.get(indicator.breakdown_variable)
    except Exception:  # pragma: no cover - a dataset whose files have gone
        return {}
    if info is None or not info.value_labels:
        return {}
    return {str(code): str(label) for code, label in info.value_labels.items()}


def effective_quotas(
    indicator: Indicator, labels: dict[str, str] | None = None
) -> dict[str, float | Any]:
    """The quotas, answering to the spelling the breakdown reports them by.

    A quota is kept under one key and looked up by another whenever the
    variable is labelled, so each one also answers to its label. The stored
    key wins where both exist, and a label already carrying a quota of its own
    is never overwritten by the code's.
    """
    stored = quotas(indicator)
    if not labels or not stored:
        return stored
    answered = dict(stored)
    for code, label in labels.items():
        if label not in answered and code in stored:
            answered[label] = stored[code]
    return answered


def target_for(
    indicator: Indicator, category: str, labels: dict[str, str] | None = None
) -> float | None:
    """The target one category of a breakdown is judged against: its own, or none.

    A survey's quota is rarely a single number: it is so many interviews in
    each region, so many of each sex, and the headline is what those add up
    to. So a group is judged against its own quota and nothing else.

    A group with no quota of its own has no target, rather than inheriting the
    headline. The headline belongs to every group together - an enumeration
    area of two hundred households measured against a national fifteen
    thousand is at one per cent of a target that was never its own, which
    reads as a disaster on a board full of them. Nothing is a more honest
    answer than a wrong one.
    """
    raw = effective_quotas(indicator, labels).get(category)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # Stored JSON, so it can hold whatever got past the schema. A junk
        # target is no target rather than a reason to fail the whole tile.
        return None


def targets_total(indicator: Indicator) -> float:
    """What the per-group quotas add up to, for comparing with the headline."""
    total = 0.0
    for raw in quotas(indicator).values():
        try:
            total += float(raw)
        except (TypeError, ValueError):
            continue
    return total


def _status_against(
    indicator: Indicator, value: float | None, target: float | None
) -> str:
    """Status for one category, with the thresholds scaled to its own target.

    The thresholds are set against the headline. A region carrying half the
    quota should trip its warning at half the count, or every small region
    would sit permanently in the red - so they move with the target. A region
    with no quota at all is reported as unknown rather than measured against
    a number that belongs to the whole survey.
    """
    if value is None:
        return IndicatorStatus.unknown
    headline = indicator.target_value
    # A group with no quota of its own is not judged. Its thresholds would
    # have to be the headline's, which is the comparison this exists to stop.
    if target is None:
        return IndicatorStatus.unknown
    if not headline or headline == target:
        return indicator_status(indicator, value)

    scale = target / headline
    scaled = Indicator(
        warning_threshold=(
            None
            if indicator.warning_threshold is None
            else indicator.warning_threshold * scale
        ),
        critical_threshold=(
            None
            if indicator.critical_threshold is None
            else indicator.critical_threshold * scale
        ),
        direction=indicator.direction,
    )
    return indicator_status(scaled, value)


def breakdown_progress(
    indicator: Indicator,
    breakdown: dict[str, float],
    labels: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Each category's value against its own target.

    Returned beside the raw breakdown rather than instead of it, so a caller
    that only wants the numbers is unaffected.

    `labels` is {code: label} for the breakdown variable, from `label_map`.
    Without it a quota stored against a labelled variable's code is invisible
    to a breakdown reported by its label.
    """
    report: dict[str, dict[str, Any]] = {}
    resolved = effective_quotas(indicator, labels)
    for category, value in breakdown.items():
        raw = resolved.get(category)
        try:
            target = None if raw is None else float(raw)
        except (TypeError, ValueError):
            target = None
        report[category] = {
            "value": value,
            "target": target,
            "percent": round(value / target * 100, 2) if target else None,
            "status": _status_against(indicator, value, target),
        }
    return report


DAY = dt.timedelta(days=1)
#: How far back the pace is averaged over. A week smooths out the day nobody
#: synced and the Monday everybody did, and is short enough to notice a team
#: that has slowed down.
PACE_WINDOW = dt.timedelta(days=7)
#: Past this a projected finish is not a date, it is "not at this rate".
PROJECTION_HORIZON = dt.timedelta(days=3650)


def _aware(moment: dt.datetime) -> dt.datetime:
    # SQLite hands back the stored moment without its zone; it was UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def _stored(db: Session, indicator_id: str, *, at_or_before: dt.datetime | None = None,
            from_moment: dt.datetime | None = None) -> tuple[float, dt.datetime] | None:
    """One stored value: the last at or before a moment, or the first from one."""
    statement = select(IndicatorSnapshot.value, IndicatorSnapshot.computed_at).where(
        IndicatorSnapshot.indicator_id == indicator_id, IndicatorSnapshot.value.is_not(None)
    )
    if at_or_before is not None:
        statement = statement.where(IndicatorSnapshot.computed_at <= at_or_before).order_by(
            IndicatorSnapshot.computed_at.desc()
        )
    else:
        statement = statement.where(IndicatorSnapshot.computed_at >= from_moment).order_by(
            IndicatorSnapshot.computed_at.asc()
        )
    row = db.execute(statement.limit(1)).first()
    return (float(row[0]), _aware(row[1])) if row else None


def movement(
    db: Session, indicator: Indicator, value: float | None, now: dt.datetime | None = None
) -> dict[str, Any]:
    """How an indicator has moved, and where that is taking it.

    A tile showed the number, how far it was from its target and the shape of
    its recent history - and left the two questions a field manager asks every
    morning to arithmetic on a sparkline: how much did we do since yesterday,
    and at this rate, when do we finish?

    All of it is read off the stored values, the same series the sparkline
    draws, so it describes the indicator over the whole dataset and is never
    set beside a filtered value. Every figure is left out where the history
    cannot support it: no change since last week on an indicator a day old,
    no pace from an afternoon's values, no finishing date at a pace going the
    wrong way.

    The pace is the plain average over the last week - what it went up by,
    divided by the days that took - rather than a fitted line, so that "at 190
    a day" is a figure anybody can check against the counts.
    """
    now = now or utcnow()
    out: dict[str, Any] = {
        "target_date": indicator.target_date.isoformat() if indicator.target_date else None,
    }
    if value is None:
        return out
    yesterday = _stored(db, indicator.id, at_or_before=now - DAY)
    last_week = _stored(db, indicator.id, at_or_before=now - 7 * DAY)
    out["change_day"] = round(value - yesterday[0], 4) if yesterday else None
    out["change_week"] = round(value - last_week[0], 4) if last_week else None

    pace: float | None = None
    first = _stored(db, indicator.id, from_moment=now - PACE_WINDOW)
    if first is not None:
        days = (now - first[1]).total_seconds() / 86400
        # Less than a day of history is not a pace: the hours after the
        # morning sync say nothing about a whole day.
        if days >= 1:
            pace = (value - first[0]) / days
            out["pace_days"] = round(days, 1)
    out["pace_per_day"] = round(pace, 4) if pace is not None else None

    target = indicator.target_value
    # A neutral indicator has no way it is meant to go, so nothing to reach.
    if target is None or indicator.direction == Direction.neutral:
        return out
    rising = indicator.direction == Direction.higher_is_better
    remaining = (target - value) if rising else (value - target)
    if remaining <= 0:
        out["reached"] = True
        return out
    toward = None if pace is None else (pace if rising else -pace)
    if toward is not None and toward > 0:
        if remaining / toward > PROJECTION_HORIZON.days:
            # Moving, but so slowly that the date it gets there is no date
            # anybody plans by - and a million days on is past the last date
            # Python can hold, which failed every tile on the page with it.
            out["projected_beyond"] = True
            if indicator.target_date:
                out["on_course"] = False
        else:
            projected = now + dt.timedelta(days=remaining / toward)
            out["projected_at"] = projected.isoformat()
            if indicator.target_date:
                out["on_course"] = projected.date() <= indicator.target_date
    if indicator.target_date:
        # Counting the day itself: a target "by the 30th" can still be worked
        # towards on the 30th.
        days_left = (indicator.target_date - now.date()).days + 1
        out["days_left"] = days_left
        if days_left > 0:
            out["needed_per_day"] = round(remaining / days_left, 4)
    return out


def refresh_indicator(db: Session, indicator: Indicator, store_snapshot: bool = True) -> dict:
    outcome = evaluate_indicator(db, indicator)
    indicator.last_value = outcome["value"]
    indicator.last_computed_at = utcnow()
    if store_snapshot:
        db.add(
            IndicatorSnapshot(
                indicator_id=indicator.id,
                value=outcome["value"],
                breakdown=outcome["breakdown"],
                computed_at=indicator.last_computed_at,
            )
        )
    db.flush()
    return outcome


def refresh_for_dataset(db: Session, dataset_id: str, store_snapshot: bool = False) -> int:
    """Recompute the indicators that read one dataset, its data having changed.

    An indicator tile shows the value the last scheduled run computed, because
    opening a board must not set a query going for every tile on it. That is
    the right trade while the data sits still and the wrong one the moment it
    moves: an import landed this morning's interviews and every tile went on
    showing yesterday's number until the quarter-hour tick came round, which
    reads as an import that did nothing.

    No snapshot by default. The snapshots are the indicator's trend, and that
    series is what the number was at each scheduled moment - five
    questionnaire versions importing one after another would otherwise punch
    five points into it inside a minute, four of them describing a dataset
    half way through being written.

    One indicator failing stops neither the others nor the import. An
    expression somebody mistyped belongs on the page where expressions are
    edited, and is no reason to refuse data that has already landed.
    """
    indicators = db.scalars(
        select(Indicator).where(
            Indicator.dataset_id == dataset_id, Indicator.is_active.is_(True)
        )
    ).all()
    refreshed = 0
    for indicator in indicators:
        try:
            refresh_indicator(db, indicator, store_snapshot=store_snapshot)
            refreshed += 1
        except Exception as exc:  # noqa: BLE001 - one bad spec must not stop the rest
            logger.warning(
                "Indicator '%s' did not refresh after the import: %s", indicator.name, exc
            )
    return refreshed


def evaluate_alert_rule(db: Session, rule: AlertRule) -> Alert | None:
    """Fire an alert when the rule's condition holds and the cooldown has passed."""
    if not rule.is_active or not rule.indicator_id:
        return None
    indicator = db.get(Indicator, rule.indicator_id)
    if indicator is None:
        return None

    value = indicator.last_value
    if value is None:
        return None

    condition = rule.condition or {}
    operator = str(condition.get("operator", "lt"))
    threshold = condition.get("value")
    comparator = COMPARATORS.get(operator)
    if comparator is None or threshold is None:
        return None

    try:
        triggered = comparator(float(value), float(threshold))
    except (TypeError, ValueError):
        return None

    if not triggered:
        # Auto-resolve any open alert once the metric recovers
        open_alerts = db.scalars(
            select(Alert).where(Alert.rule_id == rule.id, Alert.status == AlertStatus.open)
        ).all()
        for alert in open_alerts:
            alert.status = AlertStatus.resolved
            alert.resolved_at = utcnow()
        return None

    now = utcnow()
    if rule.last_triggered_at:
        last = rule.last_triggered_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.UTC)
        if (now - last).total_seconds() < rule.cooldown_minutes * 60:
            return None

    message = (
        f"{indicator.name} is {_format_value(value)}, which is {operator.upper()} the "
        f"threshold of {_format_value(float(threshold))}."
    )
    alert = Alert(
        rule_id=rule.id,
        title=rule.name,
        message=message,
        severity=rule.severity,
        status=AlertStatus.open,
        payload={
            "indicator_id": indicator.id,
            "indicator_name": indicator.name,
            "value": value,
            "threshold": threshold,
            "operator": operator,
        },
        created_at=now,
    )
    db.add(alert)
    rule.last_triggered_at = now
    db.flush()

    _dispatch_alert(db, rule, alert)
    return alert


def _format_value(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.2f}"


def _dispatch_alert(db: Session, rule: AlertRule, alert: Alert) -> None:
    channels = rule.channels or ["in_app"]
    if "in_app" in channels:
        recipients = _resolve_recipients(db, rule)
        for user_id in recipients:
            db.add(
                Notification(
                    user_id=user_id,
                    title=alert.title or "Alert",
                    body=alert.message,
                    level=alert.severity.value,
                    link="/monitoring/alerts",
                    created_at=utcnow(),
                )
            )
    if "email" in channels:
        from app.services.mailer import send_alert_email

        emails = _resolve_emails(db, rule)
        if emails:
            send_alert_email(emails, alert.title or "Alert", alert.message, alert.severity)


def _default_recipients(db: Session) -> list[User]:
    """With no explicit recipients, alerts go to everyone who can act on them."""
    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    return [u for u in users if u.has_role(Role.manager)]


def _resolve_recipients(db: Session, rule: AlertRule) -> list[str]:
    if rule.recipients:
        users = db.scalars(select(User).where(User.email.in_(rule.recipients))).all()
        return [u.id for u in users]
    return [u.id for u in _default_recipients(db)]


def _resolve_emails(db: Session, rule: AlertRule) -> list[str]:
    if rule.recipients:
        return list(rule.recipients)
    return [u.email for u in _default_recipients(db)]

