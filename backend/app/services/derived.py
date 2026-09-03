"""Datasets built from other datasets, and keeping them current.

A merge produces a real dataset with its own id, which charts, indicators and
dashboards then point at. When the data underneath is replaced by a newer
export, that merged dataset is the one thing that does not move - it still
holds the join of last month's files, and nothing on screen says so. So a
replacement re-runs every merge that stands on what was replaced.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Dataset, DatasetRelationship
from app.services.datasets import _apply_ingest, dataset_directory
from app.services.ingest import ingest_frame
from app.services.relationships import merge_frames

logger = get_logger(__name__)


def run_merge(
    db: Session,
    target: Dataset,
    relationship: DatasetRelationship,
    left: Dataset,
    right: Dataset,
) -> None:
    """Join left to right per the target's stored derivation, into the target."""
    derivation = target.derivation or {}
    frame = merge_frames(
        left,
        right,
        relationship.left_variable,
        relationship.right_variable,
        how=derivation.get("how", "left"),
        columns=derivation.get("columns") or None,
        prefix=derivation.get("prefix", ""),
    )

    labels = {v.name: v.label for v in left.variables if v.label}
    value_labels = {v.name: v.value_labels for v in left.variables if v.value_labels}
    prefix = derivation.get("prefix", "")
    for variable in right.variables:
        alias = f"{prefix}{variable.name}" if prefix else variable.name
        if variable.label:
            labels.setdefault(alias, variable.label)
        if variable.value_labels:
            value_labels.setdefault(alias, variable.value_labels)

    warnings: list[str] = []
    if derivation.get("how") == "left" and len(frame) > left.row_count:
        # A left join that grows the row count means the right side had several
        # matches per key, which is a fact about the data worth stating.
        warnings.append(
            f"The join produced {len(frame):,} rows from {left.row_count:,}, because "
            f"'{right.name}' has more than one row per key. Each left row is repeated."
        )
    _apply_ingest(
        db,
        target,
        ingest_frame(frame, labels, value_labels, dataset_directory(target.id), warnings),
    )


def sources_of(
    db: Session, dataset: Dataset
) -> tuple[DatasetRelationship, Dataset, Dataset] | None:
    """The relationship and the two datasets a merged dataset was built from."""
    derivation = dataset.derivation or {}
    if derivation.get("type") != "merge":
        return None
    relationship = db.get(DatasetRelationship, derivation.get("relationship_id"))
    if relationship is None:
        return None
    left = db.get(Dataset, relationship.left_dataset_id)
    right = db.get(Dataset, relationship.right_dataset_id)
    if left is None or right is None:
        return None
    return relationship, left, right


def rebuild_dependents(db: Session, changed_ids: list[str]) -> list[str]:
    """Re-run every merge standing on the given datasets, and report what ran.

    A merge of a merge has to wait for the one below it, so this works outwards
    in rounds: each round rebuilds what is now stale, and the datasets it
    rebuilt are themselves changed for the next round. Bounded by the number of
    derived datasets, which also stops a relationship cycle from looping here.
    """
    if not changed_ids:
        return []

    derived = [
        dataset
        for dataset in db.scalars(select(Dataset)).all()
        if (dataset.derivation or {}).get("type") == "merge"
    ]
    if not derived:
        return []

    stale = set(changed_ids)
    rebuilt: list[str] = []
    for _ in range(len(derived)):
        progressed = False
        for dataset in derived:
            if dataset.id in rebuilt:
                continue
            sources = sources_of(db, dataset)
            if sources is None:
                continue
            relationship, left, right = sources
            if left.id not in stale and right.id not in stale:
                continue
            try:
                run_merge(db, dataset, relationship, left, right)
            except Exception as exc:  # noqa: BLE001 - one bad merge must not
                # abandon the rest of the upload, and the dataset keeps the data
                # it had rather than being left empty.
                logger.warning("Could not rebuild '%s': %s", dataset.name, exc)
                continue
            rebuilt.append(dataset.id)
            stale.add(dataset.id)
            progressed = True
        if not progressed:
            break
    return rebuilt
