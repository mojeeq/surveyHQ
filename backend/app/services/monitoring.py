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
    Severity,
    User,
)
from app.schemas.query import Dimension, QuerySpec
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


def evaluate_indicator(db: Session, indicator: Indicator) -> dict[str, Any]:
    """Compute an indicator's current value plus its optional breakdown."""
    dataset = db.get(Dataset, indicator.dataset_id)
    if dataset is None or not dataset_is_queryable(dataset):
        return {"value": None, "error": "Dataset is not available", "breakdown": {}}

    ctx = DatasetContext.from_model(dataset)
    try:
        spec = QuerySpec.model_validate(indicator.spec or {})
    except Exception as exc:  # noqa: BLE001 - stored spec may predate a schema change
        return {"value": None, "error": f"Invalid indicator definition: {exc}", "breakdown": {}}

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
    if indicator.breakdown_variable:
        breakdown_spec = spec.model_copy(
            update={
                "dimensions": [Dimension(variable=indicator.breakdown_variable)],
                "limit": 200,
            }
        )
        try:
            breakdown_result = execute_query(ctx, breakdown_spec)
            for row in breakdown_result.rows:
                key = "(missing)" if row[0] is None else str(row[0])
                breakdown[key] = float(row[1]) if row[1] is not None else 0.0
        except QueryError as exc:
            logger.warning("Breakdown failed for indicator %s: %s", indicator.name, exc)

    return {"value": value, "breakdown": breakdown, "error": None}


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


def severity_rank(severity: Severity) -> int:
    return {Severity.info: 0, Severity.warning: 1, Severity.critical: 2}[severity]
