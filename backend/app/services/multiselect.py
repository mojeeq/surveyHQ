"""Tabulating a multiple-select question from the columns it was exported as.

A "tick all that apply" question does not come back as one column. Survey
Solutions writes one column per option - toilet__1, toilet__2, toilet__3 -
each holding 1 where the option was chosen and 0 where it was not. Every tool
in this platform tabulates one variable at a time, so the question that was
actually asked could not be charted at all: you could count how many households
ticked option 2, one option at a time, and never see the question.

This reads the set as what it is. One row per option, counted across the whole
column, which is the shape a bar chart of a multiple-select wants.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.query import (
    FilterGroup,
    QueryColumn,
    QueryResult,
)
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    SQLBuilder,
    _quote_path,
    quote_ident,
    run_sql,
)

# The suffix Survey Solutions puts on each option of a multiple-select. Two
# underscores and a number, which is specific enough not to catch a variable
# that merely ends in a digit.
OPTION = re.compile(r"^(?P<stem>.+?)__(?P<option>\d+)$")

MAX_OPTIONS = 60


def groups(ctx: DatasetContext) -> list[dict[str, Any]]:
    """Every set of columns in this dataset that looks like one question.

    Offered to the person building the chart rather than guessed at: a stem
    with one option under it is far more likely to be a coincidence than a
    question, so only sets of two or more are reported.
    """
    found: dict[str, list[str]] = {}
    for name in ctx.variables:
        match = OPTION.match(name)
        if match:
            found.setdefault(match.group("stem"), []).append(name)

    listed = []
    for stem, names in sorted(found.items()):
        if len(names) < 2:
            continue
        columns = sorted(names, key=_option_number)
        label = _stem_label(ctx, stem, names)
        # The name each option will be drawn under, worked out here rather than
        # left to the chart: the person ticking hhld_goods__8 out of nineteen
        # boxes is choosing an option, and needs to see which one.
        options = [
            {"column": name, "label": option_label(ctx, name, label)} for name in columns
        ]
        listed.append(
            {
                "stem": stem,
                "columns": columns,
                "label": label,
                "options": options,
                # Set when the file gave no words for any of them, so the page
                # can say why they are numbered and offer to fix it.
                "unnamed": all(
                    option["label"].startswith("Option ") for option in options
                ),
            }
        )
    return listed


def _option_number(name: str) -> int:
    match = OPTION.match(name)
    return int(match.group("option")) if match else 0


def _stem_label(ctx: DatasetContext, stem: str, names: list[str]) -> str:
    """A name for the question, taken from what its options were labelled.

    An exported option is usually labelled "Type of toilet: Flush" or similar,
    so the part the options agree on is the question and the part they differ
    on is the answer. Where they share nothing, the stem itself has to do.
    """
    labels = [(ctx.variables[name].label or "") for name in names if name in ctx.variables]
    labels = [label for label in labels if label]
    if len(labels) < 2:
        return stem
    shared = labels[0]
    for label in labels[1:]:
        limit = min(len(shared), len(label))
        cut = 0
        while cut < limit and shared[cut] == label[cut]:
            cut += 1
        shared = shared[:cut]
    shared = shared.strip(" :-/,")
    return shared or stem


# What a 0/1 column's codes are called when they say nothing about the option:
# "1 = Yes" names the tick, not the thing ticked.
TICK_WORDS = {
    "0", "1", "y", "n", "yes", "no", "true", "false",
    "selected", "not selected", "unselected", "chosen", "not chosen",
    "ticked", "not ticked", "checked", "not checked", "marked", "not marked",
}


def option_label(ctx: DatasetContext, column: str, stem_label: str) -> str:
    """What to write against one option's bar.

    Three places the option's own words can be, in the order they are worth
    trusting: the column's label, then the name its "chosen" code carries, then
    nothing - and a numbered bar, which sends the reader to the questionnaire
    to find out what option 8 was.
    """
    info = ctx.variables.get(column)
    label = (info.label or "").strip() if info else ""
    if label:
        # The question's own words are already the chart's title; repeating
        # them on every bar makes the axis unreadable.
        if stem_label and label.startswith(stem_label):
            trimmed = label[len(stem_label) :].strip(" :-/,")
            if trimmed:
                return trimmed
            # Nothing left once the question is taken off, which means every
            # option carries the question and none of them carries an answer.
            # Printing it would draw nineteen bars with the same words on them,
            # so this goes looking for the option's own name instead.
        else:
            return label

    # Some exports label the codes rather than the column: 0 is "Not selected"
    # and 1 is the option itself. A yes-or-no pair says nothing about which
    # option this is, so those words are passed over rather than printed on
    # nineteen bars that would then all read "Yes".
    for code in ("1", "1.0"):
        chosen = str(((info.value_labels if info else None) or {}).get(code) or "").strip()
        if chosen and chosen.lower() not in TICK_WORDS:
            return chosen

    match = OPTION.match(column)
    return f"Option {match.group('option')}" if match else column


def _chosen(column: str) -> str:
    """The SQL for "this option was ticked".

    An export writes 1 and 0; a CSV round trip can turn those into "1" and "0",
    and some tools write Yes and No. All three mean the same thing and a chart
    that silently counted none of them would be worse than an error.
    """
    quoted = quote_ident(column)
    return (
        f"(try_cast({quoted} AS DOUBLE) = 1 OR "
        f"lower(trim(cast({quoted} AS VARCHAR))) IN ('yes', 'true'))"
    )


def _answered(columns: list[str]) -> str:
    """The SQL for "this respondent was asked the question at all"."""
    parts = " OR ".join(f"{quote_ident(name)} IS NOT NULL" for name in columns)
    return f"({parts})"


def tabulate(
    ctx: DatasetContext,
    columns: list[str],
    filters: FilterGroup | None = None,
    percent_of: str = "respondents",
    sort: str = "value_desc",
    show: str = "both",
) -> QueryResult:
    """One row per option: how many chose it, and what share that is."""
    chosen = [name for name in columns if name in ctx.variables]
    missing = [name for name in columns if name not in ctx.variables]
    if missing:
        raise QueryError(f"'{missing[0]}' is not a variable in this dataset")
    if not chosen:
        raise QueryError("Choose at least one option column")
    if len(chosen) > MAX_OPTIONS:
        raise QueryError(
            f"That is {len(chosen)} options; a chart of more than {MAX_OPTIONS} is "
            "unreadable. Pick the ones you want to show."
        )

    builder = SQLBuilder(ctx)
    where = builder.filter_sql(filters) if filters else ""
    params = list(builder.params)

    counts = ", ".join(
        f"SUM(CASE WHEN {_chosen(name)} THEN 1 ELSE 0 END) AS c{index}"
        for index, name in enumerate(chosen)
    )
    sql = (
        f"SELECT {counts}, COUNT(*) AS total_rows, "
        f"SUM(CASE WHEN {_answered(chosen)} THEN 1 ELSE 0 END) AS answered "
        f"FROM read_parquet({_quote_path(ctx.parquet_path)})"
    )
    if where:
        sql += f" WHERE {where}"

    names, rows = run_sql(sql, params)
    if not rows:
        return _empty()
    row = dict(zip(names, rows[0], strict=False))

    total = int(row.get("total_rows") or 0)
    answered = int(row.get("answered") or 0)
    base = answered if percent_of == "respondents" else total
    stem_label = _stem_label(ctx, OPTION.match(chosen[0]).group("stem"), chosen) if OPTION.match(
        chosen[0]
    ) else ""

    out: list[list[Any]] = []
    for index, name in enumerate(chosen):
        count = int(row.get(f"c{index}") or 0)
        share = round(100 * count / base, 1) if base else 0.0
        out.append([option_label(ctx, name, stem_label), count, share])

    if sort == "value_desc":
        out.sort(key=lambda entry: entry[1], reverse=True)
    elif sort == "value_asc":
        out.sort(key=lambda entry: entry[1])
    elif sort == "label_asc":
        out.sort(key=lambda entry: str(entry[0]))

    # A bar chart wants one number per bar: drawn together, a count in the
    # hundreds and a percentage under a hundred put the second series flat
    # against the axis. A table is the case that wants both.
    keep = [0] + ([1] if show in ("count", "both") else []) + (
        [2] if show in ("percent", "both") else []
    )
    columns_out = [
        QueryColumn(name="option", label="Option", type="dimension", data_type="string"),
        QueryColumn(name="chose", label="Chose it", type="measure"),
        QueryColumn(
            name="percent",
            label="% of respondents" if percent_of == "respondents" else "% of all rows",
            type="measure",
        ),
    ]

    return QueryResult(
        columns=[columns_out[index] for index in keep],
        rows=[[entry[index] for index in keep] for entry in out],
        row_count=len(out),
        truncated=False,
        # The base the percentages are of. It is the whole point of them, and
        # belongs with the numbers rather than in the head of whoever built
        # the chart.
        total_rows_scanned=base,
    )


def _empty() -> QueryResult:
    return QueryResult(
        columns=[
            QueryColumn(name="option", label="Option", type="dimension", data_type="string"),
            QueryColumn(name="chose", label="Chose it", type="measure"),
            QueryColumn(name="percent", label="% of respondents", type="measure"),
        ],
        rows=[],
        row_count=0,
        truncated=False,
        total_rows_scanned=0,
    )
