"""Handing a whole dataset back as a file.

Analysis in the browser answers questions somebody thought to ask. Sooner or
later a statistician wants the table itself - to run their own model on it, to
send it to a colleague, to keep it with the report. A merged dataset makes the
point: it exists only here, so without this the only copy of the join is inside
the platform.

Written from the Parquet rather than from the uploaded file, so a dataset that
never had one - a merge, or a file changed by commands - downloads like any
other, and what comes out is what the platform is actually querying.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from app.core.logging import get_logger
from app.models import Dataset
from app.services.query_engine import QueryError, _quote_path

logger = get_logger(__name__)

FORMATS = {
    "csv": (".csv", "text/csv"),
    "xlsx": (
        ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "dta": (".dta", "application/x-stata-dta"),
}

# openpyxl holds the whole sheet in memory and Excel itself stops at 1,048,576
# rows, so a survey larger than this is offered as CSV or Stata instead of
# being written out to a file Excel would refuse to open.
XLSX_ROW_LIMIT = 1_000_000


def download_file(dataset: Dataset, fmt: str, directory: Path) -> Path:
    """Write the dataset out in `fmt` and return the path to send."""
    if fmt not in FORMATS:
        raise QueryError(f"'{fmt}' is not a format this can write")
    suffix, _ = FORMATS[fmt]
    stem = dataset.slug or "dataset"
    target = directory / f"{stem}{suffix}"
    source = _quote_path(str(dataset.storage_path))

    if fmt == "csv":
        # DuckDB writes it straight from the Parquet: no row of it is ever held
        # in this process, which is the difference between a 2 GB export
        # working and the API being killed for it.
        con = duckdb.connect(database=":memory:")
        try:
            con.execute("SET threads TO 4")
            con.execute("SET memory_limit = '2GB'")
            con.execute(
                f"COPY (SELECT * FROM read_parquet({source})) TO "
                f"{_quote_path(str(target))} (FORMAT CSV, HEADER)"
            )
        except duckdb.Error as exc:
            logger.warning("Dataset download failed: %s", exc)
            raise QueryError(f"The file could not be written: {exc}") from exc
        finally:
            con.close()
        return target

    frame = _frame(dataset, source)
    if fmt == "xlsx":
        if len(frame) > XLSX_ROW_LIMIT:
            raise QueryError(
                f"{len(frame):,} rows is more than a spreadsheet can hold. "
                "Download it as CSV or Stata instead."
            )
        frame.to_excel(target, index=False, sheet_name=(dataset.name or "Data")[:31])
        return target

    _write_stata(dataset, frame, target)
    return target


def _frame(dataset: Dataset, source: str) -> pd.DataFrame:
    con = duckdb.connect(database=":memory:")
    try:
        con.execute("SET threads TO 4")
        con.execute("SET memory_limit = '2GB'")
        return con.execute(f"SELECT * FROM read_parquet({source})").df()
    except duckdb.Error as exc:
        logger.warning("Dataset download failed: %s", exc)
        raise QueryError(f"The file could not be read: {exc}") from exc
    finally:
        con.close()


def _write_stata(dataset: Dataset, frame: pd.DataFrame, target: Path) -> None:
    """Write .dta, carrying the labels the platform holds for the variables.

    Labels are the reason to choose Stata over CSV, so they go with it: the
    variable's own label, and its value labels where the codes are integers -
    which is the only thing a .dta can attach them to.
    """
    labels: dict[str, str] = {}
    value_labels: dict[str, dict[Any, str]] = {}
    for variable in dataset.variables:
        if variable.label:
            labels[variable.name] = variable.label[:80]
        codes = variable.value_labels or {}
        if not codes:
            continue
        numbered: dict[Any, str] = {}
        for code, text in codes.items():
            try:
                numbered[int(float(code))] = str(text)
            except (TypeError, ValueError):
                numbered = {}
                break
        if numbered:
            value_labels[variable.name] = numbered

    # Stata cannot hold a column of mixed types, and pandas hands one back as
    # object; writing those as text is what every export tool does.
    for column in frame.columns:
        if frame[column].dtype == object:
            frame[column] = frame[column].astype("string")

    frame.to_stata(
        target,
        write_index=False,
        variable_labels={k: v for k, v in labels.items() if k in frame.columns},
        value_labels={k: v for k, v in value_labels.items() if k in frame.columns},
        version=118,
    )


def temp_directory() -> Path:
    """A directory the response can be built in and cleaned up afterwards."""
    return Path(tempfile.mkdtemp(prefix="surveyhq-download-"))
