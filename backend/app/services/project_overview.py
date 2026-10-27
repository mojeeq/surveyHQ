"""A project, read as the pipeline it is.

A survey round's work was spread across six pages: where its data comes from
on Connections, its datasets on Datasets, how they join on the project's
Relationships tab, its script on another tab, its dashboards on Dashboards,
and what is being watched on four more. Following one import from the server
to the board meant visiting all of them, and nothing anywhere said that a
merge on the way had not been rebuilt.

This puts it in the order the data travels - in, joined, prepared, shown,
watched - with whatever needs somebody's attention gathered at the top.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (
    Alert,
    AlertRule,
    Connection,
    Dashboard,
    Dataset,
    Indicator,
    ProjectScript,
    QualityResult,
    QualityRule,
)
from app.models.monitoring import AlertStatus
from app.services import freshness, stata
from app.services.scheduling import next_due


def _iso(moment: Any) -> str | None:
    return moment.isoformat() if moment is not None else None


def overview(db: Session, project_id: str) -> dict[str, Any]:
    datasets = list(db.scalars(select(Dataset).where(Dataset.project_id == project_id)).all())
    by_id = {dataset.id: dataset for dataset in datasets}
    scripts = list(
        db.scalars(
            select(ProjectScript)
            .where(ProjectScript.project_id == project_id)
            .order_by(ProjectScript.created_at, ProjectScript.id)
        ).all()
    )
    written = {one for script in scripts for one in script.writes or []}
    attention: list[dict[str, str]] = []

    # In: the connections feeding the project, and what they bring.
    now = utcnow()
    imports = []
    for connection in db.scalars(
        select(Connection).where(Connection.project_id == project_id)
    ).all():
        due = (
            next_due(
                mode=connection.sync_mode or "interval",
                times=list(connection.sync_times or []),
                timezone=connection.sync_timezone or "UTC",
                interval_minutes=connection.sync_interval_minutes,
                last_sync_at=connection.last_sync_at,
                now=now,
            )
            if connection.is_active and connection.sync_enabled
            else None
        )
        status = getattr(connection.last_sync_status, "value", str(connection.last_sync_status))
        imports.append(
            {
                "id": connection.id,
                "name": connection.name,
                "kind": getattr(connection.source_kind, "value", str(connection.source_kind)),
                "last_sync_at": _iso(connection.last_sync_at),
                "last_sync_status": status,
                "last_sync_error": connection.last_sync_error or "",
                "next_import_at": _iso(due),
            }
        )
        if status == "failed":
            attention.append(
                {
                    "kind": "import",
                    "title": f"The last import from {connection.name} failed",
                    "detail": connection.last_sync_error or "",
                    "link": "/connections",
                }
            )

    sources = [
        {
            "id": dataset.id,
            "name": dataset.name,
            "rows": dataset.row_count or 0,
            "refreshed_at": _iso(dataset.refreshed_at),
            "paradata": "paradata" in (dataset.tags or []),
            "from_connection": bool(dataset.connection_id),
        }
        for dataset in datasets
        if (dataset.derivation or {}).get("type") != "merge" and dataset.id not in written
    ]

    # Joined: each merge, and whether it kept up with its sources.
    merges = []
    for dataset in datasets:
        derivation = dataset.derivation or {}
        if derivation.get("type") != "merge":
            continue
        rebuild = (dataset.meta or {}).get("rebuild") or {}
        status = rebuild.get("status") or "rebuilt"
        merges.append(
            {
                "id": dataset.id,
                "name": dataset.name,
                "from": dataset.source_ref or "",
                "rows": dataset.row_count or 0,
                "refreshed_at": _iso(dataset.refreshed_at),
                "status": status,
                "message": rebuild.get("message") or "",
            }
        )
        if status != "rebuilt":
            attention.append(
                {
                    "kind": "merge",
                    "title": f"'{dataset.name}' was not rebuilt from the latest data",
                    "detail": rebuild.get("message") or "",
                    "link": f"/datasets/{dataset.id}",
                }
            )

    # Prepared: the scripts, and whether the next import will run each.
    prepared: list[dict[str, Any]] = []
    for script in scripts:
        saved = bool(script.text.strip())
        link = f"/scripts?script={script.id}"
        prepared.append(
            {
                "id": script.id,
                "name": script.name,
                "saved": saved,
                "commands": len(
                    stata.commands(script.text if saved else script.last_run_text or "")
                ),
                "last_run_at": _iso(script.last_run_at),
                "last_error": script.last_error or "",
                "reads": [by_id[i].name for i in script.reads or [] if i in by_id],
                "writes": [by_id[i].name for i in script.writes or [] if i in by_id],
                "runs_on_import": saved and bool(script.reads),
            }
        )
        if script.last_error:
            attention.append(
                {
                    "kind": "script",
                    "title": f"The last run of '{script.name}' failed",
                    "detail": script.last_error,
                    "link": link,
                }
            )
        elif not saved and script.reads:
            attention.append(
                {
                    "kind": "script",
                    "title": (
                        f"'{script.name}' has run but was never saved, so imports "
                        "do not re-run it"
                    ),
                    "detail": "Open it and run it once, or save it.",
                    "link": link,
                }
            )

    # Shown: the boards, and how old the data under each is.
    boards = []
    for dashboard in db.scalars(
        select(Dashboard).where(Dashboard.project_id == project_id).order_by(Dashboard.name)
    ).all():
        fresh = freshness.board(db, list(dashboard.widgets))
        boards.append(
            {
                "id": dashboard.id,
                "name": dashboard.name,
                "widgets": len(dashboard.widgets),
                "imported_at": fresh["imported_at"],
                "next_import_at": fresh["next_import_at"],
            }
        )

    # Watched: indicators, what is alarming, what is failing its checks.
    ids = list(by_id)
    indicators = (
        list(db.scalars(select(Indicator).where(Indicator.dataset_id.in_(ids))).all())
        if ids
        else []
    )
    indicator_ids = [one.id for one in indicators]
    rule_ids: list[str] = []
    if ids:
        clauses = [AlertRule.dataset_id.in_(ids)]
        if indicator_ids:
            clauses.append(AlertRule.indicator_id.in_(indicator_ids))
        rule_ids = list(db.scalars(select(AlertRule.id).where(or_(*clauses))).all())
    open_alerts = (
        len(
            db.scalars(
                select(Alert.id).where(
                    Alert.rule_id.in_(rule_ids), Alert.status == AlertStatus.open
                )
            ).all()
        )
        if rule_ids
        else 0
    )
    checks = (
        list(
            db.scalars(
                select(QualityRule).where(
                    QualityRule.dataset_id.in_(ids), QualityRule.is_active.is_(True)
                )
            ).all()
        )
        if ids
        else []
    )
    failing = 0
    for check in checks:
        latest = db.scalars(
            select(QualityResult)
            .where(QualityResult.rule_id == check.id)
            .order_by(QualityResult.run_at.desc())
            .limit(1)
        ).first()
        if latest is not None and not latest.passed:
            failing += 1
    if open_alerts:
        attention.append(
            {
                "kind": "alert",
                "title": f"{open_alerts} open alert(s)",
                "detail": "",
                "link": "/alerts",
            }
        )

    return {
        "attention": attention,
        "imports": imports,
        "sources": sources,
        "merges": merges,
        "scripts": prepared,
        "outputs": [
            {"id": i, "name": by_id[i].name, "rows": by_id[i].row_count or 0}
            for i in dict.fromkeys(one for script in scripts for one in script.writes or [])
            if i in by_id
        ],
        "dashboards": boards,
        "watching": {
            "indicators": len(indicators),
            "open_alerts": open_alerts,
            "checks": len(checks),
            "failing_checks": failing,
        },
    }
