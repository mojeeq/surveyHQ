"""Datasets built from other datasets, and keeping them current.

A merge produces a real dataset with its own id, which charts, indicators and
dashboards then point at. When the data underneath is replaced by a newer
export, that merged dataset is the one thing that does not move - it still
holds the join of last month's files, and nothing on screen says so. So a
replacement re-runs every merge that stands on what was replaced.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import Dataset, DatasetRelationship
from app.models.relationship import KeyMatch
from app.services.datasets import _apply_ingest, dataset_directory
from app.services.ingest import ingest_frame
from app.services.relationships import merge_frames, unmatched_warning

logger = get_logger(__name__)


@dataclass
class Join:
    """What a merge joins on.

    Held by the merged dataset itself, not only by the relationship it was
    made from. It used to be a pointer to that relationship and nothing else,
    so deleting the relationship - or clearing a project's relationships and
    detecting them again, which makes new ones with new ids - left every merge
    built on it with no recipe. Each import then passed it over without a
    word, and it went on holding the join of whatever export it was last built
    from while the data under it moved on.
    """

    left_variable: str
    right_variable: str
    key_match: KeyMatch


@dataclass
class MergeOutcome:
    """What became of one merged dataset when the data under it changed."""

    dataset_id: str
    name: str
    # rebuilt: built again from the new data. failed: tried, and the join
    # refused. stuck: could not be tried, because what it is built from is
    # gone - `message` says what.
    status: str
    message: str = ""


def run_merge(
    db: Session,
    target: Dataset,
    relationship: DatasetRelationship | Join,
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
        match=relationship.key_match,
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

    warnings: list[str] = unmatched_warning(
        left,
        right,
        relationship.left_variable,
        relationship.right_variable,
        relationship.key_match,
    )
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
) -> tuple[Join, Dataset, Dataset] | None:
    """The join and the two datasets a merged dataset was built from."""
    found = recipe(db, dataset)
    return None if isinstance(found, str) else found


def recipe(db: Session, dataset: Dataset) -> tuple[Join, Dataset, Dataset] | str:
    """How to build this merged dataset again, or why that cannot be done.

    Three places to find it, in order. The relationship it was made from, while
    that exists: correcting the relationship's key is how somebody fixes a
    merge, so it wins. Otherwise the recipe copied onto the dataset the last
    time it was built. Otherwise - a merge made before recipes were copied,
    whose relationship has since gone - the two datasets it names, and the one
    relationship between them now, if there is exactly one.

    Whatever is found is copied onto the dataset, so the next import needs
    nothing but the dataset.
    """
    derivation = dataset.derivation or {}
    if derivation.get("type") != "merge":
        return f"'{dataset.name}' is not a merge"

    relationship = db.get(DatasetRelationship, derivation.get("relationship_id"))
    if relationship is not None:
        left = db.get(Dataset, relationship.left_dataset_id)
        right = db.get(Dataset, relationship.right_dataset_id)
        if left is not None and right is not None:
            join = Join(
                relationship.left_variable, relationship.right_variable, relationship.key_match
            )
            _pin(dataset, join, left, right, relationship.id)
            return join, left, right

    if derivation.get("left_dataset_id"):
        left = db.get(Dataset, derivation["left_dataset_id"])
        right = db.get(Dataset, derivation.get("right_dataset_id"))
        gone = [
            derivation.get(f"{side}_name") or "a dataset"
            for side, found in (("left", left), ("right", right))
            if found is None
        ]
        if gone or left is None or right is None:
            return (
                f"'{' and '.join(gone)}', which it is built from, no longer exists. "
                "Delete this merge, or make it again from the datasets there are now."
            )
        join = Join(
            derivation.get("left_variable", ""),
            derivation.get("right_variable", ""),
            KeyMatch(derivation.get("key_match") or KeyMatch.exact.value),
        )
        return join, left, right

    return _recover(db, dataset)


def _recover(db: Session, dataset: Dataset) -> tuple[Join, Dataset, Dataset] | str:
    """Find the recipe of a merge made before recipes were copied onto it.

    All it kept was the relationship's id, and that relationship is gone. What
    it still has is the names it was built from, written as "left + right"
    when it was made. A merge of a merge has a " + " inside one of those names
    too, so every split is tried and only one that names two datasets of this
    project counts.
    """
    named = (dataset.source_ref or "").split(" + ")
    siblings = {
        one.name: one
        for one in db.scalars(
            select(Dataset).where(Dataset.project_id == dataset.project_id)
        ).all()
        if one.id != dataset.id
    }
    pairs = [
        (siblings[" + ".join(named[:cut])], siblings[" + ".join(named[cut:])])
        for cut in range(1, len(named))
        if " + ".join(named[:cut]) in siblings and " + ".join(named[cut:]) in siblings
    ]
    if len(pairs) != 1:
        return (
            "The relationship it was built from was deleted, and the datasets it "
            f"was made from ({dataset.source_ref or 'not recorded'}) cannot be "
            "found by name. Make the merge again from the Relationships view."
        )
    left, right = pairs[0]

    candidates: list[tuple[Join, str]] = []
    for one in db.scalars(select(DatasetRelationship)).all():
        if (one.left_dataset_id, one.right_dataset_id) == (left.id, right.id):
            candidates.append((Join(one.left_variable, one.right_variable, one.key_match), one.id))
        elif (one.left_dataset_id, one.right_dataset_id) == (right.id, left.id):
            # The same link drawn the other way round; the merge keeps its
            # own left and right, so the keys swap rather than the datasets.
            candidates.append((Join(one.right_variable, one.left_variable, one.key_match), one.id))
    if len(candidates) != 1:
        problem = (
            "There is no relationship between them now"
            if not candidates
            else "There are several relationships between them now, and nothing says which"
        )
        return (
            f"The relationship between '{left.name}' and '{right.name}' it was built "
            f"from was deleted. {problem}: define the one it should use in the "
            "Relationships view, and it will be rebuilt on the next import."
        )
    join, relationship_id = candidates[0]
    _pin(dataset, join, left, right, relationship_id)
    return join, left, right


def _pin(
    dataset: Dataset, join: Join, left: Dataset, right: Dataset, relationship_id: str
) -> None:
    """Copy the recipe onto the merged dataset, so it outlives the relationship."""
    derivation = dict(dataset.derivation or {})
    pinned = {
        "relationship_id": relationship_id,
        "left_dataset_id": left.id,
        "right_dataset_id": right.id,
        "left_name": left.name,
        "right_name": right.name,
        "left_variable": join.left_variable,
        "right_variable": join.right_variable,
        "key_match": getattr(join.key_match, "value", str(join.key_match)),
    }
    if any(derivation.get(key) != value for key, value in pinned.items()):
        dataset.derivation = {**derivation, **pinned}


def note(dataset: Dataset, status: str, message: str = "") -> None:
    """Write how the last rebuild went onto the merged dataset.

    Where the dataset card can read it. A merge that could not be rebuilt
    looked exactly like one that had been - same name, same badge - and the
    only sign was a date nobody compares with anything.
    """
    meta = dict(dataset.meta or {})
    meta["rebuild"] = {"status": status, "message": message, "at": utcnow().isoformat()}
    dataset.meta = meta


def rebuild_dependents(db: Session, changed_ids: list[str]) -> list[str]:
    """Re-run every merge standing on the given datasets; the ids rebuilt."""
    return [o.dataset_id for o in rebuild_merges(db, changed_ids) if o.status == "rebuilt"]


def rebuild_merges(db: Session, changed_ids: list[str]) -> list[MergeOutcome]:
    """Re-run every merge standing on the given datasets, and say how each went.

    A merge of a merge has to wait for the one below it, so this works outwards
    in rounds: each round rebuilds what is now stale, and the datasets it
    rebuilt are themselves changed for the next round. Bounded by the number of
    derived datasets, which also stops a relationship cycle from looping here.

    Nothing is passed over in silence. A merge whose join refuses is reported
    as failed and keeps the data it had; one whose sources cannot be found at
    all is reported as stuck if it sits in a project this import touched -
    which is the only way of telling it might have stood on what changed.
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

    touched = {
        one.project_id
        for one in (db.get(Dataset, i) for i in changed_ids)
        if one is not None
    }
    recipes = {dataset.id: recipe(db, dataset) for dataset in derived}
    outcomes: dict[str, MergeOutcome] = {}

    stale = set(changed_ids)
    for _ in range(len(derived)):
        progressed = False
        for dataset in derived:
            found = recipes[dataset.id]
            if dataset.id in outcomes or isinstance(found, str):
                continue
            join, left, right = found
            if left.id not in stale and right.id not in stale:
                continue
            try:
                run_merge(db, dataset, join, left, right)
            except Exception as exc:  # noqa: BLE001 - one bad merge must not
                # abandon the rest of the upload, and the dataset keeps the data
                # it had rather than being left empty.
                logger.warning("Could not rebuild '%s': %s", dataset.name, exc)
                outcomes[dataset.id] = MergeOutcome(dataset.id, dataset.name, "failed", str(exc))
                note(dataset, "failed", str(exc))
                continue
            outcomes[dataset.id] = MergeOutcome(dataset.id, dataset.name, "rebuilt")
            note(dataset, "rebuilt")
            stale.add(dataset.id)
            progressed = True
        if not progressed:
            break

    for dataset in derived:
        found = recipes[dataset.id]
        if isinstance(found, str) and dataset.project_id in touched:
            outcomes[dataset.id] = MergeOutcome(dataset.id, dataset.name, "stuck", found)
            note(dataset, "stuck", found)
    return list(outcomes.values())


def propagate_labels(
    db: Session, source_id: str, variable: str, stored: dict
) -> list[str]:
    """Carry a hand-written label into the merges built on that dataset.

    A merged dataset is a dataset in its own right, holding its own copy of the
    labels as they were when it was built. It is also the one dashboards point
    at, so a label written on the source and not carried across would be
    invisible exactly where it was wanted.

    Works outwards in rounds like rebuild_dependents, so a merge of a merge gets
    it too, and matches on the column name: a prefixed or disambiguated column
    is a different name, and guessing at it would label the wrong thing.
    """
    derived = [
        dataset
        for dataset in db.scalars(select(Dataset)).all()
        if (dataset.derivation or {}).get("type") == "merge"
    ]
    carriers = {source_id}
    touched: list[str] = []
    for _ in range(len(derived) or 1):
        progressed = False
        for dataset in derived:
            if dataset.id in touched:
                continue
            sources = sources_of(db, dataset)
            if sources is None:
                continue
            _, left, right = sources
            if left.id not in carriers and right.id not in carriers:
                continue
            row = next((v for v in dataset.variables if v.name == variable), None)
            if row is None:
                continue
            if "label" in stored:
                row.label = stored["label"]
            if "value_labels" in stored:
                row.value_labels = dict(stored["value_labels"])
            meta = dict(dataset.meta or {})
            overrides = dict(meta.get("variable_labels") or {})
            overrides[variable] = {**(overrides.get(variable) or {}), **stored}
            meta["variable_labels"] = overrides
            dataset.meta = meta
            touched.append(dataset.id)
            carriers.add(dataset.id)
            progressed = True
        if not progressed:
            break
    return touched
