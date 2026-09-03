"""Creating and refreshing datasets from files, and their metadata bookkeeping."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from dataclasses import field as dc_field
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
    PARADATA_TAG,
    SOURCE_COLUMN,
    by_member_name,
    combine,
    extract_members,
    group_by_schema,
    is_archive,
)
from app.services.ingest import (
    MISSING_TAG_SUFFIX,
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
    project_id: str | None = None,
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
        project_id=project_id,
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

    # Labels somebody wrote by hand are not in the file and would be lost every
    # time a newer export replaced it - so they are kept on the dataset and put
    # back here, which is what makes them survive a replacement.
    overrides = (dataset.meta or {}).get("variable_labels") or {}

    for meta in result.variables:
        override = overrides.get(meta.name) or {}
        db.add(
            Variable(
                dataset_id=dataset.id,
                name=meta.name,
                label=override.get("label", meta.label),
                var_type=VariableType(meta.var_type),
                storage_type=meta.storage_type,
                position=meta.position,
                n_missing=meta.n_missing,
                n_unique=meta.n_unique,
                min_value=meta.min_value,
                max_value=meta.max_value,
                mean_value=meta.mean_value,
                value_labels={**meta.value_labels, **(override.get("value_labels") or {})},
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

    return append_frame_into_dataset(db, dataset, frame, variable_labels, value_labels)


def append_frame_into_dataset(
    db: Session,
    dataset: Dataset,
    frame: pd.DataFrame,
    variable_labels: dict[str, str],
    value_labels: dict[str, dict[str, str]],
) -> Dataset:
    """Append rows onto a dataset that already holds data.

    The frame is expected to carry its own SOURCE_COLUMN already, since only the
    caller knows what the rows should be attributed to.
    """
    if not dataset_is_queryable(dataset):
        raise IngestError(
            f"'{dataset.name}' has no data to append to yet. Upload into it first."
        )
    existing = pd.read_parquet(dataset.storage_path)

    if SOURCE_COLUMN not in existing.columns:
        # The dataset predates this column; label what is already there rather
        # than leaving half the rows with no provenance.
        existing[SOURCE_COLUMN] = dataset.source_ref or "original upload"

    before = len(existing)
    combined = pd.concat([existing, frame], ignore_index=True, sort=False)

    warnings: list[str] = []
    warnings.extend(_duplicate_key_warnings(existing, frame))
    # The "__mv" companions are this platform's own bookkeeping for Stata tagged
    # missings, created only for columns that actually carry a tag. A round with
    # no ".a" in a column simply has no companion for it, which is not a
    # difference in the data and not something to report as one.
    added = _reportable(set(frame.columns) - set(existing.columns))
    dropped = _reportable(set(existing.columns) - set(frame.columns))
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


# Records which file inside an archive a dataset holds, so a later archive knows
# which dataset each of its members belongs to. Without it the match would have
# to be made on the dataset's display name, which users rename.
ARCHIVE_MEMBER_KEY = "archive_member"


@dataclass
class ArchiveImport:
    """What one archive upload did, per member file."""

    datasets: list[Dataset] = dc_field(default_factory=list)
    created: list[str] = dc_field(default_factory=list)
    appended: list[str] = dc_field(default_factory=list)
    replaced: list[str] = dc_field(default_factory=list)
    # The ids behind `replaced`, for whatever was built on top of them.
    replaced_ids: list[str] = dc_field(default_factory=list)
    skipped: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)
    rows: int = 0


# A member file only appends onto a dataset whose columns it largely shares.
# The name alone is not enough: two unrelated surveys can both export a
# "members.dta", and in the shared area they would otherwise silently merge into
# one dataset whose row count means nothing.
MIN_COLUMN_OVERLAP = 0.5


def find_archive_sibling(
    db: Session,
    key: str,
    project_id: str | None,
    columns: set[str] | None = None,
) -> Dataset | None:
    """The dataset already holding this member file, if there is one.

    Scoped to the project, so two projects can each hold their own
    "members.dta". Within that scope the candidate must also share most of its
    columns with the incoming file, which is what stops a same-named file from a
    different survey being appended onto it.
    """
    statement = select(Dataset).where(
        Dataset.project_id.is_(None) if project_id is None else Dataset.project_id == project_id
    )
    for candidate in db.scalars(statement):
        if (candidate.meta or {}).get(ARCHIVE_MEMBER_KEY) != key:
            continue
        if columns is None:
            return candidate
        known = {v.name for v in candidate.variables}
        if not known:
            return candidate
        shared = len(known & columns) / len(known)
        if shared >= MIN_COLUMN_OVERLAP:
            return candidate
        logger.info(
            "Not appending %s onto '%s': only %.0f%% of its columns match",
            key,
            candidate.name,
            shared * 100,
        )
    return None


def load_archive_as_datasets(
    db: Session,
    *,
    archive_path: Path,
    archive_name: str,
    project_id: str | None = None,
    created_by: str | None = None,
    combine_all: bool = False,
    name_prefix: str = "",
    mode: str = "replace",
) -> ArchiveImport:
    """Import an archive as one dataset per member file.

    An export holds one file per roster level - interview, household member,
    person abroad - so each becomes its own dataset. A later archive carries the
    same member names, and each of its files goes to the dataset already holding
    that name rather than creating a duplicate.

    mode decides what "goes to" means:

      replace  the dataset's data is swapped for the new file's. The dataset row
               keeps its id, so every relationship, chart, indicator and quality
               rule built on it goes on working. This is what a live monitoring
               tool needs: a fresh export every morning should update the
               numbers, not accumulate yesterday's rows underneath today's.
      append   the new rows are added to what is there, for genuinely
               incremental exports where each file holds only what is new.

    combine_all is a separate escape hatch for an archive that really does hold
    several rounds of one table: every member goes into a single dataset.
    """
    workdir = Path(tempfile.mkdtemp(prefix="surveyhq-archive-"))
    outcome = ArchiveImport()
    try:
        members = extract_members(archive_path, workdir)

        if combine_all:
            result = combine(members)
            dataset = create_dataset_record(
                db,
                name=archive_name,
                source=DatasetSource.upload,
                source_ref=archive_name,
                created_by=created_by,
                project_id=project_id,
            )
            _apply_ingest(
                db,
                dataset,
                ingest_frame(
                    result.frame,
                    result.variable_labels,
                    result.value_labels,
                    dataset_directory(dataset.id),
                    list(result.warnings),
                ),
            )
            outcome.datasets.append(dataset)
            outcome.created.append(dataset.name)
            outcome.warnings.extend(result.warnings)
            outcome.rows = dataset.row_count
            return outcome

        for key, member in sorted(by_member_name(members).items()):
            frame = member.frame.copy()
            # Every row records the archive it arrived in, not the member file:
            # the member name is the same in every round, so it would say nothing
            # about which round a row came from.
            frame[SOURCE_COLUMN] = archive_name

            existing = find_archive_sibling(
                db, key, project_id, {str(c) for c in frame.columns}
            )
            if existing is not None and dataset_is_queryable(existing):
                before = existing.row_count
                if mode == "append":
                    append_frame_into_dataset(
                        db, existing, frame, member.variable_labels, member.value_labels
                    )
                    outcome.appended.append(
                        f"{member.name} -> {existing.name} "
                        f"({before} + {len(frame)} = {existing.row_count} rows)"
                    )
                    outcome.rows += len(frame)
                else:
                    # Everything built on this dataset points at its id, so the
                    # row is kept and only its data swapped. Losing a variable is
                    # the one way that can still break something, so it is
                    # checked for rather than hoped about.
                    had = {v.name for v in existing.variables}
                    labels = dict(member.variable_labels)
                    labels.setdefault(SOURCE_COLUMN, "Archive this row was imported from")
                    ingested = ingest_frame(
                        frame,
                        labels,
                        member.value_labels,
                        dataset_directory(existing.id),
                        [],
                    )
                    _apply_ingest(db, existing, ingested)
                    outcome.replaced.append(
                        f"{member.name} -> {existing.name} "
                        f"({before} rows replaced by {existing.row_count})"
                    )
                    outcome.replaced_ids.append(existing.id)
                    outcome.rows += existing.row_count
                    outcome.warnings.extend(
                        _lost_variable_warnings(
                            db, existing, had, {v.name for v in ingested.variables}
                        )
                    )
                outcome.datasets.append(existing)
                continue

            stem = Path(member.name).stem
            dataset = existing or create_dataset_record(
                db,
                # The member stem is the useful name - VN_LF2024, R_demographics -
                # but two surveys in one project can share one, so a prefix is
                # offered for telling them apart.
                name=f"{name_prefix} {stem}".strip() if name_prefix else stem,
                description=f"From {archive_name}",
                source=DatasetSource.upload,
                source_ref=member.name,
                created_by=created_by,
                project_id=project_id,
                tags=[PARADATA_TAG] if member.is_paradata else [],
            )
            labels = dict(member.variable_labels)
            labels.setdefault(SOURCE_COLUMN, "Archive this row was imported from")
            _apply_ingest(
                db,
                dataset,
                ingest_frame(
                    frame,
                    labels,
                    member.value_labels,
                    dataset_directory(dataset.id),
                    [],
                ),
            )
            meta = dict(dataset.meta or {})
            meta[ARCHIVE_MEMBER_KEY] = key
            dataset.meta = meta
            db.flush()
            outcome.datasets.append(dataset)
            outcome.created.append(f"{member.name} -> {dataset.name} ({dataset.row_count} rows)")
            outcome.rows += dataset.row_count

        return outcome
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# Survey Solutions can be set to export everything collected so far rather than
# only what is new. Appending two such exports duplicates every interview they
# have in common, and nothing about the row counts makes that obvious - the
# dataset just quietly reports twice the fieldwork. So say it plainly.
IDENTITY_COLUMNS = ("interview__key", "interview__id")


def _reportable(columns: set[str]) -> set[str]:
    """Drop internal companion columns from anything shown to a user."""
    return {c for c in columns if not c.endswith(MISSING_TAG_SUFFIX)}


def _duplicate_key_warnings(
    existing: pd.DataFrame, incoming: pd.DataFrame
) -> list[str]:
    """Report interviews that appear in both the existing data and the new rows."""
    warnings: list[str] = []
    for column in IDENTITY_COLUMNS:
        if column not in existing.columns or column not in incoming.columns:
            continue
        overlap = set(existing[column].dropna()) & set(incoming[column].dropna())
        if not overlap:
            continue
        warnings.append(
            f"{len(overlap)} value(s) of '{column}' appear in both the existing "
            f"data and the appended rows, so those interviews are now counted "
            f"twice. This usually means the export was cumulative rather than "
            f"incremental. Examples: "
            + ", ".join(str(v) for v in sorted(overlap)[:3])
        )
        break  # one identity column is enough; the second would say the same
    return warnings


def _lost_variable_warnings(
    db: Session, dataset: Dataset, had: set[str], now: set[str]
) -> list[str]:
    """Name what a replacement broke, rather than leaving it to be discovered.

    Replacing a dataset in place is what keeps a live monitoring setup working:
    the row keeps its id, so relationships, charts, indicators and quality rules
    all still point at it. The one thing that still breaks it is a variable
    disappearing - a question dropped between rounds - and nothing about the
    import would otherwise say so. The chart just fails the next time somebody
    opens the dashboard.
    """
    from app.models import Chart, Indicator, QualityRule

    # The new names come from the ingest result, not from dataset.variables:
    # the relationship is still holding the rows that were just replaced, so
    # reading it here would compare the old list against itself and find nothing.
    lost = {name for name in had - now if not name.endswith(MISSING_TAG_SUFFIX)}
    if not lost:
        return []

    warnings = [
        f"'{dataset.name}' no longer has {len(lost)} variable(s) it had before: "
        + ", ".join(sorted(lost)[:6])
        + ("..." if len(lost) > 6 else "")
    ]

    # Anything referring to a lost variable by name is now broken. The specs are
    # free-form JSON, so this looks for the name in the serialised spec rather
    # than trying to parse every shape a spec can take.
    def mentions(blob: object) -> set[str]:
        text = json.dumps(blob or {})
        return {name for name in lost if f'"{name}"' in text}

    broken: list[str] = []
    for chart in db.scalars(select(Chart).where(Chart.dataset_id == dataset.id)):
        if mentions(chart.spec):
            broken.append(f"chart '{chart.name}'")
    for indicator in db.scalars(
        select(Indicator).where(Indicator.dataset_id == dataset.id)
    ):
        if mentions(indicator.spec) or indicator.breakdown_variable in lost:
            broken.append(f"indicator '{indicator.name}'")
    for rule in db.scalars(
        select(QualityRule).where(QualityRule.dataset_id == dataset.id)
    ):
        if mentions(rule.config) or mentions(rule.filters):
            broken.append(f"quality check '{rule.name}'")

    if broken:
        warnings.append(
            f"{len(broken)} saved item(s) refer to those variables and will now "
            "fail: " + ", ".join(broken[:6]) + ("..." if len(broken) > 6 else "")
        )
    return warnings
