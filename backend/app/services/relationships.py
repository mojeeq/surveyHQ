"""Finding and using the links between a project's datasets.

Detection looks at the data, not only at column names. Two tables sharing a
column called "id" are not necessarily related, and the difference between
one-to-many and many-to-many is a fact about the values, not the names: it is
whether the key is unique on each side. So each candidate is checked by counting
distinct values against row counts, which DuckDB answers over Parquet in
milliseconds even at survey scale.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Cardinality, Dataset, DatasetRelationship
from app.services.datasets import dataset_is_queryable
from app.services.query_engine import _quote_path, quote_ident, run_sql

logger = get_logger(__name__)

# Columns worth trying first. Survey Solutions gives every level of an export
# the same interview identifiers, which is exactly what links them.
PREFERRED_KEYS = ("interview__id", "interview__key")

# A column has to be shared and reasonably identifying to be worth proposing.
# Sharing "1" and "2" across two tables is a coincidence, not a relationship.
MIN_DISTINCT = 2


@dataclass
class Candidate:
    left_dataset_id: str
    right_dataset_id: str
    left_variable: str
    right_variable: str
    cardinality: Cardinality
    overlap: float
    left_name: str = ""
    right_name: str = ""


def _stats(dataset: Dataset, column: str) -> tuple[int, int]:
    """(rows, distinct non-null values) for one column."""
    sql = (
        f"SELECT COUNT(*), COUNT(DISTINCT {quote_ident(column)}) "
        f"FROM read_parquet({_quote_path(dataset.storage_path)})"
    )
    _, rows = run_sql(sql)
    return (int(rows[0][0]), int(rows[0][1])) if rows else (0, 0)


def _overlap(left: Dataset, right: Dataset, column: str) -> float:
    """The share of the right side's keys that appear on the left.

    A shared column name with no shared values is a coincidence; this is what
    tells the two apart.
    """
    col = quote_ident(column)
    sql = (
        f"SELECT COUNT(*) FROM ("
        f"  SELECT DISTINCT {col} AS k FROM read_parquet({_quote_path(right.storage_path)})"
        f"  WHERE {col} IS NOT NULL"
        f") r WHERE r.k IN ("
        f"  SELECT {col} FROM read_parquet({_quote_path(left.storage_path)})"
        f")"
    )
    _, matched = run_sql(sql)
    _, total = run_sql(
        f"SELECT COUNT(DISTINCT {col}) FROM read_parquet({_quote_path(right.storage_path)}) "
        f"WHERE {col} IS NOT NULL"
    )
    denominator = int(total[0][0]) if total else 0
    if not denominator:
        return 0.0
    return int(matched[0][0]) / denominator


def detect(db: Session, datasets: list[Dataset]) -> list[Candidate]:
    """Propose relationships among a set of datasets.

    Only the identifier columns are considered. Trying every shared column would
    propose links on things like "sex" that happen to appear in two tables, and
    the noise would make the real ones hard to find.
    """
    ready = [d for d in datasets if dataset_is_queryable(d)]
    columns = {d.id: {v.name for v in d.variables} for d in ready}
    candidates: list[Candidate] = []

    for index, left in enumerate(ready):
        for right in ready[index + 1 :]:
            shared = columns[left.id] & columns[right.id]
            for key in PREFERRED_KEYS:
                if key not in shared:
                    continue
                try:
                    left_rows, left_distinct = _stats(left, key)
                    right_rows, right_distinct = _stats(right, key)
                except Exception as exc:  # noqa: BLE001 - a bad column is not fatal
                    logger.warning("Could not compare %s on %s: %s", key, left.name, exc)
                    continue
                if left_distinct < MIN_DISTINCT or right_distinct < MIN_DISTINCT:
                    continue

                left_unique = left_distinct == left_rows
                right_unique = right_distinct == right_rows
                if left_unique and right_unique:
                    cardinality = Cardinality.one_to_one
                elif left_unique:
                    cardinality = Cardinality.one_to_many
                elif right_unique:
                    cardinality = Cardinality.many_to_one
                else:
                    # Neither side identifies a row, so a join would multiply
                    # rows in a way nobody asked for. Worth showing, never
                    # worth turning on by default.
                    cardinality = Cardinality.many_to_many

                overlap = _overlap(left, right, key)
                if overlap <= 0:
                    continue
                candidates.append(
                    Candidate(
                        left_dataset_id=left.id,
                        right_dataset_id=right.id,
                        left_variable=key,
                        right_variable=key,
                        cardinality=cardinality,
                        overlap=round(overlap, 4),
                        left_name=left.name,
                        right_name=right.name,
                    )
                )
                break  # the first identifier that works is the one to use
    return candidates


def store(
    db: Session, project_id: str | None, candidates: list[Candidate]
) -> list[DatasetRelationship]:
    """Save proposals that are not already recorded.

    Existing relationships are left exactly as they are: a detected link the
    user has since corrected must not be silently reverted by running detection
    again.
    """
    created: list[DatasetRelationship] = []
    for candidate in candidates:
        existing = db.scalar(
            select(DatasetRelationship).where(
                DatasetRelationship.left_dataset_id == candidate.left_dataset_id,
                DatasetRelationship.right_dataset_id == candidate.right_dataset_id,
                DatasetRelationship.left_variable == candidate.left_variable,
                DatasetRelationship.right_variable == candidate.right_variable,
            )
        )
        if existing is not None:
            continue
        relationship = DatasetRelationship(
            project_id=project_id,
            left_dataset_id=candidate.left_dataset_id,
            right_dataset_id=candidate.right_dataset_id,
            left_variable=candidate.left_variable,
            right_variable=candidate.right_variable,
            cardinality=candidate.cardinality,
            # A many-to-many join multiplies rows, so it is recorded but not
            # switched on for anyone to merge by accident.
            is_active=candidate.cardinality is not Cardinality.many_to_many,
            detected=True,
        )
        db.add(relationship)
        created.append(relationship)
    db.flush()
    return created


# --- merging ----------------------------------------------------------------


def merge_frames(
    left: Dataset,
    right: Dataset,
    left_variable: str,
    right_variable: str,
    how: str = "left",
    columns: list[str] | None = None,
    prefix: str = "",
) -> pd.DataFrame:
    """Join two datasets on their related key.

    Reads through DuckDB rather than loading both into pandas and merging: the
    join happens over Parquet, so only the columns asked for are read and the
    memory cost is the result rather than both inputs.
    """
    right_columns = [v.name for v in right.variables]
    if columns:
        wanted = [c for c in columns if c in right_columns]
        missing = sorted(set(columns) - set(right_columns))
        if missing:
            raise ValueError(
                f"'{right.name}' has no column(s) named: {', '.join(missing[:5])}"
            )
    else:
        wanted = right_columns
    # The join key would otherwise arrive twice under the same name.
    wanted = [c for c in wanted if c != right_variable]

    left_names = {v.name for v in left.variables}
    selected: list[str] = []
    for column in wanted:
        alias = f"{prefix}{column}" if prefix else column
        if alias in left_names:
            # Silently overwriting a left column with a right one loses data and
            # is impossible to notice afterwards.
            alias = f"{alias}__right"
        selected.append(f"r.{quote_ident(column)} AS {quote_ident(alias)}")

    join = "LEFT JOIN" if how == "left" else "INNER JOIN"
    sql = (
        f"SELECT l.*{',' if selected else ''} {', '.join(selected)} "
        f"FROM read_parquet({_quote_path(left.storage_path)}) l "
        f"{join} read_parquet({_quote_path(right.storage_path)}) r "
        f"ON l.{quote_ident(left_variable)} = r.{quote_ident(right_variable)}"
    )
    columns_out, rows = run_sql(sql)
    return pd.DataFrame(rows, columns=columns_out)
