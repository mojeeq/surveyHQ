"""Creating and refreshing datasets from files, and their metadata bookkeeping."""

from __future__ import annotations

import shutil
from pathlib import Path

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import Dataset, DatasetSource, DatasetStatus, Variable, VariableType
from app.services.ingest import IngestError, detect_monitoring_fields, ingest_file

logger = get_logger(__name__)


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)[:180] or "dataset"
    candidate = base
    suffix = 2
    while db.scalar(select(Dataset).where(Dataset.slug == candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def dataset_directory(dataset_id: str) -> Path:
    return settings.datasets_path / dataset_id


def create_dataset_record(
    db: Session,
    *,
    name: str,
    description: str = "",
    source: DatasetSource = DatasetSource.upload,
    source_ref: str = "",
    connection_id: str | None = None,
    tags: list[str] | None = None,
    created_by: str | None = None,
) -> Dataset:
    dataset = Dataset(
        name=name,
        slug=unique_slug(db, name),
        description=description,
        source=source,
        source_ref=source_ref,
        connection_id=connection_id,
        tags=tags or [],
        created_by=created_by,
        status=DatasetStatus.pending,
    )
    db.add(dataset)
    db.flush()
    return dataset


def load_file_into_dataset(db: Session, dataset: Dataset, file_path: Path) -> Dataset:
    """Ingest a file and attach the resulting Parquet + variables to the dataset.

    Safe to call repeatedly: a refresh replaces the data in place and bumps the
    version, so saved charts keep working as long as variable names are stable.
    """
    dataset.status = DatasetStatus.processing
    dataset.error = ""
    db.flush()

    directory = dataset_directory(dataset.id)
    try:
        result = ingest_file(file_path, directory)
    except IngestError as exc:
        dataset.status = DatasetStatus.failed
        dataset.error = str(exc)
        db.flush()
        raise
    except Exception as exc:  # noqa: BLE001 - surface unexpected reader failures
        dataset.status = DatasetStatus.failed
        dataset.error = f"Unexpected error while reading the file: {exc}"
        db.flush()
        raise IngestError(dataset.error) from exc

    # Replace variable metadata wholesale; the parquet file is the source of truth
    for existing in list(dataset.variables):
        db.delete(existing)
    db.flush()

    for meta in result.variables:
        db.add(
            Variable(
                dataset_id=dataset.id,
                name=meta.name,
                label=meta.label,
                var_type=VariableType(meta.var_type),
                storage_type=meta.storage_type,
                position=meta.position,
                n_missing=meta.n_missing,
                n_unique=meta.n_unique,
                min_value=meta.min_value,
                max_value=meta.max_value,
                mean_value=meta.mean_value,
                value_labels=meta.value_labels,
                missing_tags=meta.missing_tags,
                is_hidden=meta.is_hidden,
            )
        )

    detected = detect_monitoring_fields(result.variables)
    meta_payload = dict(dataset.meta or {})
    meta_payload["monitoring_fields"] = detected
    meta_payload["warnings"] = result.warnings
    dataset.meta = meta_payload

    dataset.storage_path = str(result.parquet_path)
    dataset.row_count = result.row_count
    dataset.column_count = result.column_count
    dataset.file_size = result.file_size
    dataset.status = DatasetStatus.ready
    dataset.refreshed_at = utcnow()
    dataset.version = (dataset.version or 0) + 1
    db.flush()
    logger.info(
        "Dataset %s ready: %s rows x %s columns",
        dataset.name,
        result.row_count,
        result.column_count,
    )
    return dataset


def delete_dataset_files(dataset: Dataset) -> None:
    directory = dataset_directory(dataset.id)
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)


def dataset_is_queryable(dataset: Dataset) -> bool:
    return (
        dataset.status == DatasetStatus.ready
        and bool(dataset.storage_path)
        and Path(dataset.storage_path).exists()
    )
