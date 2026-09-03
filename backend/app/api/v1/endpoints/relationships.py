"""Relationships between a project's datasets, and the merges built on them."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, RequireManager, get_dataset
from app.models import (
    Cardinality,
    Dataset,
    DatasetRelationship,
    DatasetSource,
    User,
)
from app.schemas.common import Message
from app.schemas.dataset import DatasetDetail
from app.schemas.relationship import (
    DetectedRelationship,
    DetectionResult,
    MergeIn,
    RelationshipIn,
    RelationshipOut,
    RelationshipUpdate,
)
from app.services.audit import record
from app.services.datasets import (
    _apply_ingest,
    create_dataset_record,
    dataset_directory,
    dataset_is_queryable,
)
from app.services.ingest import ingest_frame
from app.services.projects import scope_for
from app.services.relationships import detect, merge_frames, store

router = APIRouter()


@router.get("", response_model=list[RelationshipOut])
def list_relationships(
    db: DbSession, user: CurrentUser, project_id: str = ""
) -> list[RelationshipOut]:
    """Relationships whose datasets this user can see."""
    statement = select(DatasetRelationship)
    if project_id:
        statement = statement.where(
            DatasetRelationship.project_id.is_(None)
            if project_id == "none"
            else DatasetRelationship.project_id == project_id
        )
    scope = scope_for(db, user)
    output: list[RelationshipOut] = []
    for relationship in db.scalars(statement):
        left = db.get(Dataset, relationship.left_dataset_id)
        right = db.get(Dataset, relationship.right_dataset_id)
        # Both ends have to be visible: a link is a statement about two
        # datasets, and naming one the caller cannot see would leak it.
        if left is None or right is None:
            continue
        if not (scope.allows(left.project_id) and scope.allows(right.project_id)):
            continue
        output.append(
            RelationshipOut(
                **{
                    field: getattr(relationship, field)
                    for field in (
                        "id", "project_id", "left_dataset_id", "right_dataset_id",
                        "left_variable", "right_variable", "cardinality",
                        "is_active", "detected", "created_at",
                    )
                },
                left_name=left.name,
                right_name=right.name,
            )
        )
    return output


@router.post("/detect", response_model=DetectionResult)
def detect_relationships(
    db: DbSession, user: RequireManager, project_id: str = ""
) -> DetectionResult:
    """Propose links among a project's datasets by looking at the data."""
    scope = scope_for(db, user)
    statement = select(Dataset).where(
        Dataset.project_id.is_(None)
        if project_id in ("", "none")
        else Dataset.project_id == project_id
    )
    datasets = [d for d in db.scalars(statement) if scope.allows(d.project_id)]
    if len(datasets) < 2:
        return DetectionResult(proposed=[], created=0)

    candidates = detect(db, datasets)
    created = store(db, project_id or None, candidates)
    db.commit()
    return DetectionResult(
        proposed=[
            DetectedRelationship(
                left_dataset_id=c.left_dataset_id,
                right_dataset_id=c.right_dataset_id,
                left_name=c.left_name,
                right_name=c.right_name,
                left_variable=c.left_variable,
                right_variable=c.right_variable,
                cardinality=c.cardinality,
                overlap=c.overlap,
            )
            for c in candidates
        ],
        created=len(created),
    )


@router.post("", response_model=RelationshipOut, status_code=201)
def create_relationship(
    payload: RelationshipIn, db: DbSession, user: RequireManager
) -> RelationshipOut:
    left = get_dataset(payload.left_dataset_id, db, user)
    right = get_dataset(payload.right_dataset_id, db, user)
    if left.id == right.id:
        raise HTTPException(status_code=422, detail="A dataset cannot relate to itself")
    _require_column(left, payload.left_variable)
    _require_column(right, payload.right_variable)

    relationship = DatasetRelationship(
        project_id=left.project_id,
        left_dataset_id=left.id,
        right_dataset_id=right.id,
        left_variable=payload.left_variable,
        right_variable=payload.right_variable,
        cardinality=payload.cardinality,
        detected=False,
    )
    db.add(relationship)
    db.commit()
    db.refresh(relationship)
    return _to_out(relationship, db)


@router.patch("/{relationship_id}", response_model=RelationshipOut)
def update_relationship(
    relationship_id: str, payload: RelationshipUpdate, db: DbSession, user: RequireManager
) -> RelationshipOut:
    relationship = _get(relationship_id, db, user)
    data = payload.model_dump(exclude_unset=True)
    if "left_variable" in data:
        _require_column(db.get(Dataset, relationship.left_dataset_id), data["left_variable"])
    if "right_variable" in data:
        _require_column(db.get(Dataset, relationship.right_dataset_id), data["right_variable"])
    for field, value in data.items():
        setattr(relationship, field, value)
    # It is no longer only a guess once someone has corrected it.
    relationship.detected = False
    db.commit()
    db.refresh(relationship)
    return _to_out(relationship, db)


@router.delete("/{relationship_id}", response_model=Message)
def delete_relationship(
    relationship_id: str, db: DbSession, user: RequireManager
) -> Message:
    relationship = _get(relationship_id, db, user)
    db.delete(relationship)
    db.commit()
    return Message(detail="Relationship deleted")


@router.post("/merge", response_model=DatasetDetail, status_code=201)
def merge_datasets(payload: MergeIn, db: DbSession, user: RequireManager) -> DatasetDetail:
    """Build a new dataset by joining two related ones.

    The recipe is stored on the result, so it can be re-run when either source
    changes rather than having to be rebuilt by hand.
    """
    relationship = _get(payload.relationship_id, db, user)
    if relationship.cardinality is Cardinality.many_to_many:
        raise HTTPException(
            status_code=422,
            detail=(
                "These two are many-to-many on that key, so joining them would "
                "multiply rows rather than add columns. Merge each into the "
                "table they both point at instead."
            ),
        )
    left = get_dataset(relationship.left_dataset_id, db, user)
    right = get_dataset(relationship.right_dataset_id, db, user)
    for dataset in (left, right):
        if not dataset_is_queryable(dataset):
            raise HTTPException(
                status_code=409, detail=f"'{dataset.name}' has no data to merge"
            )

    derivation = {
        "type": "merge",
        "relationship_id": relationship.id,
        "how": payload.how,
        "columns": payload.columns,
        "prefix": payload.prefix,
    }
    merged = create_dataset_record(
        db,
        name=payload.name,
        description=f"{left.name} joined to {right.name}",
        source=DatasetSource.derived,
        source_ref=f"{left.name} + {right.name}",
        created_by=user.id,
        project_id=left.project_id,
    )
    merged.derivation = derivation
    _run_merge(db, merged, relationship, left, right)
    record(
        db,
        user=user,
        action="merge_datasets",
        entity_type="dataset",
        entity_id=merged.id,
        detail=derivation,
    )
    db.commit()
    db.refresh(merged)
    return DatasetDetail.model_validate(merged)


@router.post("/rebuild/{dataset_id}", response_model=DatasetDetail)
def rebuild_derived_dataset(
    dataset_id: str, db: DbSession, user: RequireManager
) -> DatasetDetail:
    """Re-run the merge that produced this dataset, against current sources."""
    dataset = get_dataset(dataset_id, db, user)
    derivation = dataset.derivation or {}
    if derivation.get("type") != "merge":
        raise HTTPException(
            status_code=422,
            detail=f"'{dataset.name}' was uploaded, not derived, so there is nothing to re-run",
        )
    relationship = db.get(DatasetRelationship, derivation.get("relationship_id"))
    if relationship is None:
        raise HTTPException(
            status_code=409,
            detail="The relationship this was built from no longer exists",
        )
    left = get_dataset(relationship.left_dataset_id, db, user)
    right = get_dataset(relationship.right_dataset_id, db, user)
    _run_merge(db, dataset, relationship, left, right)
    db.commit()
    db.refresh(dataset)
    return DatasetDetail.model_validate(dataset)


# --- helpers ----------------------------------------------------------------


def _run_merge(
    db: DbSession,
    target: Dataset,
    relationship: DatasetRelationship,
    left: Dataset,
    right: Dataset,
) -> None:
    derivation = target.derivation or {}
    try:
        frame = merge_frames(
            left,
            right,
            relationship.left_variable,
            relationship.right_variable,
            how=derivation.get("how", "left"),
            columns=derivation.get("columns") or None,
            prefix=derivation.get("prefix", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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


def _require_column(dataset: Dataset | None, column: str) -> None:
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if column not in {v.name for v in dataset.variables}:
        raise HTTPException(
            status_code=422, detail=f"'{dataset.name}' has no column named '{column}'"
        )


def _get(relationship_id: str, db: DbSession, user: User) -> DatasetRelationship:
    relationship = db.get(DatasetRelationship, relationship_id)
    if relationship is None:
        raise HTTPException(status_code=404, detail="Relationship not found")
    # Both ends, so a relationship cannot be used to reach a dataset out of scope
    get_dataset(relationship.left_dataset_id, db, user)
    get_dataset(relationship.right_dataset_id, db, user)
    return relationship


def _to_out(relationship: DatasetRelationship, db: DbSession) -> RelationshipOut:
    left = db.get(Dataset, relationship.left_dataset_id)
    right = db.get(Dataset, relationship.right_dataset_id)
    return RelationshipOut(
        **{
            field: getattr(relationship, field)
            for field in (
                "id", "project_id", "left_dataset_id", "right_dataset_id",
                "left_variable", "right_variable", "cardinality",
                "is_active", "detected", "created_at",
            )
        },
        left_name=left.name if left else "",
        right_name=right.name if right else "",
    )
