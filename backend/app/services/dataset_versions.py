"""Retained dataset snapshots. Publishing changes only the database pointer."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from uuid import uuid4

from app.services.ingest import IngestResult, VariableMeta


def describe(dataset) -> dict:
    return {
        "version": dataset.version,
        "parquet_path": dataset.storage_path,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "file_size": dataset.file_size,
        "variables": [
            {f.name: getattr(v, f.name) for f in fields(VariableMeta)} for v in dataset.variables
        ],
        "warnings": (dataset.meta or {}).get("warnings", []),
    }


def remember_version(dataset) -> None:
    if not dataset.storage_path or not Path(dataset.storage_path).is_file():
        return
    from app.services.datasets import dataset_directory

    directory = dataset_directory(dataset.id) / "versions"
    directory.mkdir(parents=True, exist_ok=True)
    # Paths are unique per snapshot; failed transactions never replace a
    # previously retained snapshot with uncommitted data.
    target = directory / f"{dataset.version}-{uuid4().hex}.json"
    target.write_text(json.dumps(describe(dataset)), encoding="utf-8")
    dataset.meta = {**(dataset.meta or {}), "retained_versions": [
        *((dataset.meta or {}).get("retained_versions") or []), str(target)
    ]}


def as_ingest(snapshot: dict) -> IngestResult:
    payload = {k: v for k, v in snapshot.items() if k != "version"}
    payload["parquet_path"] = Path(payload["parquet_path"])
    payload["variables"] = [VariableMeta(**v) for v in payload["variables"]]
    return IngestResult(**payload)


def list_versions(dataset) -> list[dict]:

    found = {}
    for filename in (dataset.meta or {}).get("retained_versions", []):
        file = Path(filename)
        if not file.is_file():
            continue
        snapshot = json.loads(file.read_text())
        # Uncommitted snapshots can only have the current/future version.
        if snapshot["version"] < dataset.version and Path(snapshot["parquet_path"]).is_file():
            found.setdefault(snapshot["version"], snapshot)
    return sorted(found.values(), key=lambda x: x["version"], reverse=True)
