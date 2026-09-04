"""How recent a dataset's data is.

Two different questions, and a monitoring tool needs both. When did the
platform last receive data - which says whether the import is running. And how
recent is the newest record in it - which says whether the field teams are
still sending anything. An import that runs faithfully every morning and
collects nothing new looks perfectly healthy by the first measure and is the
exact failure the second one catches.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.models import Dataset
from app.services.datasets import dataset_is_queryable
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    _quote_path,
    quote_ident,
    run_sql,
)

# Anything older than this is stale enough to say so, unless the widget was
# given its own thresholds.
DEFAULT_WARN_HOURS = 24
DEFAULT_CRITICAL_HOURS = 72


# What makes a date column the one that says when a record happened, and what
# makes it something else entirely.
WHEN_IT_HAPPENED = (
    "interview",
    "submit",
    "complete",
    "receiv",
    "sync",
    "upload",
    "collect",
    "visit",
    "starttime",
    "endtime",
    "timestamp",
)
NOT_A_RECORD_TIME = (
    # A person's birthday is an answer, not a moment the data arrived. Reading
    # one as the data's recency reports a survey taken this morning as thirty
    # years stale, which is worse than reporting nothing.
    "birth",
    "dob",
    "death",
    "died",
    "marri",
    # Questionnaire configuration: the reference period, the simulated dates a
    # template ships with. They date the form, not the fieldwork.
    "custom",
    "config",
    "simulat",
    "period",
    "reference",
    "activate",
)


def score_date_variable(name: str) -> int:
    lower = name.lower()
    if any(word in lower for word in NOT_A_RECORD_TIME):
        return -5
    return 3 if any(word in lower for word in WHEN_IT_HAPPENED) else 0


def date_variable(dataset: Dataset, ctx: DatasetContext, chosen: str = "") -> str:
    """The column that says when a record happened, if the dataset has one.

    A choice made by hand wins. Otherwise the date columns are scored: one that
    names the interview or a submission is what this wants, and one that names
    a birthday or the questionnaire's own configuration is not a date about
    this record at all. When nothing scores above zero the answer is "none",
    because saying so beats reporting the newest birthday in the file.
    """
    if chosen and chosen in ctx.variables:
        return chosen

    candidates = [
        name
        for name, info in ctx.variables.items()
        if getattr(info, "var_type", "") == "datetime"
    ]
    detected = (dataset.meta or {}).get("monitoring_fields", {}).get("date")
    if detected and detected in ctx.variables and detected not in candidates:
        candidates.append(str(detected))
    if not candidates:
        return ""

    best = max(candidates, key=score_date_variable)
    return best if score_date_variable(best) > 0 else ""


def latest_record(ctx: DatasetContext, variable: str) -> dt.datetime | None:
    """The newest value of that column, which is the newest record."""
    if not variable or variable not in ctx.variables:
        return None
    column = quote_ident(ctx.require(variable).name)
    sql = (
        f"SELECT MAX(try_cast({column} AS TIMESTAMP)) "
        f"FROM read_parquet({_quote_path(ctx.parquet_path)})"
    )
    try:
        _, rows = run_sql(sql)
    except QueryError:
        return None
    value = rows[0][0] if rows else None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    return None


def hours_since(moment: dt.datetime | None, now: dt.datetime) -> float | None:
    if moment is None:
        return None
    stamped = moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
    return max(0.0, (now - stamped).total_seconds() / 3600)


def status(hours: float | None, warn: float, critical: float) -> str:
    """Green, amber or red - the same three the indicators already use."""
    if hours is None:
        return "unknown"
    if hours >= critical:
        return "critical"
    if hours >= warn:
        return "warning"
    return "ok"


def report(
    dataset: Dataset,
    now: dt.datetime,
    warn_hours: float = DEFAULT_WARN_HOURS,
    critical_hours: float = DEFAULT_CRITICAL_HOURS,
    date_column: str = "",
) -> dict[str, Any]:
    """One dataset's line in the freshness widget."""
    line: dict[str, Any] = {
        "dataset_id": dataset.id,
        "name": dataset.name,
        "rows": dataset.row_count,
        "imported_at": dataset.refreshed_at.isoformat() if dataset.refreshed_at else None,
        "latest_record_at": None,
        "date_variable": "",
        "status": "unknown",
        "hours_since_import": None,
        "hours_since_record": None,
    }
    if not dataset_is_queryable(dataset):
        line["error"] = "This dataset has no data"
        return line

    ctx = DatasetContext.from_model(dataset)
    variable = date_variable(dataset, ctx, date_column)
    newest = latest_record(ctx, variable)

    line["date_variable"] = variable
    line["latest_record_at"] = newest.isoformat() if newest else None
    line["hours_since_import"] = hours_since(dataset.refreshed_at, now)
    line["hours_since_record"] = hours_since(newest, now)
    # Judged on whichever is older: the data is only as fresh as the staler of
    # "when we last received anything" and "how new the newest record is".
    ages = [age for age in (line["hours_since_import"], line["hours_since_record"]) if age]
    line["status"] = status(max(ages) if ages else None, warn_hours, critical_hours)
    return line
