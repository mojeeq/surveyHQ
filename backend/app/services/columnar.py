"""High-throughput DuckDB/Parquet helpers used by ingest and derived datasets.

The core rule here is simple: large survey data should stay columnar. Operations
that can be expressed as a DuckDB query are streamed directly from source files
to Parquet instead of being materialised as Python tuples or pandas frames.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from app.core.config import settings


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def quote_path(path: str | Path) -> str:
    return quote_literal(str(path))


def _configured_threads() -> int:
    if settings.duckdb_threads > 0:
        return settings.duckdb_threads
    cpus = os.cpu_count() or 4
    # Leave headroom for the API, postgres and celery. An operator can override
    # this explicitly on a large analytical host.
    return max(1, min(8, max(1, cpus // 2)))


def connect() -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection using deployment-level resource settings."""
    con = duckdb.connect(database=":memory:")
    con.execute(f"SET threads TO {_configured_threads()}")
    con.execute(f"SET memory_limit = {quote_literal(settings.duckdb_memory_limit)}")
    temp_dir = settings.duckdb_temp_path
    temp_dir.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory = {quote_path(temp_dir)}")
    # Large GROUP BY / UNION / COPY operations do not need insertion-order
    # preservation and DuckDB can use less memory when it is disabled.
    con.execute("SET preserve_insertion_order = false")
    return con


def parquet_columns(path: str | Path) -> list[tuple[str, str]]:
    con = connect()
    try:
        rows = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet({quote_path(path)})"
        ).fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]
    finally:
        con.close()


def parquet_row_count(path: str | Path) -> int:
    con = connect()
    try:
        row = con.execute(
            f"SELECT COUNT(*) FROM read_parquet({quote_path(path)})"
        ).fetchone()
        return int(row[0] if row else 0)
    finally:
        con.close()


def _temporary_output(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp.parquet")


def _copy_query(con: duckdb.DuckDBPyConnection, query: str, destination: Path) -> Path:
    temporary = _temporary_output(destination)
    try:
        con.execute(
            "COPY (" + query + ") TO " + quote_path(temporary)
            + " (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def frame_to_parquet(frame: pd.DataFrame, destination: Path) -> Path:
    """Write only the incoming frame; never touch the existing survey in RAM."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(destination, index=False, engine="pyarrow", compression="zstd")
    return destination


def append_frame_to_parquet(
    existing_path: str | Path,
    incoming: pd.DataFrame,
    destination: str | Path,
    *,
    source_column: str | None = None,
    existing_source_value: str = "original upload",
) -> tuple[list[str], list[str]]:
    """Append a pandas *incoming* frame to an existing Parquet file in DuckDB.

    Only the newly-arrived rows are materialised in pandas. The existing survey
    remains in Parquet and DuckDB performs UNION ALL BY NAME directly into the
    replacement file. The destination is swapped atomically after COPY finishes.

    Returns (existing_columns, incoming_columns) for schema-change warnings.
    """
    existing_path = Path(existing_path)
    destination = Path(destination)
    incoming_path = destination.with_name(f".incoming.{uuid.uuid4().hex}.parquet")
    try:
        frame_to_parquet(incoming, incoming_path)
        existing_columns = [name for name, _ in parquet_columns(existing_path)]
        incoming_columns = [name for name, _ in parquet_columns(incoming_path)]

        existing_select = f"SELECT * FROM read_parquet({quote_path(existing_path)})"
        if source_column and source_column not in existing_columns:
            existing_select = (
                "SELECT *, "
                + quote_literal(existing_source_value)
                + " AS "
                + quote_ident(source_column)
                + f" FROM read_parquet({quote_path(existing_path)})"
            )
        incoming_select = f"SELECT * FROM read_parquet({quote_path(incoming_path)})"

        con = connect()
        try:
            _copy_query(
                con,
                f"{existing_select} UNION ALL BY NAME {incoming_select}",
                destination,
            )
        finally:
            con.close()
        return existing_columns, incoming_columns
    finally:
        incoming_path.unlink(missing_ok=True)


def overlapping_frame_values(
    existing_path: str | Path,
    incoming: pd.DataFrame,
    column: str,
    *,
    examples: int = 3,
) -> tuple[int, list[Any]]:
    """Find duplicate identifiers while only the incoming rows live in pandas."""
    if column not in incoming.columns:
        return 0, []
    con = connect()
    try:
        con.register("incoming_rows", incoming[[column]])
        col = quote_ident(column)
        base = (
            f"SELECT DISTINCT e.{col} AS value "
            f"FROM read_parquet({quote_path(existing_path)}) e "
            f"INNER JOIN incoming_rows i ON e.{col} = i.{col} "
            f"WHERE e.{col} IS NOT NULL"
        )
        count = int(con.execute(f"SELECT COUNT(*) FROM ({base}) x").fetchone()[0])
        sample = [row[0] for row in con.execute(f"{base} LIMIT {int(examples)}").fetchall()]
        return count, sample
    finally:
        con.close()


def overlapping_values(
    left_path: str | Path,
    right_path: str | Path,
    column: str,
    *,
    examples: int = 3,
) -> tuple[int, list[Any]]:
    """Count shared non-null identifiers without building Python sets of rows."""
    col = quote_ident(column)
    con = connect()
    try:
        base = (
            f"SELECT DISTINCT l.{col} AS value "
            f"FROM read_parquet({quote_path(left_path)}) l "
            f"INNER JOIN read_parquet({quote_path(right_path)}) r "
            f"ON l.{col} = r.{col} WHERE l.{col} IS NOT NULL"
        )
        count = int(con.execute(f"SELECT COUNT(*) FROM ({base}) x").fetchone()[0])
        sample = [row[0] for row in con.execute(f"{base} LIMIT {int(examples)}").fetchall()]
        return count, sample
    finally:
        con.close()


def copy_join_to_parquet(
    *,
    left_path: str | Path,
    right_path: str | Path,
    left_key: str,
    right_key: str,
    right_columns: Iterable[str],
    left_columns: set[str],
    destination: str | Path,
    how: str = "left",
    prefix: str = "",
) -> tuple[int, list[str]]:
    """Stream a relationship join directly to Parquet and return its shape."""
    selected: list[str] = []
    for column in right_columns:
        if column == right_key:
            continue
        alias = f"{prefix}{column}" if prefix else column
        if alias in left_columns:
            alias = f"{alias}__right"
        selected.append(f"r.{quote_ident(column)} AS {quote_ident(alias)}")

    join = "LEFT JOIN" if how == "left" else "INNER JOIN"
    query = (
        f"SELECT l.*{',' if selected else ''} {', '.join(selected)} "
        f"FROM read_parquet({quote_path(left_path)}) l "
        f"{join} read_parquet({quote_path(right_path)}) r "
        f"ON l.{quote_ident(left_key)} = r.{quote_ident(right_key)}"
    )

    destination = Path(destination)
    con = connect()
    try:
        _copy_query(con, query, destination)
        row_count = int(
            con.execute(
                f"SELECT COUNT(*) FROM read_parquet({quote_path(destination)})"
            ).fetchone()[0]
        )
        names = [
            str(row[0])
            for row in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet({quote_path(destination)})"
            ).fetchall()
        ]
        return row_count, names
    finally:
        con.close()


def preview(path: str | Path, limit: int = 20) -> dict[str, Any]:
    """Read only the requested preview rows instead of loading a whole Parquet."""
    con = connect()
    try:
        cursor = con.execute(
            f"SELECT * FROM read_parquet({quote_path(path)}) LIMIT {max(0, int(limit))}"
        )
        columns = [item[0] for item in cursor.description or []]
        rows = [list(row) for row in cursor.fetchall()]
        return {"columns": columns, "rows": rows}
    finally:
        con.close()


def delimited_to_parquet(source: str | Path, destination: str | Path) -> Path:
    """Parse a large UTF-8 CSV/TAB file in DuckDB and stream it to Parquet."""
    source = Path(source)
    destination = Path(destination)
    delimiter = "\t" if source.suffix.lower() in {".tab", ".tsv", ".txt"} else ","
    query = (
        "SELECT * FROM read_csv("
        + quote_path(source)
        + ", auto_detect=true, header=true, delim="
        + quote_literal(delimiter)
        + ", sample_size=100000, ignore_errors=false)"
    )
    con = connect()
    try:
        _copy_query(con, query, destination)
        return destination
    finally:
        con.close()


@dataclass
class ColumnProfile:
    name: str
    storage_type: str
    non_null: int
    distinct: int
    minimum: Any = None
    maximum: Any = None
    mean: Any = None
    has_fractional: bool = False


def profile_parquet(
    path: str | Path,
    *,
    hidden_suffix: str = "__mv",
    batch_size: int = 12,
) -> tuple[int, list[ColumnProfile], dict[str, list[str]]]:
    """Profile a wide Parquet in batched scans instead of one query per column.

    A 600-column census file previously caused more than a thousand complete
    scans (statistics, integrality tests, tagged missings). This groups many
    aggregates into each scan while keeping exact distinct counts for metadata.
    Hidden tagged-missing companion columns are retained in the profile because
    the query engine needs them even though the UI hides them.
    """
    con = connect()
    try:
        described = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet({quote_path(path)})"
        ).fetchall()
        total = int(
            con.execute(f"SELECT COUNT(*) FROM read_parquet({quote_path(path)})").fetchone()[0]
        )
        columns = [(str(row[0]), str(row[1])) for row in described]
        storage_by_name = dict(columns)

        profiles: list[ColumnProfile] = []
        for start in range(0, len(columns), max(1, batch_size)):
            batch = columns[start : start + max(1, batch_size)]
            expressions: list[str] = []
            shape: list[tuple[str, str, bool]] = []
            for index, (name, storage) in enumerate(batch):
                q = quote_ident(name)
                numeric = any(
                    token in storage.upper()
                    for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "HUGEINT")
                )
                expressions.extend(
                    [
                        f"COUNT({q}) AS c_{index}",
                        f"COUNT(DISTINCT {q}) AS d_{index}",
                    ]
                )
                if numeric:
                    expressions.extend(
                        [
                            f"MIN({q}) AS min_{index}",
                            f"MAX({q}) AS max_{index}",
                            f"AVG({q}) AS mean_{index}",
                            (
                                f"COUNT(*) FILTER (WHERE {q} IS NOT NULL "
                                f"AND {q} != floor({q})) AS frac_{index}"
                            ),
                        ]
                    )
                shape.append((name, storage, numeric))

            row = con.execute(
                f"SELECT {', '.join(expressions)} FROM read_parquet({quote_path(path)})"
            ).fetchone()
            cursor = 0
            for name, storage, numeric in shape:
                non_null = int(row[cursor] or 0)
                distinct = int(row[cursor + 1] or 0)
                cursor += 2
                minimum = maximum = mean = None
                fractional = False
                if numeric:
                    minimum, maximum, mean = row[cursor : cursor + 3]
                    fractional = int(row[cursor + 3] or 0) > 0
                    cursor += 4
                profiles.append(
                    ColumnProfile(
                        name=name,
                        storage_type=storage,
                        non_null=non_null,
                        distinct=distinct,
                        minimum=minimum,
                        maximum=maximum,
                        mean=mean,
                        has_fractional=fractional,
                    )
                )

        tags: dict[str, list[str]] = {}
        for name, _storage in columns:
            if name.endswith(hidden_suffix):
                continue
            companion = f"{name}{hidden_suffix}"
            if companion not in storage_by_name:
                continue
            q = quote_ident(companion)
            tags[name] = sorted(
                str(row[0])
                for row in con.execute(
                    f"SELECT DISTINCT {q} FROM read_parquet({quote_path(path)}) "
                    f"WHERE {q} IS NOT NULL"
                ).fetchall()
            )
        return total, profiles, tags
    finally:
        con.close()
