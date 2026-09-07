"""Saving a boundary layer and reading it back.

The geometry lives as GeoJSON on disk, whatever it arrived as, and is read
back through a small cache. A monitoring dashboard asks the same national
frame the same question on every refresh, and parsing megabytes of coordinates
each time is work nobody sees the result of.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.boundaries import Areas

# Enough for the frames one deployment works with at once - a national one and
# a few survey-specific ones - keyed so a re-uploaded layer is never served
# from a previous version of itself.
_CACHE: dict[tuple[str, float], tuple[list[dict[str, Any]], Areas]] = {}
MAX_CACHED = 8


def path_for(layer_id: str) -> Path:
    return settings.boundaries_path / f"{layer_id}.geojson"


def save(layer_id: str, features: list[dict[str, Any]]) -> tuple[Path, int]:
    """Write the layer as a GeoJSON feature collection; return where and how big."""
    settings.boundaries_path.mkdir(parents=True, exist_ok=True)
    path = path_for(layer_id)
    payload = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(payload), encoding="utf-8")
    _CACHE.pop(_key(path), None)
    return path, path.stat().st_size


def remove(layer_id: str) -> None:
    path = path_for(layer_id)
    _CACHE.pop(_key(path), None)
    path.unlink(missing_ok=True)


def _key(path: Path) -> tuple[str, float]:
    # The modification time is part of the key, so a layer replaced on disk is
    # a different entry rather than a stale one.
    try:
        return str(path), path.stat().st_mtime
    except OSError:
        return str(path), 0.0


def load(path: str | Path) -> tuple[list[dict[str, Any]], Areas]:
    """The layer's features and its prepared index, cached by file and mtime."""
    path = Path(path)
    key = _key(path)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], Areas([])
    features = payload.get("features") or []
    prepared = (features, Areas(features))
    if len(_CACHE) >= MAX_CACHED:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = prepared
    return prepared


def clear_cache() -> None:
    _CACHE.clear()
