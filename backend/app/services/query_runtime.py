"""Runtime wiring for SurveyHQ's high-throughput data paths.

The compiler and file readers remain independently testable; the API and Celery
entry points install this layer once before importing endpoint/task modules.
That gives every production caller configured DuckDB resources, version-aware
query caching, columnar append/merge, batched metadata scans, direct large CSV
parsing and precomputed field monitoring without duplicating endpoint contracts.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Callable

import redis

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.query import QueryResult
from app.services import columnar

logger = get_logger(__name__)
_lock = threading.Lock()
_installed = False
_client: redis.Redis | None = None


def _redis() -> redis.Redis | None:
    global _client
    # Unit/integration test legs deliberately run without a Redis service. The
    # cache is an accelerator, never a correctness dependency, so avoid a failed
    # TCP connect on every test query.
    if not settings.analytics_cache_enabled or settings.environment.lower() in {"test", "testing"}:
        return None
    if _client is None:
        _client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
            health_check_interval=30,
        )
    return _client


def _key(ctx: Any, spec: Any) -> str:
    # Dataset version is part of the key, so importing new data invalidates the
    # old cache without an expensive key scan or explicit purge operation.
    payload = json.dumps(
        spec.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    version = int(getattr(ctx, "version", 0) or 0)
    return f"surveyhq:q:{ctx.dataset_id}:v{version}:{digest}"


def _get(key: str) -> QueryResult | None:
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if not raw:
            return None
        result = QueryResult.model_validate_json(raw)
        # duration_ms describes this request, not the original cache fill.
        result.duration_ms = 0
        return result
    except Exception as exc:  # noqa: BLE001 - cache failure must never break analysis
        logger.debug("Analytics cache read failed: %s", exc)
        return None


def _put(key: str, result: QueryResult) -> None:
    client = _redis()
    if client is None:
        return
    try:
        client.setex(
            key,
            max(1, settings.analytics_cache_ttl_seconds),
            result.model_dump_json().encode("utf-8"),
        )
    except Exception as exc:  # noqa: BLE001 - Redis is an accelerator, not a dependency
        logger.debug("Analytics cache write failed: %s", exc)


def install_query_runtime() -> None:
    """Install all performance accelerators once per API/worker process."""
    global _installed
    if _installed:
        return
    with _lock:
        if _installed:
            return

        # Query execution --------------------------------------------------
        from app.services import query_engine

        query_engine._connect = columnar.connect
        original_execute: Callable[..., QueryResult] = query_engine.execute_query
        original_from_model = query_engine.DatasetContext.from_model

        @classmethod
        def versioned_context(cls: Any, dataset: Any) -> Any:
            ctx = original_from_model(dataset)
            # DatasetContext is intentionally a small dataclass and not slotted,
            # so the version can travel with it without changing every test that
            # constructs one directly.
            ctx.version = int(getattr(dataset, "version", 0) or 0)
            return ctx

        query_engine.DatasetContext.from_model = versioned_context

        def cached_execute_query(ctx: Any, spec: Any) -> QueryResult:
            key = _key(ctx, spec)
            cached = _get(key)
            if cached is not None:
                return cached
            result = original_execute(ctx, spec)
            _put(key, result)
            return result

        cached_execute_query.__name__ = original_execute.__name__
        cached_execute_query.__doc__ = original_execute.__doc__
        setattr(cached_execute_query, "__surveyhq_cached__", True)
        query_engine.execute_query = cached_execute_query

        # Ingest / metadata ------------------------------------------------
        from app.services import fast_ingest, ingest

        original_ingest_file = ingest.ingest_file
        ingest.build_metadata_from_parquet = fast_ingest.build_metadata_from_parquet_fast
        ingest.dataframe_preview = fast_ingest.dataframe_preview_fast

        def ingest_file(source: Any, destination_dir: Any) -> Any:
            return fast_ingest.ingest_file_fast(source, destination_dir, original_ingest_file)

        ingest.ingest_file = ingest_file

        # Datasets imports ingest_file by name, so import it only after the
        # ingest module is patched. Internal calls resolve _apply_ingest and
        # append_frame_into_dataset from its module globals at execution time.
        from app.services import datasets, monitoring_precompute

        original_apply_ingest = datasets._apply_ingest

        def apply_ingest_with_summary(db: Any, dataset: Any, result: Any) -> Any:
            ready = original_apply_ingest(db, dataset, result)
            if settings.monitoring_precompute_enabled:
                monitoring_precompute.build(ready)
            return ready

        datasets._apply_ingest = apply_ingest_with_summary
        datasets.append_frame_into_dataset = fast_ingest.append_frame_fast

        # Derived merges now COPY their join result directly to Parquet instead
        # of fetchall() -> DataFrame -> PyArrow -> Parquet.
        from app.services import derived

        derived.run_merge = fast_ingest.run_merge_fast

        # The unfiltered day-grain field overview is precomputed on each import.
        # Filtered views continue through the canonical query engine.
        from app.services import field_progress

        original_build_overview = field_progress.build_overview

        def build_overview(
            dataset: Any, filters: Any = None, grain: str = "day"
        ) -> dict[str, Any]:
            return monitoring_precompute.build_overview_fast(
                dataset, original_build_overview, filters, grain
            )

        field_progress.build_overview = build_overview
        _installed = True
