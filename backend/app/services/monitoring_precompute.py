"""Versioned precomputed field-monitoring views beside each survey Parquet.

The important performance property is that field-progress calculations happen
once when data changes, rather than once per browser load.  The actual numbers
are still produced by field_progress.build_overview, so value labels, Stata
tagged missings, filters and all other statistical semantics have one canonical
implementation.
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

logger = get_logger(__name__)
SUMMARY_NAME = "monitoring-summary.json"


def _path(dataset: Any) -> Path:
    return Path(dataset.storage_path).parent / SUMMARY_NAME


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


def store(dataset: Any, overview: dict[str, Any]) -> dict[str, Any]:
    payload = _jsonable(
        {
            **overview,
            "dataset_version": int(dataset.version or 0),
        }
    )
    destination = _path(dataset)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, destination)
    return payload


def precompute(
    dataset: Any,
    builder: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    """Run the canonical unfiltered day overview once and persist it."""
    if not settings.monitoring_precompute_enabled or not dataset.storage_path:
        return None
    if not (dataset.meta or {}).get("monitoring_fields"):
        return None
    try:
        overview = builder(dataset, None, "day")
        return store(dataset, overview)
    except Exception as exc:  # noqa: BLE001 - acceleration must never block import
        logger.warning("Could not precompute monitoring summary for %s: %s", dataset.name, exc)
        return None


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
    """Serve the precomputed default view; preserve canonical ad-hoc views."""
    if grain != "day" or (filters is not None and not filters.is_empty()):
        return original(dataset, filters, grain)
    cached = load(dataset)
    if cached is None:
        cached = precompute(dataset, original)
    return cached if cached is not None else original(dataset, filters, grain)
