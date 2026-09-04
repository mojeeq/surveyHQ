"""A fixed-window rate limiter, shared across workers when Redis is reachable.

The platform runs two uvicorn workers behind nginx, so a counter held in one
process enforces roughly twice the limit it is set to. Redis is already here for
Celery, so the count lives there and every worker sees the same one. If Redis is
unavailable the limiter falls back to per-process counting rather than failing
open: a doubled limit is still a limit, and a login endpoint that stops working
because a cache is down is a worse outcome than a slightly loose one.

Fixed windows, not a sliding log: a caller can spend two windows' worth of
attempts across a window boundary. For "stop a password being guessed a million
times" and "stop a public dashboard being scraped flat out" the difference does
not matter, and the counter is one INCR rather than a sorted set per caller.
"""

from __future__ import annotations

import threading
import time

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_KEY_PREFIX = "ratelimit:"

# Per-process fallback: {key: (window_started, count)}
_local: dict[str, tuple[float, int]] = {}
_local_lock = threading.Lock()

_redis_client = None
_redis_checked = False


def _redis():  # type: ignore[no-untyped-def]
    """The shared Redis client, or None if it cannot be reached.

    Looked up once. A limiter that retried a dead Redis on every request would
    add its connection timeout to every login attempt.
    """
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        client.ping()
        _redis_client = client
    except Exception as exc:  # noqa: BLE001 - any failure means fall back
        logger.warning("Rate limiting is per-process; Redis is unreachable: %s", exc)
        _redis_client = None
    return _redis_client


def _hit_local(key: str, window: int) -> int:
    now = time.monotonic()
    with _local_lock:
        started, count = _local.get(key, (now, 0))
        if now - started >= window:
            started, count = now, 0
        count += 1
        _local[key] = (started, count)
        if len(_local) > 10_000:
            # Keys are cheap but not free, and nothing else prunes them.
            cutoff = now - window
            for stale in [k for k, (s, _) in _local.items() if s < cutoff]:
                del _local[stale]
        return count


def reset() -> None:
    """Forget every count held in this process. For tests."""
    with _local_lock:
        _local.clear()


def hits(key: str, window_seconds: int) -> int:
    """Record one use of key and return how many there have been this window."""
    client = _redis()
    if client is None:
        return _hit_local(key, window_seconds)
    try:
        full = f"{_KEY_PREFIX}{key}"
        count = int(client.incr(full))
        if count == 1:
            # Set the expiry on the call that created the key, rather than with
            # EXPIRE NX, which needs Redis 7. Without this a key would live for
            # ever and the first window would be the only one.
            client.expire(full, window_seconds)
        return count
    except Exception as exc:  # noqa: BLE001 - a cache failure must not 500
        logger.warning("Rate limit counter failed, falling back locally: %s", exc)
        return _hit_local(key, window_seconds)


def enforce(key: str, limit: int, window_seconds: int, message: str) -> None:
    """Raise 429 once key has been used more than limit times this window."""
    if not settings.rate_limit_enabled:
        return
    if hits(key, window_seconds) > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message,
            headers={"Retry-After": str(window_seconds)},
        )
