"""Indicators, alerts, data quality and field progress."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

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
    Indicator,
    IndicatorSnapshot,
    QualityResult,
    QualityRule,
    Severity,
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
)
from app.schemas.query import FilterGroup
from app.services.audit import record
from app.services.field_progress import build_overview
from app.services.monitoring import (
    evaluate_alert_rule,
    indicator_status,
    progress_percent,
    refresh_indicator,
)
from app.services.projects import (
    alert_rule_clause,
    dataset_clause,
    restrict,
    scope_for,
)
from app.services.quality import execute_rule, suggested_rules

router = APIRouter()


# --- indicators ------------------------------------------------------------


@router.get("/indicators", response_model=list[IndicatorOut])
def list_indicators(
    db: DbSession, user: CurrentUser, dataset_id: str = "", active_only: bool = False
) -> list[Indicator]:
    statement = restrict(
        select(Indicator).order_by(Indicator.display_order, Indicator.created_at),
        dataset_clause(db, user, Indicator.dataset_id),
    )
    if dataset_id:
        statement = statement.where(Indicator.dataset_id == dataset_id)
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
    indicator_id: str, payload: IndicatorUpdate, db: DbSession, _: RequireManager
) -> Indicator:
    indicator = _get_indicator(indicator_id, db)
    data = payload.model_dump(exclude_unset=True)
    if "spec" in data and data["spec"] is not None:
        data["spec"] = payload.spec.model_dump(mode="json") if payload.spec else {}
    for field, value in data.items():
        setattr(indicator, field, value)
    refresh_indicator(db, indicator, store_snapshot=False)
    db.commit()
    db.refresh(indicator)
    return indicator


@router.delete("/indicators/{indicator_id}", response_model=Message)
def delete_indicator(indicator_id: str, db: DbSession, _: RequireManager) -> Message:
    indicator = _get_indicator(indicator_id, db)
    db.delete(indicator)
    db.commit()
    return Message(detail="Indicator deleted")


@router.get("/indicators/values", response_model=list[IndicatorValue])
def indicator_values(
    db: DbSession,
    user: CurrentUser,
    dataset_id: str = "",
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
    indicators = list(
        db.scalars(statement.order_by(Indicator.display_order, Indicator.created_at)).all()
    )

    values: list[IndicatorValue] = []
    for indicator in indicators:
        error = None
        breakdown: dict[str, float] = {}
        if refresh:
            outcome = refresh_indicator(db, indicator, store_snapshot=False)
            error = outcome.get("error")
            breakdown = outcome.get("breakdown") or {}

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
    indicator_id: str, db: DbSession, _: CurrentUser
) -> IndicatorValue:
    indicator = _get_indicator(indicator_id, db)
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
        computed_at=indicator.last_computed_at,
        error=outcome.get("error"),
    )


def _get_indicator(indicator_id: str, db: DbSession) -> Indicator:
    indicator = db.get(Indicator, indicator_id)
    if indicator is None:
        raise HTTPException(status_code=404, detail="Indicator not found")
    return indicator


# --- alerts ----------------------------------------------------------------


@router.get("/alert-rules", response_model=list[AlertRuleOut])
def list_alert_rules(db: DbSession, user: CurrentUser) -> list[AlertRule]:
    statement = restrict(
        select(AlertRule).order_by(AlertRule.created_at.desc()),
        alert_rule_clause(db, user),
    )
    return list(db.scalars(statement).all())


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=201)
def create_alert_rule(
    payload: AlertRuleCreate, db: DbSession, user: RequireManager
) -> AlertRule:
    if payload.indicator_id:
        _get_indicator(payload.indicator_id, db)
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    record(db, user=user, action="create_alert_rule", entity_type="alert_rule")
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleOut)
def update_alert_rule(
    rule_id: str, payload: AlertRuleUpdate, db: DbSession, _: RequireManager
) -> AlertRule:
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/alert-rules/{rule_id}", response_model=Message)
def delete_alert_rule(rule_id: str, db: DbSession, _: RequireManager) -> Message:
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    db.delete(rule)
    db.commit()
    return Message(detail="Alert rule deleted")


@router.post("/alert-rules/{rule_id}/test", response_model=dict)
def test_alert_rule(rule_id: str, db: DbSession, _: RequireManager) -> dict[str, Any]:
    """Evaluate a rule right now without waiting for the scheduler."""
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
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
    return list(db.scalars(statement).all())


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(alert_id: str, db: DbSession, user: CurrentUser) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.acknowledged
    alert.acknowledged_at = utcnow()
    alert.acknowledged_by = user.id
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: str, db: DbSession, _: CurrentUser) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.resolved
    alert.resolved_at = utcnow()
    db.commit()
    db.refresh(alert)
    return alert


# --- data quality ----------------------------------------------------------


@router.get("/quality-rules", response_model=list[QualityRuleWithResult])
def list_quality_rules(
    db: DbSession, user: CurrentUser, dataset_id: str = ""
) -> list[QualityRuleWithResult]:
    statement = restrict(
        select(QualityRule).order_by(QualityRule.created_at.desc()),
        dataset_clause(db, user, QualityRule.dataset_id),
    )
    if dataset_id:
        statement = statement.where(QualityRule.dataset_id == dataset_id)
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
    rule_id: str, payload: QualityRuleUpdate, db: DbSession, _: RequireManager
) -> QualityRule:
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Quality rule not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/quality-rules/{rule_id}", response_model=Message)
def delete_quality_rule(rule_id: str, db: DbSession, _: RequireManager) -> Message:
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Quality rule not found")
    db.delete(rule)
    db.commit()
    return Message(detail="Quality rule deleted")


@router.post("/quality-rules/{rule_id}/run", response_model=QualityResultOut)
def run_quality_rule(rule_id: str, db: DbSession, _: CurrentUser) -> QualityResult:
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Quality rule not found")
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
    db: DbSession, _: CurrentUser, rule_id: str = "", limit: int = Query(default=50, le=500)
) -> list[QualityResult]:
    statement = select(QualityResult).order_by(QualityResult.run_at.desc()).limit(limit)
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
def monitoring_summary(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Headline numbers for the landing page, counting only what this user sees."""
    rules = alert_rule_clause(db, user)
    open_alerts = db.scalars(
        restrict(
            select(Alert).where(Alert.status == AlertStatus.open).limit(500),
            None if rules is None else Alert.rule_id.in_(select(AlertRule.id).where(rules)),
        )
    ).all()
    indicators = db.scalars(
        restrict(
            select(Indicator).where(Indicator.is_active.is_(True)),
            dataset_clause(db, user, Indicator.dataset_id),
        )
    ).all()
    datasets = db.scalars(
        restrict(select(Dataset), scope_for(db, user).filter(Dataset.project_id))
    ).all()

    quality = dataset_clause(db, user, QualityRule.dataset_id)
    failing_checks = db.scalars(
        restrict(
            select(QualityResult)
            .where(QualityResult.passed.is_(False))
            .order_by(QualityResult.run_at.desc())
            .limit(100),
            None
            if quality is None
            else QualityResult.rule_id.in_(select(QualityRule.id).where(quality)),
        )
    ).all()

    statuses = [indicator_status(i, i.last_value) for i in indicators]
    recent_cutoff = utcnow() - dt.timedelta(days=7)
    return {
        "datasets": len(datasets),
        "total_records": sum(d.row_count for d in datasets),
        "indicators": len(indicators),
        "indicators_ok": statuses.count("ok"),
        "indicators_warning": statuses.count("warning"),
        "indicators_critical": statuses.count("critical"),
        "open_alerts": len(open_alerts),
        "critical_alerts": len(
            [a for a in open_alerts if a.severity == Severity.critical]
        ),
        "failing_quality_checks": len({r.rule_id for r in failing_checks}),
        "recently_refreshed": len(
            [
                d
                for d in datasets
                if d.refreshed_at and d.refreshed_at.replace(tzinfo=dt.UTC)
                >= recent_cutoff
            ]
        ),
    }
