"""Drop-in high-throughput implementations for the survey-data hot paths.

These functions deliberately preserve the public contracts in ingest/datasets/
derived.  The performance runtime installs them before endpoint and worker
modules are imported, so the rest of the application does not need a second set
of code paths or schemas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.core.config import settings
from app.core.logging import get_logger
from app.services import columnar

logger = get_logger(__name__)
DELIMITED = {".csv", ".tab", ".tsv", ".txt"}


def build_metadata_from_parquet_fast(
    parquet_path: Path,
    variable_labels: dict[str, str],
    value_labels: dict[str, dict[str, str]],
) -> list[Any]:
    """Build exact metadata with batched Parquet scans.

    The old streaming path issued at least one full scan per variable and a
    second scan for every numeric integrality test.  Wide census files could
    therefore read the same Parquet more than a thousand times.  profile_parquet
    combines many independent aggregates into each pass.
    """
    from app.services.ingest import MISSING_TAG_SUFFIX, VariableMeta, _safe_float, classify

    total, profiles, tags = columnar.profile_parquet(
        parquet_path, hidden_suffix=MISSING_TAG_SUFFIX
    )
    metas: list[VariableMeta] = []
    for position, profile in enumerate(profiles):
        storage = profile.storage_type
        upper = storage.upper()
        numeric = any(
            token in upper for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "HUGEINT")
        )
        is_datetime = "TIMESTAMP" in upper or upper == "DATE"
        labels = value_labels.get(profile.name, {})
        var_type = classify(
            is_boolean=upper == "BOOLEAN",
            is_datetime=is_datetime,
            is_numeric=numeric,
            is_integral=numeric and not profile.has_fractional,
            has_value_labels=bool(labels),
            non_null=profile.non_null,
            distinct=profile.distinct,
        )
        metas.append(
            VariableMeta(
                name=profile.name,
                label=str(variable_labels.get(profile.name, "") or "")[:1000],
                var_type=var_type,
                storage_type=storage,
                position=position,
                n_missing=total - profile.non_null,
                n_unique=profile.distinct,
                min_value=_safe_float(profile.minimum),
                max_value=_safe_float(profile.maximum),
                mean_value=_safe_float(profile.mean),
                value_labels=labels,
                missing_tags=tags.get(profile.name, []),
                is_hidden=profile.name.endswith(MISSING_TAG_SUFFIX),
            )
        )
    return metas


def ingest_file_fast(
    source: Path,
    destination_dir: Path,
    original: Callable[[Path, Path], Any],
) -> Any:
    """Use DuckDB's parallel CSV reader for large delimited survey exports."""
    from app.services.ingest import IngestResult

    threshold = max(1, settings.duckdb_csv_above_mb) * 1024 * 1024
    if source.suffix.lower() not in DELIMITED or source.stat().st_size < threshold:
        return original(source, destination_dir)

    destination_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = destination_dir / "data.parquet"
    try:
        columnar.delimited_to_parquet(source, parquet_path)
        metas = build_metadata_from_parquet_fast(parquet_path, {}, {})
        return IngestResult(
            parquet_path=parquet_path,
            row_count=columnar.parquet_row_count(parquet_path),
            column_count=len(metas),
            file_size=parquet_path.stat().st_size,
            variables=metas,
            warnings=[
                "Large delimited file parsed directly by DuckDB and streamed to Parquet."
            ],
        )
    except Exception as exc:  # noqa: BLE001 - encoding/dialect fallback stays compatible
        logger.warning(
            "DuckDB direct ingest could not read %s (%s); falling back to pandas",
            source.name,
            exc,
        )
        parquet_path.unlink(missing_ok=True)
        return original(source, destination_dir)


def dataframe_preview_fast(path: Path, limit: int = 20) -> dict[str, Any]:
    return columnar.preview(path, limit)


def _duplicate_warnings(existing_path: Path, incoming: pd.DataFrame) -> list[str]:
    from app.services import datasets as dataset_service

    existing_names = {name for name, _ in columnar.parquet_columns(existing_path)}
    warnings: list[str] = []
    for column in dataset_service.IDENTITY_COLUMNS:
        if column not in existing_names or column not in incoming.columns:
            continue
        count, sample = columnar.overlapping_frame_values(existing_path, incoming, column)
        if not count:
            continue
        warnings.append(
            f"{count} value(s) of '{column}' appear in both the existing data and "
            "the appended rows, so those interviews are now counted twice. This "
            "usually means the export was cumulative rather than incremental. Examples: "
            + ", ".join(str(value) for value in sample)
        )
        break
    return warnings


def append_frame_fast(
    db: Any,
    dataset: Any,
    frame: pd.DataFrame,
    variable_labels: dict[str, str],
    value_labels: dict[str, dict[str, str]],
) -> Any:
    """Append without ever reading the existing survey into pandas."""
    from app.services import datasets as dataset_service
    from app.services.ingest import IngestError, IngestResult, clean_columns

    if not dataset_service.dataset_is_queryable(dataset):
        raise IngestError(
            f"'{dataset.name}' has no data to append to yet. Upload into it first."
        )

    existing_path = Path(dataset.storage_path)
    frame = clean_columns(frame)
    before = int(dataset.row_count or 0)
    existing_columns = {name for name, _ in columnar.parquet_columns(existing_path)}
    incoming_columns = {str(name) for name in frame.columns}

    warnings = _duplicate_warnings(existing_path, frame)
    added = dataset_service._reportable(incoming_columns - existing_columns)
    dropped = dataset_service._reportable(existing_columns - incoming_columns)
    if added:
        warnings.append(
            f"The appended file adds {len(added)} new variable(s), blank for earlier rows: "
            + ", ".join(sorted(added)[:5])
        )
    if dropped:
        warnings.append(
            f"The appended file does not contain {len(dropped)} existing variable(s), "
            "blank for the new rows: " + ", ".join(sorted(dropped)[:5])
        )

    kept_labels = {v.name: v.label for v in dataset.variables if v.label}
    kept_value_labels = {v.name: v.value_labels for v in dataset.variables if v.value_labels}
    for key, value in variable_labels.items():
        kept_labels.setdefault(key, value)
    for key, value in value_labels.items():
        kept_value_labels.setdefault(key, value)
    warnings.extend(dataset_service._recoded_warnings(kept_value_labels, value_labels))

    columnar.append_frame_to_parquet(
        existing_path,
        frame,
        existing_path,
        source_column=dataset_service.SOURCE_COLUMN,
        existing_source_value=dataset.source_ref or "original upload",
    )
    metas = build_metadata_from_parquet_fast(existing_path, kept_labels, kept_value_labels)
    result = IngestResult(
        parquet_path=existing_path,
        row_count=before + len(frame),
        column_count=len(metas),
        file_size=existing_path.stat().st_size,
        variables=metas,
        warnings=warnings,
    )
    dataset_service._apply_ingest(db, dataset, result)
    logger.info(
        "Columnar append: %s rows to %s (%s -> %s)",
        len(frame),
        dataset.name,
        before,
        dataset.row_count,
    )
    return dataset


def run_merge_fast(
    db: Any,
    target: Any,
    relationship: Any,
    left: Any,
    right: Any,
) -> None:
    """Join Parquet to Parquet and COPY the result directly to the target."""
    from app.services import datasets as dataset_service
    from app.services.ingest import IngestResult

    derivation = target.derivation or {}
    right_names = [v.name for v in right.variables]
    columns = derivation.get("columns") or None
    if columns:
        missing = sorted(set(columns) - set(right_names))
        if missing:
            raise ValueError(
                f"'{right.name}' has no column(s) named: {', '.join(missing[:5])}"
            )
        wanted = [name for name in columns if name in right_names]
    else:
        wanted = right_names

    left_names = {v.name for v in left.variables}
    prefix = derivation.get("prefix", "")
    destination = dataset_service.dataset_directory(target.id) / "data.parquet"
    row_count, output_names = columnar.copy_join_to_parquet(
        left_path=left.storage_path,
        right_path=right.storage_path,
        left_key=relationship.left_variable,
        right_key=relationship.right_variable,
        right_columns=wanted,
        left_columns=left_names,
        destination=destination,
        how=derivation.get("how", "left"),
        prefix=prefix,
    )

    labels = {v.name: v.label for v in left.variables if v.label}
    value_labels = {v.name: v.value_labels for v in left.variables if v.value_labels}
    output_set = set(output_names)
    for variable in right.variables:
        if variable.name == relationship.right_variable or variable.name not in wanted:
            continue
        alias = f"{prefix}{variable.name}" if prefix else variable.name
        if alias in left_names:
            alias = f"{alias}__right"
        if alias not in output_set:
            continue
        if variable.label:
            labels.setdefault(alias, variable.label)
        if variable.value_labels:
            value_labels.setdefault(alias, variable.value_labels)

    warnings: list[str] = []
    if derivation.get("how", "left") == "left" and row_count > int(left.row_count or 0):
        warnings.append(
            f"The join produced {row_count:,} rows from {left.row_count:,}, because "
            f"'{right.name}' has more than one row per key. Each left row is repeated."
        )

    metas = build_metadata_from_parquet_fast(destination, labels, value_labels)
    dataset_service._apply_ingest(
        db,
        target,
        IngestResult(
            parquet_path=destination,
            row_count=row_count,
            column_count=len(metas),
            file_size=destination.stat().st_size,
            variables=metas,
            warnings=warnings,
        ),
    )
    logger.info(
        "Columnar merge: %s + %s -> %s (%s rows)",
        left.name,
        right.name,
        target.name,
        row_count,
    )
