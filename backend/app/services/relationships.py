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
from app.models import Cardinality, Dataset, DatasetRelationship, KeyMatch
from app.services.datasets import dataset_is_queryable
from app.services.query_engine import (
    _quote_path,
    column_types,
    kind_of,
    quote_ident,
    run_frame,
    run_sql,
)

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


def check_key_types(
    left: Dataset,
    right: Dataset,
    left_variable: str,
    right_variable: str,
    match: KeyMatch = KeyMatch.exact,
) -> None:
    """Refuse a join between a text key and a numeric one, in those words.

    Survey data does this constantly: one export writes the household id as
    "H0041" and the next as 41, or an id arrives quoted from a CSV and unquoted
    from a .dta. DuckDB answers such a join by casting the text side to a number
    and failing on the first value that is not one - and a ConversionException is
    not a ValueError, so it went past the endpoint's 422 handler and the merge
    came back a bare 500 with nothing in it anybody could act on.

    Read from the files rather than from the variables' `var_type`, which is the
    semantic type the interface offers and not what the column holds.

    A relationship that says how to match its keys has already answered this, so
    there is nothing here to refuse.
    """
    if match is not KeyMatch.exact:
        return
    here = column_types(left.storage_path).get(left_variable)
    there = column_types(right.storage_path).get(right_variable)
    # A column that is not in the file at all is the caller's own check to make,
    # and it has a better message for it than this one would.
    if here is None or there is None:
        return
    if kind_of(here) == kind_of(there):
        return

    named = (
        f"'{left_variable}'"
        if left_variable == right_variable
        else f"'{left_variable}' and '{right_variable}'"
    )
    raise ValueError(
        f"{named}: the key is {kind_of(here)} in '{left.name}' and "
        f"{kind_of(there)} in '{right.name}', so the two cannot be joined on it. "
        f"Make them the same type on both sides, or set this relationship to "
        f"match its keys as text."
    )


def key_expression(qualified: str, stored: str, match: KeyMatch) -> str:
    """One side of the join condition, converted the way the relationship says.

    `qualified` is the column already quoted and prefixed with its table alias,
    because these expressions mention it more than once. Nothing here comes from
    a person: the patterns are fixed and the only thing the relationship chooses
    is which of them to use, so no expression a caller typed reaches the SQL.
    """
    if match is KeyMatch.exact:
        return qualified
    numeric = kind_of(stored) == "a number"

    # Both of these go through _as_text first, and have to. A numeric key is a
    # DOUBLE, and casting 41.0 straight to text gives "41.0" - whose digits are
    # 410. Rendering it whole first gives "41", which is the id.
    if match is KeyMatch.digits:
        # Everything that is not a digit goes, and then the digits are read as
        # the number they spell - which is what drops the leading zeros, so
        # "H0041" and 41 arrive at the same place. Nothing left after stripping
        # means an id with no digits in it at all, which TRY_CAST turns into a
        # null that matches nothing.
        return f"TRY_CAST({_only(_as_text(qualified, numeric), '[^0-9]')} AS DOUBLE)"

    if match is KeyMatch.alphanumeric:
        # The letters are part of the id here, so they stay; the punctuation,
        # the spaces and the capitalisation are what differ between two systems
        # writing down the same thing.
        return f"upper({_only(_as_text(qualified, numeric), '[^A-Za-z0-9]')})"

    if match is KeyMatch.number:
        if numeric:
            return qualified
        # TRY_CAST, not CAST: a value that is not a number becomes null and so
        # matches nothing, where a plain cast fails the whole join on the first
        # one it meets - which is the 500 this feature exists to answer.
        return f"TRY_CAST(trim({qualified}) AS DOUBLE)"

    return _as_text(qualified, numeric)


def _as_text(qualified: str, numeric: bool) -> str:
    """The key as a person would write it down."""
    if not numeric:
        # Trimmed, because an id that came through a CSV often arrives padded
        # and " 41" is not "41" to anything but a person reading it.
        return f"trim(CAST({qualified} AS VARCHAR))"
    # A household id read from a .dta is a DOUBLE, and 41.0 as text is "41.0" -
    # which matches the string "41" no better than the number did. So a whole
    # number is rendered whole. TRY_CAST guards the one case that would fail,
    # a value too large for a 128-bit integer, which is not an id but is not
    # worth an error either.
    return (
        f"CASE WHEN {qualified} IS NULL THEN NULL "
        f"WHEN {qualified} = floor({qualified}) THEN COALESCE("
        f"CAST(TRY_CAST({qualified} AS HUGEINT) AS VARCHAR), "
        f"CAST({qualified} AS VARCHAR)) "
        f"ELSE CAST({qualified} AS VARCHAR) END"
    )


def _only(text_expression: str, unwanted: str) -> str:
    """A text expression with every character matching `unwanted` removed.

    `unwanted` is one of this module's own literals, never anything a caller
    supplied. DuckDB matches with RE2, which has no backtracking, so even a
    pattern that did come from outside could not be made to run away - but none
    does.
    """
    return f"regexp_replace({text_expression}, '{unwanted}', '', 'g')"


def join_condition(
    left: Dataset,
    right: Dataset,
    left_variable: str,
    right_variable: str,
    match: KeyMatch = KeyMatch.exact,
    left_alias: str = "l",
    right_alias: str = "r",
) -> str:
    """The `ON` for a merge, with both keys converted the same way."""
    here = column_types(left.storage_path).get(left_variable, "")
    there = column_types(right.storage_path).get(right_variable, "")
    return (
        f"{key_expression(f'{left_alias}.{quote_ident(left_variable)}', here, match)}"
        f" = "
        f"{key_expression(f'{right_alias}.{quote_ident(right_variable)}', there, match)}"
    )


def matched_rows(
    left: Dataset,
    right: Dataset,
    left_variable: str,
    right_variable: str,
    match: KeyMatch,
) -> int:
    """How many pairs the keys actually make, counted before anything is built.

    Worth one aggregate pass when a relationship has been told to convert its
    keys, because that is the case where the merge can succeed and mean nothing:
    a left join that matched no rows writes out the left side with a column of
    blanks beside it, and nothing on the page would say the conversion had not
    worked.
    """
    on = join_condition(left, right, left_variable, right_variable, match)
    sql = (
        f"SELECT COUNT(*) FROM read_parquet({_quote_path(left.storage_path)}) l "
        f"JOIN read_parquet({_quote_path(right.storage_path)}) r ON {on}"
    )
    _, rows = run_sql(sql)
    return int(rows[0][0]) if rows else 0


TIDYING = (KeyMatch.digits, KeyMatch.alphanumeric)

HOW = {
    KeyMatch.text: "as text",
    KeyMatch.number: "as numbers",
    KeyMatch.digits: "by the numbers inside them",
    KeyMatch.alphanumeric: "ignoring punctuation and capitalisation",
}


def collision_warning(dataset: Dataset, variable: str, match: KeyMatch) -> list[str]:
    """A note when ignoring part of an id makes two different ids the same one.

    This is the price of the two modes that throw part of the key away, and it
    has to be said rather than discovered. "H0041" and "P0041" are a household
    and a person in plenty of surveys, and matching by the digits inside them
    makes both of them 41 - after which a merge joins every person to the wrong
    household and the row count looks entirely reasonable.

    A warning and not a refusal: whether the prefix means anything is a fact
    about the survey, and somebody choosing this option may well know that it
    does not. What they cannot do is see it from here, so this shows them.
    """
    if match not in TIDYING:
        return []
    types = column_types(dataset.storage_path)
    if variable not in types:
        return []

    tidied = key_expression(quote_ident(variable), types[variable], match)
    plain = _as_text(quote_ident(variable), kind_of(types[variable]) == "a number")
    sql = (
        f"WITH pairs AS (SELECT {tidied} AS k, {plain} AS original "
        f"FROM read_parquet({_quote_path(dataset.storage_path)})), "
        f"clashes AS (SELECT k, count(DISTINCT original) AS n, "
        f"list(DISTINCT original)[1:3] AS few FROM pairs WHERE k IS NOT NULL "
        f"GROUP BY 1 HAVING count(DISTINCT original) > 1) "
        f"SELECT (SELECT count(*) FROM clashes), "
        f"(SELECT few FROM clashes ORDER BY n DESC, k LIMIT 1)"
    )
    _, rows = run_sql(sql)
    if not rows:
        return []
    groups, few = int(rows[0][0] or 0), list(rows[0][1] or [])
    if not groups:
        return []

    shown = " and ".join(f"'{value}'" for value in sorted(str(v) for v in few)[:2])
    return [
        f"Matching the keys {HOW[match]} makes {groups:,} set(s) of different "
        f"ids in '{dataset.name}' into one key - {shown}, for instance. If those "
        f"are not the same thing, this merge is joining the wrong rows."
    ]


def unmatched_warning(
    left: Dataset,
    right: Dataset,
    left_variable: str,
    right_variable: str,
    match: KeyMatch,
) -> list[str]:
    """A note when a converted key still lines nothing up."""
    if match is KeyMatch.exact:
        return []
    if matched_rows(left, right, left_variable, right_variable, match):
        return []
    return [
        f"Matching the keys {HOW[match]} lined up no rows at all, so nothing from "
        f"'{right.name}' reached this dataset. The two ids may differ by more "
        f"than how they are written."
    ]


def merge_frames(
    left: Dataset,
    right: Dataset,
    left_variable: str,
    right_variable: str,
    how: str = "left",
    columns: list[str] | None = None,
    prefix: str = "",
    match: KeyMatch = KeyMatch.exact,
) -> pd.DataFrame:
    """Join two datasets on their related key.

    Reads through DuckDB rather than loading both into pandas and merging: the
    join happens over Parquet, so only the columns asked for are read and the
    memory cost is the result rather than both inputs.
    """
    check_key_types(left, right, left_variable, right_variable, match)

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
        f"ON {join_condition(left, right, left_variable, right_variable, match)}"
    )
    # Through DuckDB's own conversion rather than a list of lists: building a
    # Python object per cell cost fourteen seconds and 400 MB of heap on a
    # 200,000-row join before anything had been done with it.
    return run_frame(sql)
