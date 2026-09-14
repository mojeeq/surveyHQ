"""Drill-down and exports for data-quality failures."""

from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from app.api.deps import DbSession, RequireAnalyst, get_ready_dataset
from app.models import Dataset, QualityResult, QualityRule
from app.services.audit import record
from app.services.quality_failures import FailureRows, failed_records
from app.services.query_engine import QueryError

router = APIRouter()

MAX_EXPORT_ROWS = 50_000


def _rule(
    rule_id: str,
    db: DbSession,
    user: RequireAnalyst,
) -> tuple[QualityRule, Dataset]:
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Quality rule not found")
    dataset = get_ready_dataset(rule.dataset_id, db, user)
    return rule, dataset


def _payload(rows: FailureRows, offset: int) -> dict[str, Any]:
    return {
        "columns": rows.columns,
        "rows": rows.rows,
        "total": rows.total,
        "offset": offset,
        "truncated": rows.truncated,
    }


def _safe_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    return clean or "quality"


def _safe_sheet(value: str, used: set[str]) -> str:
    base = re.sub(r"[\\/*?:\[\]]", "_", value).strip() or "Failures"
    base = base[:31]
    name = base
    number = 2
    while name.casefold() in used:
        suffix = f"_{number}"
        name = base[: 31 - len(suffix)] + suffix
        number += 1
    used.add(name.casefold())
    return name


def _latest_result(db: DbSession, rule_id: str) -> QualityResult | None:
    return db.scalar(
        select(QualityResult)
        .where(QualityResult.rule_id == rule_id)
        .order_by(QualityResult.run_at.desc())
        .limit(1)
    )


@router.get("/quality-rules/{rule_id}/failures", response_model=dict)
def quality_failures(
    rule_id: str,
    db: DbSession,
    user: RequireAnalyst,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Rows behind a quality finding, for inspection in the browser."""
    rule, dataset = _rule(rule_id, db, user)
    try:
        rows = failed_records(dataset, rule, limit=limit, offset=offset)
    except (QueryError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _payload(rows, offset)


@router.get("/quality-rules/{rule_id}/failures/export")
def export_quality_failures(
    rule_id: str,
    db: DbSession,
    user: RequireAnalyst,
    format: str = Query(default="xlsx", pattern="^(csv|xlsx)$"),
) -> Response:
    """Download the records implicated by one quality rule."""
    rule, dataset = _rule(rule_id, db, user)
    try:
        rows = failed_records(dataset, rule, limit=MAX_EXPORT_ROWS)
    except (QueryError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    frame = pd.DataFrame(rows.rows, columns=rows.columns)
    stem = _safe_filename(f"{dataset.name}_{rule.name}_failures")

    if format == "csv":
        raw = frame.to_csv(index=False).encode("utf-8-sig")
        media = "text/csv; charset=utf-8"
        filename = f"{stem}.csv"
    else:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            frame.to_excel(writer, sheet_name="Failures", index=False)
            summary = pd.DataFrame(
                [
                    {
                        "rule": rule.name,
                        "check_type": rule.check_type.value,
                        "dataset": dataset.name,
                        "matching_rows": rows.total,
                        "exported_rows": len(frame),
                        "truncated": rows.truncated,
                    }
                ]
            )
            summary.to_excel(writer, sheet_name="Summary", index=False)
        raw = buffer.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{stem}.xlsx"

    record(
        db,
        user=user,
        action="export_quality_failures",
        entity_type="quality_rule",
        entity_id=rule.id,
    )
    db.commit()
    return Response(
        content=raw,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/datasets/{dataset_id}/quality/export")
def export_quality_workbook(
    dataset_id: str,
    db: DbSession,
    user: RequireAnalyst,
) -> Response:
    """One workbook containing the quality summary and one sheet per rule."""
    dataset = get_ready_dataset(dataset_id, db, user)
    rules = list(
        db.scalars(
            select(QualityRule)
            .where(QualityRule.dataset_id == dataset_id)
            .order_by(QualityRule.created_at)
        ).all()
    )
    if not rules:
        raise HTTPException(
            status_code=409,
            detail="This dataset has no quality rules to export",
        )

    buffer = io.BytesIO()
    summary_rows: list[dict[str, Any]] = []
    used_sheets = {"summary"}

    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        for rule in rules:
            latest = _latest_result(db, rule.id)
            error = ""
            try:
                rows = failed_records(dataset, rule, limit=MAX_EXPORT_ROWS)
                frame = pd.DataFrame(rows.rows, columns=rows.columns)
                issue_rows = rows.total
                truncated = rows.truncated
            except Exception as exc:  # noqa: BLE001 - keep other rule sheets exportable
                frame = pd.DataFrame({"error": [str(exc)]})
                issue_rows = 0
                truncated = False
                error = str(exc)

            frame.to_excel(
                writer,
                sheet_name=_safe_sheet(rule.name, used_sheets),
                index=False,
            )
            summary_rows.append(
                {
                    "rule": rule.name,
                    "check_type": rule.check_type.value,
                    "severity": rule.severity.value,
                    "passed": latest.passed if latest else None,
                    "failed_rows": latest.failed_rows if latest else None,
                    "checked_rows": latest.total_rows if latest else None,
                    "failure_rate": latest.failure_rate if latest else None,
                    "matching_issue_rows": issue_rows,
                    "export_truncated": truncated,
                    "last_run": latest.run_at.isoformat() if latest else None,
                    "message": latest.message if latest else "Not run yet",
                    "export_error": error,
                }
            )

        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

    record(
        db,
        user=user,
        action="export_quality_workbook",
        entity_type="dataset",
        entity_id=dataset.id,
    )
    db.commit()
    filename = f"{_safe_filename(dataset.name)}_quality.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
