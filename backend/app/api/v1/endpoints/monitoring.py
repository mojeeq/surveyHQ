"""Indicators, alerts, data quality and field progress."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, select

from app.api.deps import (
    CurrentUser,
    DbSession,
    RequireManager,
    get_dataset,
    get_ready_dataset,
)
from app.db.base import utcnow
from app.models import (
    Alert,
    AlertRule,
    AlertStatus,
    Dataset,
    Direction,
    Indicator,
    IndicatorSnapshot,
    QualityResult,
    QualityRule,
    Severity,
    TargetSet,
    User,
)
from app.schemas.common import Message
from app.schemas.monitoring import (
    AlertOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    IndicatorCreate,
    IndicatorOut,
    IndicatorUpdate,
    IndicatorValue,
    QualityResultOut,
    QualityRuleCreate,
    QualityRuleOut,
    QualityRuleUpdate,
    QualityRuleWithResult,
    TargetSetCreate,
    TargetSetOut,
    TargetSetSummary,
    TargetSetUpdate,
)
from app.schemas.query import FilterGroup
from app.services.audit import record
from app.services.field_progress import build_overview
from app.services.monitoring import (
    breakdown_progress,
    evaluate_alert_rule,
    indicator_status,
    progress_percent,
    refresh_indicator,
)
from app.services.projects import (
    alert_rule_clause,
    can_view,
    dataset_clause,
    in_project_clause,
    restrict,
    scope_for,
)
from app.services.quality import execute_rule, suggested_rules

router = APIRouter()


# --- indicators ------------------------------------------------------------


@router.get("/indicators", response_model=list[IndicatorOut])
def list_indicators(
    db: DbSession,
    user: CurrentUser,
    dataset_id: str = "",
    project_id: str | None = None,
    active_only: bool = False,
) -> list[Indicator]:
    statement = restrict(
        select(Indicator).order_by(Indicator.display_order, Indicator.created_at),
        dataset_clause(db, user, Indicator.dataset_id),
    )
    if dataset_id:
        statement = statement.where(Indicator.dataset_id == dataset_id)
    if project_id is not None:
        statement = statement.where(in_project_clause(Indicator.dataset_id, project_id))
    if active_only:
        statement = statement.where(Indicator.is_active.is_(True))
    return list(db.scalars(statement).all())


@router.post("/indicators", response_model=IndicatorOut, status_code=201)
def create_indicator(
    payload: IndicatorCreate, db: DbSession, user: RequireManager
) -> Indicator:
    get_ready_dataset(payload.dataset_id, db, user)
    indicator = Indicator(
        name=payload.name,
        description=payload.description,
        dataset_id=payload.dataset_id,
        spec=payload.spec.model_dump(mode="json"),
        unit=payload.unit,
        value_format=payload.value_format,
        target_value=payload.target_value,
        warning_threshold=payload.warning_threshold,
        critical_threshold=payload.critical_threshold,
        direction=payload.direction,
        breakdown_variable=payload.breakdown_variable,
        breakdown_targets=payload.breakdown_targets,
        target_set_id=_linked_set(payload.target_set_id, payload.dataset_id, db, user),
        percent_of=payload.percent_of,
        display_order=payload.display_order,
    )
    db.add(indicator)
    db.flush()
    refresh_indicator(db, indicator)
    record(
        db, user=user, action="create_indicator", entity_type="indicator", entity_id=indicator.id
    )
    db.commit()
    db.refresh(indicator)
    return indicator


@router.patch("/indicators/{indicator_id}", response_model=IndicatorOut)
def update_indicator(
    indicator_id: str, payload: IndicatorUpdate, db: DbSession, user: RequireManager
) -> Indicator:
    indicator = _get_indicator(indicator_id, db, user)
    data = payload.model_dump(exclude_unset=True)
    if data.get("dataset_id") and data["dataset_id"] != indicator.dataset_id:
        # Moving it onto another dataset is a read of that dataset and a write
        # into whatever project holds it, so both ends are checked.
        get_dataset(data["dataset_id"], db, user)
    if "spec" in data and data["spec"] is not None:
        data["spec"] = payload.spec.model_dump(mode="json") if payload.spec else {}
    if "target_set_id" in data:
        # Checked against whichever dataset the indicator ends up on, so moving
        # an indicator and its set in one call is judged on the pair.
        data["target_set_id"] = _linked_set(
            data["target_set_id"], data.get("dataset_id") or indicator.dataset_id, db, user
        )
    for field, value in data.items():
        setattr(indicator, field, value)
    refresh_indicator(db, indicator, store_snapshot=False)
    db.commit()
    db.refresh(indicator)
    return indicator


@router.delete("/indicators/{indicator_id}", response_model=Message)
def delete_indicator(indicator_id: str, db: DbSession, user: RequireManager) -> Message:
    indicator = _get_indicator(indicator_id, db, user)
    db.delete(indicator)
    db.commit()
    return Message(detail="Indicator deleted")


@router.get("/indicators/values", response_model=list[IndicatorValue])
def indicator_values(
    db: DbSession,
    user: CurrentUser,
    dataset_id: str = "",
    project_id: str | None = None,
    refresh: bool = False,
    trend_points: int = Query(default=30, le=365),
) -> list[IndicatorValue]:
    """Current values for the monitoring scoreboard, with recent history."""
    statement = restrict(
        select(Indicator).where(Indicator.is_active.is_(True)),
        dataset_clause(db, user, Indicator.dataset_id),
    )
    if dataset_id:
        statement = statement.where(Indicator.dataset_id == dataset_id)
    if project_id is not None:
        statement = statement.where(in_project_clause(Indicator.dataset_id, project_id))
    indicators = list(
        db.scalars(statement.order_by(Indicator.display_order, Indicator.created_at)).all()
    )

    values: list[IndicatorValue] = []
    for indicator in indicators:
        error = None
        breakdown: dict[str, float] = {}
        truncated = False
        if refresh:
            outcome = refresh_indicator(db, indicator, store_snapshot=False)
            error = outcome.get("error")
            breakdown = outcome.get("breakdown") or {}
            truncated = bool(outcome.get("breakdown_truncated"))

        snapshots = db.scalars(
            select(IndicatorSnapshot)
            .where(IndicatorSnapshot.indicator_id == indicator.id)
            .order_by(IndicatorSnapshot.computed_at.desc())
            .limit(trend_points)
        ).all()
        trend = [
            {"t": s.computed_at.isoformat(), "v": s.value} for s in reversed(list(snapshots))
        ]

        values.append(
            IndicatorValue(
                indicator_id=indicator.id,
                name=indicator.name,
                value=indicator.last_value,
                unit=indicator.unit,
                value_format=indicator.value_format,
                target_value=indicator.target_value,
                progress_percent=progress_percent(indicator, indicator.last_value),
                status=indicator_status(indicator, indicator.last_value),
                direction=indicator.direction,
                breakdown=breakdown,
                breakdown_progress=breakdown_progress(indicator, breakdown),
                breakdown_truncated=bool(truncated),
                breakdown_variable=indicator.breakdown_variable,
                computed_at=indicator.last_computed_at,
                error=error,
                trend=trend,
            )
        )
    if refresh:
        db.commit()
    return values


@router.post("/indicators/{indicator_id}/refresh", response_model=IndicatorValue)
def refresh_single_indicator(
    indicator_id: str, db: DbSession, user: CurrentUser
) -> IndicatorValue:
    indicator = _get_indicator(indicator_id, db, user)
    outcome = refresh_indicator(db, indicator)
    db.commit()
    db.refresh(indicator)
    return IndicatorValue(
        indicator_id=indicator.id,
        name=indicator.name,
        value=indicator.last_value,
        unit=indicator.unit,
        value_format=indicator.value_format,
        target_value=indicator.target_value,
        progress_percent=progress_percent(indicator, indicator.last_value),
        status=indicator_status(indicator, indicator.last_value),
        direction=indicator.direction,
        breakdown=outcome.get("breakdown") or {},
        breakdown_progress=breakdown_progress(indicator, outcome.get("breakdown") or {}),
        breakdown_truncated=bool(outcome.get("breakdown_truncated")),
        breakdown_variable=indicator.breakdown_variable,
        computed_at=indicator.last_computed_at,
        error=outcome.get("error"),
    )


def _get_indicator(indicator_id: str, db: DbSession, user: User) -> Indicator:
    """An indicator the caller may reach, by way of its dataset.

    Filtering the listing is not enough on its own: these routes take an id
    directly, so without this an indicator on another project's dataset stays
    readable and editable to anyone who knows its id.
    """
    indicator = db.get(Indicator, indicator_id)
    if indicator is None:
        raise HTTPException(status_code=404, detail="Indicator not found")
    get_dataset(indicator.dataset_id, db, user)
    return indicator


# --- alerts ----------------------------------------------------------------


def _get_alert_rule(rule_id: str, db: DbSession, user: User) -> AlertRule:
    """An alert rule the caller may reach, by way of what it watches.

    A rule hangs off an indicator, or off a dataset directly, or off neither -
    and each of those decides its project. Filtering the listing is not enough:
    every route below takes an id, so without this a rule watching another
    project's indicator stays readable, editable and deletable by anyone who
    knows its id.
    """
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    if rule.indicator_id:
        indicator = db.get(Indicator, rule.indicator_id)
        if indicator is not None:
            get_dataset(indicator.dataset_id, db, user)
            return rule
    if rule.dataset_id:
        get_dataset(rule.dataset_id, db, user)
        return rule
    # Tied to nothing in particular: a global rule, which lives in the shared
    # area and follows the same rule as an unassigned dataset.
    if not can_view(db, user, None):
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return rule


def _get_alert(alert_id: str, db: DbSession, user: User) -> Alert:
    """An alert the caller may reach, by way of the rule that raised it."""
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.rule_id:
        try:
            _get_alert_rule(alert.rule_id, db, user)
        except HTTPException:
            # Say what the caller can verify: the alert is not theirs to see.
            raise HTTPException(status_code=404, detail="Alert not found") from None
    elif not can_view(db, user, None):
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


# --- target sets -----------------------------------------------------------
#
# A quota list is prepared before fieldwork, by somebody who is not watching a
# dashboard, and read by several indicators at once. Kept inside an indicator
# it had to be retyped for each of them. Here it is a record of its own.


def _get_target_set(set_id: str, db: DbSession, user: User) -> TargetSet:
    found = db.get(TargetSet, set_id)
    if found is None or not can_view(db, user, found.dataset_id):
        # Not found rather than forbidden, so a reader cannot learn which ids
        # exist in a project they are not in.
        raise HTTPException(status_code=404, detail="Target set not found")
    return found


def _linked_set(
    set_id: str | None, dataset_id: str, db: DbSession, user: User
) -> str | None:
    """The set an indicator may link to: one the caller can see, on its dataset.

    A set belongs to the dataset whose categories it names, so linking an
    indicator to a set built on another dataset would key quotas by values
    that cannot appear in it.
    """
    if not set_id:
        return None
    found = _get_target_set(set_id, db, user)
    if found.dataset_id != dataset_id:
        raise HTTPException(
            status_code=400,
            detail="That target set belongs to a different dataset",
        )
    return found.id


@router.get("/target-sets", response_model=list[TargetSetSummary])
def list_target_sets(
    db: DbSession,
    user: CurrentUser,
    dataset_id: str = "",
    project_id: str | None = None,
) -> list[TargetSetSummary]:
    """Every set the caller can see, without the rows.

    A census set holds two thousand quotas and a list page needs none of them:
    how many categories it covers and what they add up to is what says whether
    it is the one you are looking for.
    """
    statement = restrict(
        select(TargetSet).order_by(TargetSet.name),
        dataset_clause(db, user, TargetSet.dataset_id),
    )
    if dataset_id:
        statement = statement.where(TargetSet.dataset_id == dataset_id)
    if project_id is not None:
        statement = statement.where(in_project_clause(TargetSet.dataset_id, project_id))
    sets = list(db.scalars(statement).all())

    names = dict(
        db.execute(
            select(Dataset.id, Dataset.name).where(
                Dataset.id.in_({one.dataset_id for one in sets})
            )
        ).all()
    )
    used = dict(
        db.execute(
            select(Indicator.target_set_id, func.count(Indicator.id))
            .where(Indicator.target_set_id.in_({one.id for one in sets}))
            .group_by(Indicator.target_set_id)
        ).all()
    )
    return [
        TargetSetSummary(
            id=one.id,
            name=one.name,
            description=one.description,
            dataset_id=one.dataset_id,
            dataset_name=names.get(one.dataset_id, ""),
            variable=one.variable,
            categories=len(one.targets or {}),
            total=sum(_as_number(value) for value in (one.targets or {}).values()),
            used_by=used.get(one.id, 0),
            updated_at=one.updated_at,
        )
        for one in sets
    ]


@router.post("/target-sets", response_model=TargetSetOut, status_code=201)
def create_target_set(
    payload: TargetSetCreate, db: DbSession, user: RequireManager
) -> TargetSet:
    get_ready_dataset(payload.dataset_id, db, user)
    created = TargetSet(
        name=payload.name,
        description=payload.description,
        dataset_id=payload.dataset_id,
        variable=payload.variable,
        targets=payload.targets,
    )
    db.add(created)
    db.flush()
    record(
        db,
        user=user,
        action="create_target_set",
        entity_type="target_set",
        entity_id=created.id,
        detail={"categories": len(payload.targets)},
    )
    db.commit()
    db.refresh(created)
    return created


@router.get("/target-sets/{set_id}", response_model=TargetSetOut)
def read_target_set(set_id: str, db: DbSession, user: CurrentUser) -> TargetSet:
    return _get_target_set(set_id, db, user)


@router.patch("/target-sets/{set_id}", response_model=TargetSetOut)
def update_target_set(
    set_id: str, payload: TargetSetUpdate, db: DbSession, user: RequireManager
) -> TargetSet:
    found = _get_target_set(set_id, db, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(found, field, value)
    record(
        db,
        user=user,
        action="update_target_set",
        entity_type="target_set",
        entity_id=found.id,
        detail={"categories": len(found.targets or {})},
    )
    db.commit()
    db.refresh(found)
    return found


@router.delete("/target-sets/{set_id}", response_model=Message)
def delete_target_set(set_id: str, db: DbSession, user: RequireManager) -> Message:
    found = _get_target_set(set_id, db, user)
    # The indicators reading it keep working: the link clears and each falls
    # back to whatever quotas it carries itself, which is nothing for most.
    using = db.scalars(
        select(Indicator).where(Indicator.target_set_id == found.id)
    ).all()
    for indicator in using:
        indicator.target_set_id = None
    db.delete(found)
    record(
        db,
        user=user,
        action="delete_target_set",
        entity_type="target_set",
        entity_id=set_id,
        detail={"indicators_unlinked": len(using)},
    )
    db.commit()
    return Message(detail=f"Target set deleted. {len(using)} indicator(s) unlinked.")


def _as_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0



@router.get("/alert-rules", response_model=list[AlertRuleOut])
def list_alert_rules(
    db: DbSession, user: CurrentUser, project_id: str | None = None
) -> list[AlertRule]:
    statement = restrict(
        select(AlertRule).order_by(AlertRule.created_at.desc()),
        alert_rule_clause(db, user),
    )
    if project_id is not None:
        statement = statement.where(_rules_in_project(project_id))
    return list(db.scalars(statement).all())


def _rules_in_project(project_id: str) -> Any:
    """Alert rules belonging to one project, through whatever they are tied to.

    A rule names a dataset, an indicator, or neither; the last is a global rule
    and belongs to the shared area, which is what an empty project id asks for.
    """
    clause = AlertRule.dataset_id.in_(
        select(Dataset.id).where(
            Dataset.project_id == project_id if project_id else Dataset.project_id.is_(None)
        )
    ) | AlertRule.indicator_id.in_(
        select(Indicator.id).where(in_project_clause(Indicator.dataset_id, project_id))
    )
    if not project_id:
        clause = clause | (AlertRule.dataset_id.is_(None) & AlertRule.indicator_id.is_(None))
    return clause


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=201)
def create_alert_rule(
    payload: AlertRuleCreate, db: DbSession, user: RequireManager
) -> AlertRule:
    if payload.indicator_id:
        _get_indicator(payload.indicator_id, db, user)
    if payload.dataset_id:
        get_dataset(payload.dataset_id, db, user)
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    record(db, user=user, action="create_alert_rule", entity_type="alert_rule")
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleOut)
def update_alert_rule(
    rule_id: str, payload: AlertRuleUpdate, db: DbSession, user: RequireManager
) -> AlertRule:
    rule = _get_alert_rule(rule_id, db, user)
    changes = payload.model_dump(exclude_unset=True)
    # Moving a rule onto another project's indicator or dataset is a write to
    # that project, so it is checked against the destination as well.
    if changes.get("indicator_id"):
        _get_indicator(changes["indicator_id"], db, user)
    if changes.get("dataset_id"):
        get_dataset(changes["dataset_id"], db, user)
    for field, value in changes.items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/alert-rules/{rule_id}", response_model=Message)
def delete_alert_rule(rule_id: str, db: DbSession, user: RequireManager) -> Message:
    rule = _get_alert_rule(rule_id, db, user)
    db.delete(rule)
    db.commit()
    return Message(detail="Alert rule deleted")


@router.post("/alert-rules/{rule_id}/test", response_model=dict)
def test_alert_rule(rule_id: str, db: DbSession, user: RequireManager) -> dict[str, Any]:
    """Evaluate a rule right now without waiting for the scheduler."""
    rule = _get_alert_rule(rule_id, db, user)
    if rule.indicator_id:
        indicator = db.get(Indicator, rule.indicator_id)
        if indicator:
            refresh_indicator(db, indicator, store_snapshot=False)
    alert = evaluate_alert_rule(db, rule)
    db.commit()
    return {
        "triggered": alert is not None,
        "message": alert.message if alert else "The condition is not met right now.",
    }


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    db: DbSession,
    user: CurrentUser,
    status: AlertStatus | None = None,
    severity: Severity | None = None,
    project_id: str | None = None,
    limit: int = Query(default=100, le=500),
) -> list[Alert]:
    # An alert is visible through the rule that raised it. One whose rule has
    # been deleted has nothing left to scope it by, so only an admin sees it.
    clause = alert_rule_clause(db, user)
    statement = restrict(
        select(Alert).order_by(Alert.created_at.desc()).limit(limit),
        None if clause is None else Alert.rule_id.in_(select(AlertRule.id).where(clause)),
    )
    if status:
        statement = statement.where(Alert.status == status)
    if severity:
        statement = statement.where(Alert.severity == severity)
    if project_id is not None:
        # An alert reaches a project through the rule that raised it.
        statement = statement.where(
            Alert.rule_id.in_(select(AlertRule.id).where(_rules_in_project(project_id)))
        )
    return list(db.scalars(statement).all())


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(alert_id: str, db: DbSession, user: CurrentUser) -> Alert:
    alert = _get_alert(alert_id, db, user)
    alert.status = AlertStatus.acknowledged
    alert.acknowledged_at = utcnow()
    alert.acknowledged_by = user.id
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: str, db: DbSession, user: CurrentUser) -> Alert:
    alert = _get_alert(alert_id, db, user)
    alert.status = AlertStatus.resolved
    alert.resolved_at = utcnow()
    db.commit()
    db.refresh(alert)
    return alert


# --- data quality ----------------------------------------------------------


@router.get("/quality-rules", response_model=list[QualityRuleWithResult])
def list_quality_rules(
    db: DbSession, user: CurrentUser, dataset_id: str = "", project_id: str | None = None
) -> list[QualityRuleWithResult]:
    statement = restrict(
        select(QualityRule).order_by(QualityRule.created_at.desc()),
        dataset_clause(db, user, QualityRule.dataset_id),
    )
    if dataset_id:
        statement = statement.where(QualityRule.dataset_id == dataset_id)
    if project_id is not None:
        statement = statement.where(in_project_clause(QualityRule.dataset_id, project_id))
    rules = list(db.scalars(statement).all())

    output: list[QualityRuleWithResult] = []
    for rule in rules:
        latest = db.scalar(
            select(QualityResult)
            .where(QualityResult.rule_id == rule.id)
            .order_by(QualityResult.run_at.desc())
            .limit(1)
        )
        item = QualityRuleWithResult.model_validate(rule)
        item.latest_result = QualityResultOut.model_validate(latest) if latest else None
        output.append(item)
    return output


@router.post("/quality-rules", response_model=QualityRuleOut, status_code=201)
def create_quality_rule(
    payload: QualityRuleCreate, db: DbSession, user: RequireManager
) -> QualityRule:
    get_ready_dataset(payload.dataset_id, db, user)
    rule = QualityRule(**payload.model_dump())
    db.add(rule)
    db.flush()
    execute_rule(db, rule)
    record(db, user=user, action="create_quality_rule", entity_type="quality_rule")
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/quality-rules/{rule_id}", response_model=QualityRuleOut)
def update_quality_rule(
    rule_id: str, payload: QualityRuleUpdate, db: DbSession, user: RequireManager
) -> QualityRule:
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Quality rule not found")
    # A rule is reachable through its dataset, like everything else that hangs
    # off one; without this, a rule on a dataset the caller cannot see is still
    # editable by id.
    get_dataset(rule.dataset_id, db, user)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.flush()
    # Re-run it: the stored result describes the old definition, and leaving it
    # there would report a pass or a failure for a check that no longer exists.
    execute_rule(db, rule)
    record(
        db,
        user=user,
        action="update_quality_rule",
        entity_type="quality_rule",
        entity_id=rule.id,
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/quality-rules/{rule_id}", response_model=Message)
def delete_quality_rule(rule_id: str, db: DbSession, user: RequireManager) -> Message:
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Quality rule not found")
    get_dataset(rule.dataset_id, db, user)
    db.delete(rule)
    db.commit()
    return Message(detail="Quality rule deleted")


@router.post("/quality-rules/{rule_id}/run", response_model=QualityResultOut)
def run_quality_rule(rule_id: str, db: DbSession, user: CurrentUser) -> QualityResult:
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Quality rule not found")
    # Running a check reports failing rows and examples from the data, so this
    # is a read of the dataset and scoped like one.
    get_dataset(rule.dataset_id, db, user)
    result = execute_rule(db, rule)
    db.commit()
    db.refresh(result)
    return result


@router.post("/datasets/{dataset_id}/quality/run-all", response_model=list[QualityResultOut])
def run_all_quality_rules(
    dataset_id: str, db: DbSession, user: CurrentUser
) -> list[QualityResult]:
    get_dataset(dataset_id, db, user)
    rules = db.scalars(
        select(QualityRule).where(
            QualityRule.dataset_id == dataset_id, QualityRule.is_active.is_(True)
        )
    ).all()
    results = [execute_rule(db, rule) for rule in rules]
    db.commit()
    for result in results:
        db.refresh(result)
    return results


@router.get("/datasets/{dataset_id}/quality/suggestions", response_model=list[dict])
def quality_suggestions(
    dataset_id: str, db: DbSession, user: CurrentUser
) -> list[dict[str, Any]]:
    """Checks the platform recommends for this dataset, ready to accept."""
    dataset = get_dataset(dataset_id, db, user)
    return suggested_rules(dataset)


@router.get("/quality-results", response_model=list[QualityResultOut])
def list_quality_results(
    db: DbSession, user: CurrentUser, rule_id: str = "", limit: int = Query(default=50, le=500)
) -> list[QualityResult]:
    # A result is reachable through the rule that produced it, and a rule
    # through its dataset. Without this, failure counts and offending-row
    # details from another project's data would be readable here.
    rules = dataset_clause(db, user, QualityRule.dataset_id)
    statement = restrict(
        select(QualityResult).order_by(QualityResult.run_at.desc()).limit(limit),
        None if rules is None else QualityResult.rule_id.in_(
            select(QualityRule.id).where(rules)
        ),
    )
    if rule_id:
        statement = statement.where(QualityResult.rule_id == rule_id)
    return list(db.scalars(statement).all())


# --- field progress --------------------------------------------------------


@router.post("/datasets/{dataset_id}/field-progress", response_model=dict)
def field_progress(
    dataset_id: str,
    db: DbSession,
    user: CurrentUser,
    filters: FilterGroup | None = None,
    grain: str = Query(default="day", pattern="^(day|week|month|quarter|year)$"),
) -> dict[str, Any]:
    """Ready-made field monitoring views derived from the dataset's own columns."""
    dataset = get_ready_dataset(dataset_id, db, user)
    return build_overview(dataset, filters, grain)


@router.get("/summary", response_model=dict)
def monitoring_summary(
    db: DbSession, user: CurrentUser, project_id: str | None = None
) -> dict[str, Any]:
    """Headline numbers for the landing page, counting only what this user sees.

    project_id narrows every count to one project - `none` for the shared area
    - so the overview answers "how is this round going" rather than only "how
    is everything going".
    """
    scoped = project_id is not None
    target = "" if project_id == "none" else (project_id or "")
    recent_cutoff = utcnow() - dt.timedelta(days=7)

    rules = alert_rule_clause(db, user)
    alert_statement = restrict(
        select(Alert.id.label("id"), Alert.severity.label("severity")).where(
            Alert.status == AlertStatus.open
        ),
        None if rules is None else Alert.rule_id.in_(select(AlertRule.id).where(rules)),
    )
    if project_id is not None:
        alert_statement = alert_statement.where(
            Alert.rule_id.in_(
                select(AlertRule.id).where(
                    in_project_clause(
                        AlertRule.dataset_id, "" if project_id == "none" else project_id
                    )
                    | AlertRule.indicator_id.in_(
                        select(Indicator.id).where(
                            in_project_clause(
                                Indicator.dataset_id,
                                "" if project_id == "none" else project_id,
                            )
                        )
                    )
                )
            )
        )
    alerts = alert_statement.subquery()
    open_alerts, critical_alerts = db.execute(
        select(
            func.count(alerts.c.id),
            func.coalesce(
                func.sum(
                    case((alerts.c.severity == Severity.critical, 1), else_=0)
                ),
                0,
            ),
        )
    ).one()

    status = case(
        (Indicator.last_value.is_(None), "unknown"),
        (
            Indicator.warning_threshold.is_(None) & Indicator.critical_threshold.is_(None),
            "ok",
        ),
        (
            (Indicator.direction == Direction.lower_is_better)
            & Indicator.critical_threshold.is_not(None)
            & (Indicator.last_value >= Indicator.critical_threshold),
            "critical",
        ),
        (
            (Indicator.direction == Direction.lower_is_better)
            & Indicator.warning_threshold.is_not(None)
            & (Indicator.last_value >= Indicator.warning_threshold),
            "warning",
        ),
        (
            (Indicator.direction == Direction.higher_is_better)
            & Indicator.critical_threshold.is_not(None)
            & (Indicator.last_value <= Indicator.critical_threshold),
            "critical",
        ),
        (
            (Indicator.direction == Direction.higher_is_better)
            & Indicator.warning_threshold.is_not(None)
            & (Indicator.last_value <= Indicator.warning_threshold),
            "warning",
        ),
        else_="ok",
    )
    indicator_statement = restrict(
        select(Indicator.id.label("id"), status.label("status")).where(
            Indicator.is_active.is_(True)
        ),
        dataset_clause(db, user, Indicator.dataset_id),
    )
    if scoped:
        indicator_statement = indicator_statement.where(
            in_project_clause(Indicator.dataset_id, target)
        )
    indicators = indicator_statement.subquery()
    (
        indicator_count,
        indicators_ok,
        indicators_warning,
        indicators_critical,
    ) = db.execute(
        select(
            func.count(indicators.c.id),
            func.coalesce(
                func.sum(case((indicators.c.status == "ok", 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((indicators.c.status == "warning", 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((indicators.c.status == "critical", 1), else_=0)),
                0,
            ),
        )
    ).one()

    dataset_statement = restrict(
        select(
            Dataset.id.label("id"),
            Dataset.row_count.label("row_count"),
            Dataset.refreshed_at.label("refreshed_at"),
        ),
        scope_for(db, user).filter(Dataset.project_id),
    )
    if scoped:
        dataset_statement = dataset_statement.where(Dataset.project_id == (target or None))
    datasets = dataset_statement.subquery()
    datasets_count, total_records, recently_refreshed = db.execute(
        select(
            func.count(datasets.c.id),
            func.coalesce(func.sum(datasets.c.row_count), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            datasets.c.refreshed_at.is_not(None)
                            & (datasets.c.refreshed_at >= recent_cutoff),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
    ).one()

    quality = dataset_clause(db, user, QualityRule.dataset_id)
    if scoped:
        in_project = in_project_clause(QualityRule.dataset_id, target)
        quality = in_project if quality is None else (quality & in_project)
    failing_checks = (
        restrict(
            select(QualityResult)
            .where(QualityResult.passed.is_(False))
            .order_by(QualityResult.run_at.desc())
            .limit(100),
            None
            if quality is None
            else QualityResult.rule_id.in_(select(QualityRule.id).where(quality)),
        ).subquery()
    )
    failing_quality_checks = (
        db.scalar(select(func.count(func.distinct(failing_checks.c.rule_id)))) or 0
    )

    return {
        "datasets": int(datasets_count or 0),
        "total_records": int(total_records or 0),
        "indicators": int(indicator_count or 0),
        "indicators_ok": int(indicators_ok or 0),
        "indicators_warning": int(indicators_warning or 0),
        "indicators_critical": int(indicators_critical or 0),
        "open_alerts": int(open_alerts or 0),
        "critical_alerts": int(critical_alerts or 0),
        "failing_quality_checks": int(failing_quality_checks),
        "recently_refreshed": int(recently_refreshed or 0),
    }
