"""Runtime wiring for fast DuckDB queries and version-aware Redis caching.

Kept outside query_engine so the compiler stays deterministic and easy to test.
The API and Celery entry points install this once before importing endpoint/task
modules; every caller that subsequently imports execute_query receives the cached
wrapper, while all query-engine SQL uses the configured DuckDB connection.
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
    if not settings.analytics_cache_enabled:
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
    """Install configured DuckDB resources and cache aggregate query results."""
    global _installed
    if _installed:
        return
    with _lock:
        if _installed:
            return
        from app.services import query_engine

        query_engine._connect = columnar.connect
        original: Callable[..., QueryResult] = query_engine.execute_query

        def cached_execute_query(ctx: Any, spec: Any) -> QueryResult:
            # Contexts built in older tests do not carry a version. They still
            # work; production contexts do, and therefore invalidate precisely.
            key = _key(ctx, spec)
            cached = _get(key)
            if cached is not None:
                return cached
            result = original(ctx, spec)
            _put(key, result)
            return result

        cached_execute_query.__name__ = original.__name__
        cached_execute_query.__doc__ = original.__doc__
        setattr(cached_execute_query, "__surveyhq_cached__", True)
        query_engine.execute_query = cached_execute_query
        _installed = True
