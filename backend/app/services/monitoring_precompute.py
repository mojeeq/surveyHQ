"""Small precomputed field-monitoring views beside each survey Parquet.

Monitoring asks the same handful of questions after every refresh. Computing
those once, from the freshly written Parquet, makes the monitoring page a JSON
read rather than six independent GROUP BY scans. Filtered/ad-hoc views still
fall back to the normal query engine so semantics are unchanged.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services import columnar

logger = get_logger(__name__)
SUMMARY_NAME = "monitoring-summary.json"


def _path(dataset: Any) -> Path:
    return Path(dataset.storage_path).parent / SUMMARY_NAME


def _variable(dataset: Any, name: str) -> Any | None:
    return next((item for item in dataset.variables if item.name == name), None)


def _label(dataset: Any, variable: str, value: Any) -> Any:
    row = _variable(dataset, variable)
    labels = (row.value_labels if row is not None else None) or {}
    if not labels or value is None:
        return value
    key: Any = value
    if isinstance(value, float) and value.is_integer():
        key = int(value)
    return labels.get(str(key), value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _rows(con: Any, sql: str) -> tuple[list[str], list[list[Any]]]:
    cursor = con.execute(sql)
    names = [item[0] for item in cursor.description or []]
    return names, [list(row) for row in cursor.fetchall()]


def _dicts(con: Any, sql: str) -> list[dict[str, Any]]:
    names, rows = _rows(con, sql)
    return [dict(zip(names, row, strict=False)) for row in rows]


def build(dataset: Any) -> dict[str, Any] | None:
    if not settings.monitoring_precompute_enabled or not dataset.storage_path:
        return None
    fields = dict((dataset.meta or {}).get("monitoring_fields", {}))
    if not fields:
        return None

    source = f"read_parquet({columnar.quote_path(dataset.storage_path)})"
    con = columnar.connect()
    try:
        result: dict[str, Any] = {
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "dataset_version": int(dataset.version or 0),
            "total_records": int(dataset.row_count or 0),
            "detected_fields": fields,
            "available_views": [],
        }

        status = fields.get("status")
        if status:
            q = columnar.quote_ident(status)
            rows = _dicts(
                con,
                f"SELECT {q} AS status, COUNT(*) AS count FROM {source} "
                f"GROUP BY 1 ORDER BY count DESC NULLS LAST LIMIT 50",
            )
            for row in rows:
                row["status"] = _label(dataset, status, row.get("status"))
            result["status_breakdown"] = rows
            if rows:
                result["available_views"].append("status_breakdown")

        date = fields.get("date")
        if date:
            q = columnar.quote_ident(date)
            rows = _dicts(
                con,
                f"SELECT date_trunc('day', try_cast({q} AS TIMESTAMP)) AS period, "
                f"COUNT(*) AS count FROM {source} GROUP BY 1 "
                f"HAVING period IS NOT NULL ORDER BY period ASC LIMIT 2000",
            )
            running = 0
            for row in rows:
                running += int(row.get("count") or 0)
                row["cumulative"] = running
            result["submissions_over_time"] = rows
            if rows:
                result["available_views"].append("submissions_over_time")

        duration = fields.get("duration")
        duration_expr = None
        if duration:
            duration_expr = f"try_cast({columnar.quote_ident(duration)} AS DOUBLE)"

        for key, output in (("interviewer", "by_interviewer"), ("supervisor", "by_supervisor")):
            variable = fields.get(key)
            if not variable:
                continue
            q = columnar.quote_ident(variable)
            measures = "COUNT(*) AS interviews"
            if duration_expr:
                measures += (
                    f", AVG({duration_expr}) AS mean_duration, "
                    f"MEDIAN({duration_expr}) AS median_duration"
                )
            rows = _dicts(
                con,
                f"SELECT {q} AS {columnar.quote_ident(key)}, {measures} FROM {source} "
                f"GROUP BY 1 ORDER BY interviews DESC NULLS LAST LIMIT 50",
            )
            for row in rows:
                row[key] = _label(dataset, variable, row.get(key))
            result[output] = rows
            if rows:
                result["available_views"].append(output)

        region = fields.get("region")
        if region:
            q = columnar.quote_ident(region)
            rows = _dicts(
                con,
                f"SELECT {q} AS area, COUNT(*) AS interviews FROM {source} "
                f"GROUP BY 1 ORDER BY interviews DESC NULLS LAST LIMIT 100",
            )
            for row in rows:
                row["area"] = _label(dataset, region, row.get("area"))
            result["coverage_by_area"] = rows
            if rows:
                result["available_views"].append("coverage_by_area")

        latitude = fields.get("latitude")
        longitude = fields.get("longitude")
        if latitude and longitude:
            lat = columnar.quote_ident(latitude)
            lon = columnar.quote_ident(longitude)
            extras: list[tuple[str, str]] = []
            for key in ("interview_key", "interviewer", "status"):
                name = fields.get(key)
                if name:
                    extras.append((key, name))
            selected = f"{lat} AS lat, {lon} AS lon" + "".join(
                f", {columnar.quote_ident(name)} AS {columnar.quote_ident(key)}"
                for key, name in extras
            )
            rows = _dicts(
                con,
                f"SELECT {selected} FROM {source} WHERE {lat} IS NOT NULL AND {lon} IS NOT NULL "
                f"AND {lat} BETWEEN -90 AND 90 AND {lon} BETWEEN -180 AND 180 "
                f"AND NOT ({lat} = 0 AND {lon} = 0) LIMIT 5000",
            )
            for row in rows:
                for key, name in extras:
                    row[key] = _label(dataset, name, row.get(key))
            result["geo_points"] = rows
            if rows:
                result["available_views"].append("geo_points")

        completed = 0
        for row in result.get("status_breakdown") or []:
            label = str(row.get("status") or "").lower()
            if "complet" in label or "approv" in label:
                completed += int(row.get("count") or 0)
        result["completed_records"] = completed
        total = int(dataset.row_count or 0)
        result["completion_rate"] = round(completed / total * 100, 2) if total else None

        payload = _jsonable(result)
        destination = _path(dataset)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, destination)
        return payload
    except Exception as exc:  # noqa: BLE001 - monitoring acceleration is optional
        logger.warning("Could not precompute monitoring summary for %s: %s", dataset.name, exc)
        return None
    finally:
        con.close()


def load(dataset: Any) -> dict[str, Any] | None:
    path = _path(dataset)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if int(payload.get("dataset_version") or -1) != int(dataset.version or 0):
        return None
    return payload


def build_overview_fast(
    dataset: Any,
    original: Callable[..., dict[str, Any]],
    filters: Any = None,
    grain: str = "day",
) -> dict[str, Any]:
    # The precomputed file represents the unfiltered day-grain overview. Any
    # filter or other grain is still computed by the canonical query path.
    if grain != "day" or (filters is not None and not filters.is_empty()):
        return original(dataset, filters, grain)
    cached = load(dataset)
    if cached is None:
        cached = build(dataset)
    return cached if cached is not None else original(dataset, filters, grain)
