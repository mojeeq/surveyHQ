"""Creating and refreshing datasets from files, and their metadata bookkeeping."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import Dataset, DatasetSource, DatasetStatus, Variable, VariableType
from app.services.archives import (
    SOURCE_COLUMN,
    combine,
    extract_members,
    group_by_schema,
    is_archive,
)
from app.services.ingest import (
    IngestError,
    IngestResult,
    detect_monitoring_fields,
    ingest_file,
    ingest_frame,
    read_source,
)

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

    return _apply_ingest(db, dataset, result)


def _apply_ingest(db: Session, dataset: Dataset, result: IngestResult) -> Dataset:
    """Attach a finished ingest to the dataset row.

    Shared by every route data arrives on so that variables, counts, detected
    monitoring fields and status are recorded identically each time.
    """
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


def load_archive_into_dataset(
    db: Session, dataset: Dataset, archive_path: Path, combine_all: bool = False
) -> tuple[Dataset, dict]:
    """Ingest a zip, appending the files inside it into one dataset.

    An export archive usually holds several tables - one per roster level - not
    several rounds of the same one, so by default only the largest group of files
    sharing a column set is appended. combine_all forces every file together on
    the union of their columns, which is what you want when rounds genuinely
    differ.
    """
    workdir = Path(tempfile.mkdtemp(prefix="surveyhq-archive-"))
    try:
        members = extract_members(archive_path, workdir)
        groups = group_by_schema(members)
        chosen = members if combine_all else groups[0]

        skipped = [m.name for m in members if m not in chosen]
        result = combine(chosen)
        warnings = list(result.warnings)
        if skipped:
            warnings.append(
                f"{len(skipped)} file(s) had a different set of columns and were "
                f"not appended: {', '.join(skipped[:5])}"
                + ("..." if len(skipped) > 5 else "")
                + ". Upload them separately, or choose to combine everything."
            )

        _apply_ingest(
            db,
            dataset,
            ingest_frame(
                result.frame,
                result.variable_labels,
                result.value_labels,
                dataset_directory(dataset.id),
                warnings,
            ),
        )
        summary = {
            "files_combined": result.members,
            "files_skipped": skipped,
            "rows": dataset.row_count,
        }
        meta = dict(dataset.meta or {})
        meta["archive"] = summary
        dataset.meta = meta
        db.flush()
        return dataset, summary
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def append_file_into_dataset(
    db: Session, dataset: Dataset, file_path: Path, source_name: str | None = None
) -> Dataset:
    """Append another file's rows onto a dataset that already holds data.

    Used for the case the archive route does not cover: a later round arriving
    on its own, to be added to what is already there rather than replacing it.

    source_name is the name the file was uploaded under. It has to be passed in:
    file_path points at a temporary copy named after the dataset id, so using it
    would stamp every appended row with a meaningless generated filename and lose
    the provenance the column exists to record.
    """
    label = source_name or file_path.name
    if not dataset_is_queryable(dataset):
        raise IngestError(
            f"'{dataset.name}' has no data to append to yet. Upload into it first."
        )

    existing = pd.read_parquet(dataset.storage_path)
    if is_archive(file_path):
        workdir = Path(tempfile.mkdtemp(prefix="surveyhq-append-"))
        try:
            members = extract_members(file_path, workdir)
            incoming = combine(group_by_schema(members)[0])
            frame, variable_labels, value_labels = (
                incoming.frame,
                incoming.variable_labels,
                incoming.value_labels,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    else:
        frame, variable_labels, value_labels = read_source(file_path)
        frame = frame.copy()
        frame[SOURCE_COLUMN] = label

    if SOURCE_COLUMN not in existing.columns:
        # The dataset predates this column; label what is already there rather
        # than leaving half the rows with no provenance.
        existing[SOURCE_COLUMN] = dataset.source_ref or "original upload"

    before = len(existing)
    combined = pd.concat([existing, frame], ignore_index=True, sort=False)

    warnings: list[str] = []
    added = set(frame.columns) - set(existing.columns)
    dropped = set(existing.columns) - set(frame.columns)
    if added:
        warnings.append(
            f"The appended file adds {len(added)} new variable(s), blank for "
            f"earlier rows: " + ", ".join(sorted(added)[:5])
        )
    if dropped:
        warnings.append(
            f"The appended file does not contain {len(dropped)} existing "
            f"variable(s), blank for the new rows: " + ", ".join(sorted(dropped)[:5])
        )

    # Existing labels win: they describe the dataset as it has been analysed.
    kept_labels = {v.name: v.label for v in dataset.variables if v.label}
    kept_value_labels = {v.name: v.value_labels for v in dataset.variables if v.value_labels}
    for key, value in variable_labels.items():
        kept_labels.setdefault(key, value)
    for key, value in value_labels.items():
        kept_value_labels.setdefault(key, value)

    _apply_ingest(
        db,
        dataset,
        ingest_frame(
            combined, kept_labels, kept_value_labels, dataset_directory(dataset.id), warnings
        ),
    )
    logger.info(
        "Appended %s rows to %s (%s -> %s)",
        len(combined) - before,
        dataset.name,
        before,
        len(combined),
    )
    return dataset
