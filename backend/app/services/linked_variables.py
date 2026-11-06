"""Variables brought into a dataset from another one, in place.

A merge makes a new dataset, which is right for a new piece of analysis and
wrong for the board that already exists: its charts, indicators and quality
checks point at the dataset they were built on, and moving them all to a new
one is the redoing this is here to save. So a dataset can instead take
variables from another and keep its own id - the household file gains the
district's population, or the person file gains the household's wealth
quintile - and everything built on it goes on working, now with the new
variables to use.

It is a recipe, not a copy. The rows of the dataset are kept exactly as they
are, in the same order, with the other dataset's values beside them where the
keys match and blanks where they do not. Whenever either dataset gets new
data - a newer export replacing it, rows appended, a command changing it - the
variables are brought in again, so they never hold last week's values beside
this week's rows.

The other dataset has to have one row per key. More than one would mean
repeating rows of this one to make room for them, and a household file that
quietly grows a row per person is the mistake this refuses rather than makes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import Dataset, DatasetRelationship, KeyMatch
from app.services.datasets import _apply_ingest, dataset_directory, dataset_is_queryable
from app.services.ingest import MISSING_TAG_SUFFIX, IngestResult
from app.services.query_engine import (
    QueryError,
    _quote_path,
    column_types,
    copy_to_parquet,
    quote_ident,
    run_sql,
)
from app.services.relationships import PREFERRED_KEYS, check_key_types, key_expression
from app.services.stata_frame import columns_of, row_count, variables_of

logger = get_logger(__name__)

# Where the recipes live on the dataset.
LINKS = "linked_variables"
# The notes the last bring-in left, kept apart so the next one replaces them
# without touching what the import itself had to say.
NOTES = "linked_variables_notes"
# How many unmatched or repeated keys a message names.
EXAMPLES = 3


@dataclass
class Link:
    """One dataset's variables, brought into another on one or more keys."""

    id: str
    source_id: str
    source_name: str
    keys: list[tuple[str, str]]
    key_match: KeyMatch
    variables: list[str]
    status: dict[str, Any] = field(default_factory=dict)

    def stored(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "keys": [{"here": here, "there": there} for here, there in self.keys],
            "key_match": self.key_match.value,
            "variables": list(self.variables),
            "status": dict(self.status),
        }

    @classmethod
    def read(cls, stored: dict[str, Any]) -> Link:
        return cls(
            id=str(stored.get("id") or uuid4().hex),
            source_id=str(stored.get("source_id") or ""),
            source_name=str(stored.get("source_name") or ""),
            keys=[
                (str(pair.get("here") or ""), str(pair.get("there") or ""))
                for pair in stored.get("keys") or []
            ],
            key_match=KeyMatch(stored.get("key_match") or KeyMatch.exact.value),
            variables=[str(name) for name in stored.get("variables") or []],
            status=dict(stored.get("status") or {}),
        )


@dataclass
class Match:
    """How the keys line up, counted before anything is written."""

    rows: int
    matched: int

    @property
    def unmatched(self) -> int:
        return self.rows - self.matched

    def sentence(self, target: str, source: str) -> str:
        if not self.rows:
            return f"'{target}' has no rows yet."
        if self.matched == self.rows:
            return f"Every one of the {self.rows:,} rows of '{target}' has a match in '{source}'."
        if not self.matched:
            return (
                f"None of the {self.rows:,} rows of '{target}' has a match in '{source}', "
                "so the variables would be blank everywhere. The keys may be written "
                "differently on the two sides - try matching them as text or as numbers."
            )
        return (
            f"{self.matched:,} of the {self.rows:,} rows of '{target}' have a match in "
            f"'{source}'; the other {self.unmatched:,} will be blank."
        )


def links(dataset: Dataset) -> list[Link]:
    """The variables this dataset brings in, as recipes."""
    return [Link.read(one) for one in (dataset.meta or {}).get(LINKS) or []]


def provided(dataset: Dataset) -> set[str]:
    """The columns of this dataset that a link brings in, companions included.

    A newer export will not have them - they were never in the file - and the
    import that replaces the data should not report them as lost: they are
    brought in again as soon as the data has landed.
    """
    names = {name for link in links(dataset) for name in link.variables}
    return names | {f"{name}{MISSING_TAG_SUFFIX}" for name in names}


def source_ids(dataset: Dataset) -> set[str]:
    return {link.source_id for link in links(dataset)}


def _save(dataset: Dataset, found: list[Link]) -> None:
    meta = dict(dataset.meta or {})
    meta[LINKS] = [link.stored() for link in found]
    dataset.meta = meta


# --- choosing what to bring in -----------------------------------------------


def suggest_keys(
    db: Session, target: Dataset, source: Dataset
) -> tuple[list[tuple[str, str]], KeyMatch]:
    """The keys to match on, before anybody has said.

    A relationship between the two, where one has been drawn: whoever drew it
    has already said which columns are the same thing, and how to compare
    them. Otherwise a column the two share by name that identifies a row of
    the other - the interview key of a Survey Solutions export, usually.
    """
    for one in db.scalars(select(DatasetRelationship)).all():
        if (one.left_dataset_id, one.right_dataset_id) == (target.id, source.id):
            return [(one.left_variable, one.right_variable)], one.key_match
        if (one.left_dataset_id, one.right_dataset_id) == (source.id, target.id):
            return [(one.right_variable, one.left_variable)], one.key_match

    here = {v.name for v in target.variables if not v.name.endswith(MISSING_TAG_SUFFIX)}
    there = [v.name for v in source.variables if v.name in here]
    ordered = [name for name in PREFERRED_KEYS if name in there] + [
        name for name in there if name not in PREFERRED_KEYS
    ]
    for name in ordered:
        if _repeated(source, [name], KeyMatch.exact)[0] == 0 and _distinct(source, name) > 1:
            return [(name, name)], KeyMatch.exact
    return [], KeyMatch.exact


def _distinct(dataset: Dataset, column: str) -> int:
    _, rows = run_sql(
        f"SELECT COUNT(DISTINCT {quote_ident(column)}) "
        f"FROM read_parquet({_quote_path(dataset.storage_path)})"
    )
    return int(rows[0][0]) if rows else 0


def plan(
    db: Session,
    target: Dataset,
    source: Dataset,
    keys: list[tuple[str, str]],
    key_match: KeyMatch,
    variables: list[str],
    require_variables: bool = True,
) -> Link:
    """Check a link before it is made, and say plainly what is wrong with it."""
    if source.id == target.id:
        raise QueryError("A dataset cannot bring variables in from itself.")
    if not dataset_is_queryable(source):
        raise QueryError(f"'{source.name}' has no data yet.")
    if not dataset_is_queryable(target):
        raise QueryError(f"'{target.name}' has no data yet.")
    if not keys:
        raise QueryError(
            f"Choose the key to match on: a variable '{target.name}' and "
            f"'{source.name}' both have, such as the interview key."
        )

    existing = links(target)
    brought = provided(target)
    own = {v.name for v in target.variables} - brought
    theirs = {v.name for v in source.variables}
    for here, there in keys:
        if here not in own:
            raise QueryError(
                f"'{target.name}' has no variable called '{here}' of its own to match on"
                + (" - it is one brought in from another dataset" if here in brought else "")
                + "."
            )
        if there not in theirs:
            raise QueryError(f"'{source.name}' has no variable called '{there}'.")
        try:
            check_key_types(target, source, here, there, key_match)
        except ValueError as exc:
            raise QueryError(str(exc)) from None

    key_names = {there for _, there in keys}
    wanted = [
        name
        for name in dict.fromkeys(variables)
        if name not in key_names and not name.endswith(MISSING_TAG_SUFFIX)
    ]
    if not wanted and require_variables:
        raise QueryError(f"Choose at least one variable to bring in from '{source.name}'.")
    absent = [name for name in wanted if name not in theirs]
    if absent:
        raise QueryError(f"'{source.name}' has no variable(s) called: {', '.join(absent[:5])}.")

    same = next(
        (
            link
            for link in existing
            if link.source_id == source.id
            and link.keys == list(keys)
            and link.key_match == key_match
        ),
        None,
    )
    elsewhere = {name for link in existing if link is not same for name in link.variables}
    clashes = [name for name in wanted if name in own or name in elsewhere]
    if clashes:
        raise QueryError(
            f"'{target.name}' already has "
            + ", ".join(f"'{name}'" for name in clashes[:5])
            + ". Leave "
            + ("it" if len(clashes) == 1 else "them")
            + " out, or rename the one in "
            f"'{target.name}' first."
        )

    if _depends_on(db, source, target.id):
        raise QueryError(
            f"'{source.name}' is itself built from '{target.name}', so each would "
            "have to be brought up to date before the other."
        )

    repeated, example = _repeated(source, [there for _, there in keys], key_match)
    if repeated:
        shown = ", ".join(str(one) for one in example)
        raise QueryError(
            f"'{source.name}' has more than one row for {repeated:,} value(s) of "
            f"{_named([there for _, there in keys])} (for example {shown}). Bringing its "
            f"variables in would mean repeating rows of '{target.name}'. Match on a key "
            f"that is unique in '{source.name}' - add the second key of a roster, say."
        )

    if same is not None:
        return Link(
            id=same.id,
            source_id=source.id,
            source_name=source.name,
            keys=list(keys),
            key_match=key_match,
            variables=list(dict.fromkeys([*same.variables, *wanted])),
            status=same.status,
        )
    return Link(
        id=uuid4().hex,
        source_id=source.id,
        source_name=source.name,
        keys=list(keys),
        key_match=key_match,
        variables=wanted,
    )


def _named(columns: list[str]) -> str:
    return " + ".join(f"'{column}'" for column in columns)


def _depends_on(
    db: Session, dataset: Dataset, target_id: str, seen: set[str] | None = None
) -> bool:
    """Whether `dataset` is built, however indirectly, from `target_id`."""
    seen = seen if seen is not None else set()
    if dataset.id in seen:
        return False
    seen.add(dataset.id)
    derivation = dataset.derivation or {}
    upstream = set(source_ids(dataset))
    if derivation.get("type") == "merge":
        upstream |= {
            one
            for one in (derivation.get("left_dataset_id"), derivation.get("right_dataset_id"))
            if one
        }
    if target_id in upstream:
        return True
    for one in upstream:
        found = db.get(Dataset, one)
        if found is not None and _depends_on(db, found, target_id, seen):
            return True
    return False


def _key(alias: str, column: str, stored: str, match: KeyMatch) -> str:
    return key_expression(f"{alias}.{quote_ident(column)}", stored, match)


def _repeated(source: Dataset, columns: list[str], match: KeyMatch) -> tuple[int, list[Any]]:
    """How many keys the other dataset repeats, and a few of them."""
    types = column_types(source.storage_path)
    keys = [_key("s", column, types.get(column, ""), match) for column in columns]
    present = " AND ".join(f"{key} IS NOT NULL" for key in keys)
    grouped = ", ".join(keys)
    shown = keys[0] if len(keys) == 1 else f"concat_ws(' / ', {grouped})"
    sql = (
        f"SELECT COUNT(*), list(shown ORDER BY shown)[1:{EXAMPLES}] FROM ("
        f"SELECT {shown} AS shown FROM read_parquet({_quote_path(source.storage_path)}) s "
        f"WHERE {present} GROUP BY {grouped} HAVING COUNT(*) > 1)"
    )
    _, rows = run_sql(sql)
    if not rows:
        return 0, []
    return int(rows[0][0] or 0), list(rows[0][1] or [])


def _on(target: Dataset, source: Dataset, link: Link, alias: str) -> str:
    here_types = column_types(target.storage_path)
    there_types = column_types(source.storage_path)
    return " AND ".join(
        f"{_key('t', here, here_types.get(here, ''), link.key_match)} = "
        f"{_key(alias, there, there_types.get(there, ''), link.key_match)}"
        for here, there in link.keys
    )


def check(target: Dataset, source: Dataset, link: Link) -> Match:
    """How many rows of the dataset the other one has a match for."""
    sql = (
        f"SELECT COUNT(*), COUNT(s.__found) "
        f"FROM read_parquet({_quote_path(target.storage_path)}) t "
        f"LEFT JOIN (SELECT *, TRUE AS __found FROM "
        f"read_parquet({_quote_path(source.storage_path)})) s ON {_on(target, source, link, 's')}"
    )
    _, rows = run_sql(sql)
    total, matched = (int(rows[0][0] or 0), int(rows[0][1] or 0)) if rows else (0, 0)
    return Match(rows=total, matched=matched)


# --- bringing them in ----------------------------------------------------------


def add(db: Session, target: Dataset, link: Link) -> Match:
    """Keep a link on the dataset and bring its variables in now."""
    source = db.get(Dataset, link.source_id)
    found = [one for one in links(target) if one.id != link.id]
    found.append(link)
    _save(target, found)
    bring_in(db, target)
    return check(target, source, link) if source is not None else Match(target.row_count, 0)


def remove(db: Session, target: Dataset, link_id: str, keep_columns: bool = False) -> Link:
    """Stop bringing one dataset's variables in.

    By default the variables go too, so the dataset is what it would have been
    had they never been brought in. Kept, they stay as they are now and are no
    longer brought up to date - the choice for somebody who wanted a one-off
    copy after all.
    """
    found = links(target)
    gone = next((one for one in found if one.id == link_id), None)
    if gone is None:
        raise QueryError("That link is not on this dataset any more.")
    _save(target, [one for one in found if one.id != link_id])
    if not keep_columns:
        bring_in(db, target, dropping=gone.variables)
    return gone


def bring_in(db: Session, target: Dataset, dropping: list[str] | None = None) -> list[str]:
    """Write the dataset again with every link's variables brought in fresh.

    One pass for all of them: the dataset's own columns, without any earlier
    copy of a brought-in variable, and each other dataset's values beside them
    by key. Row order is the dataset's own, held by its position in the file,
    so a table read top to bottom reads the same afterwards.

    Returns the notes worth putting beside the data - a link whose keys no
    longer line anything up, say. A link that cannot be brought in at all -
    its dataset deleted, or its keys now repeated - raises, and the dataset
    keeps the data it had.
    """
    found = links(target)
    sources: list[tuple[Link, Dataset]] = []
    for link in found:
        source = db.get(Dataset, link.source_id)
        if source is None:
            raise QueryError(
                f"'{link.source_name}', which {', '.join(link.variables[:3])} "
                f"{'is' if len(link.variables) == 1 else 'are'} brought in from, no longer exists."
            )
        if not dataset_is_queryable(source):
            raise QueryError(f"'{source.name}' has no data to bring in.")
        repeated, example = _repeated(source, [there for _, there in link.keys], link.key_match)
        if repeated:
            raise QueryError(
                f"'{source.name}' now has more than one row for {repeated:,} value(s) of "
                f"{_named([there for _, there in link.keys])} (for example "
                f"{', '.join(str(one) for one in example)}), so its variables were not "
                f"brought in again. '{target.name}' keeps the values it had."
            )
        sources.append((link, source))

    present = [name for name, _ in columns_of(target.storage_path)]
    brought = {name for link in found for name in link.variables} | set(dropping or [])
    brought |= {f"{name}{MISSING_TAG_SUFFIX}" for name in brought}
    dropped = [name for name in present if name in brought]

    selects: list[str] = []
    joins: list[str] = []
    for index, (link, source) in enumerate(sources):
        alias = f"s{index}"
        theirs = {name for name, _ in columns_of(source.storage_path)}
        for name in link.variables:
            if name not in theirs:
                raise QueryError(
                    f"'{source.name}' no longer has a variable called '{name}', so it "
                    f"could not be brought into '{target.name}'."
                )
            selects.append(f"{alias}.{quote_ident(name)} AS {quote_ident(name)}")
            companion = f"{name}{MISSING_TAG_SUFFIX}"
            if companion in theirs:
                selects.append(f"{alias}.{quote_ident(companion)} AS {quote_ident(companion)}")
        joins.append(
            f"LEFT JOIN read_parquet({_quote_path(source.storage_path)}) {alias} "
            f"ON {_on(target, source, link, alias)}"
        )

    excluded = ", ".join(quote_ident(name) for name in ["__row", *dropped])
    sql = (
        f"SELECT t.* EXCLUDE ({excluded}){''.join(f', {one}' for one in selects)} "
        f"FROM (SELECT * EXCLUDE (file_row_number), file_row_number AS __row FROM "
        f"read_parquet({_quote_path(target.storage_path)}, file_row_number = true)) t "
        f"{' '.join(joins)} ORDER BY t.__row"
    )
    directory = dataset_directory(target.id)
    directory.mkdir(parents=True, exist_ok=True)
    parquet = directory / f"data-{uuid4().hex}.parquet"
    copy_to_parquet(sql, str(parquet))
    rows = row_count(parquet)

    # The dataset's own labels for its own columns; the other dataset's for
    # what came from it. Labels written by hand on this dataset are put back
    # over both by _apply_ingest, as after any other change.
    labels = {v.name: v.label for v in target.variables if v.label and v.name not in brought}
    value_labels = {
        v.name: v.value_labels for v in target.variables if v.value_labels and v.name not in brought
    }
    for link, source in sources:
        for variable in source.variables:
            if variable.name in link.variables:
                if variable.label:
                    labels[variable.name] = variable.label
                if variable.value_labels:
                    value_labels[variable.name] = variable.value_labels

    notes: list[str] = []
    now = utcnow().isoformat()
    for link, source in sources:
        match = check(target, source, link)
        link.status = {"status": "ok", "at": now, "rows": match.rows, "matched": match.matched}
        if match.rows and not match.matched:
            notes.append(
                f"No row matched '{source.name}' on {_named([h for h, _ in link.keys])}, so "
                f"{', '.join(link.variables[:3])} {'is' if len(link.variables) == 1 else 'are'} "
                "blank everywhere."
            )

    meta = dict(target.meta or {})
    earlier = set(meta.get(NOTES) or [])
    kept = [one for one in meta.get("warnings") or [] if one not in earlier]

    _apply_ingest(
        db,
        target,
        IngestResult(
            parquet_path=parquet,
            row_count=rows,
            column_count=len(columns_of(parquet)),
            file_size=parquet.stat().st_size,
            variables=variables_of(parquet, labels, value_labels),
            warnings=[*kept, *notes],
        ),
    )
    meta = dict(target.meta or {})
    meta[NOTES] = notes
    meta[LINKS] = [link.stored() for link in found]
    target.meta = meta
    return notes


def note_failure(target: Dataset, message: str) -> None:
    """Mark every link on the dataset as not brought in this time, and why."""
    now = utcnow().isoformat()
    found = links(target)
    for link in found:
        link.status = {**link.status, "status": "failed", "message": message, "at": now}
    _save(target, found)
