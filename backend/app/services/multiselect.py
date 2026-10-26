"""Tabulating a multiple-select question from the columns it was exported as.

A "tick all that apply" question does not come back as one column. Survey
Solutions writes one column per option - toilet__1, toilet__2, toilet__3 -
each holding 1 where the option was chosen and 0 where it was not. Every tool
in this platform tabulates one variable at a time, so the question that was
actually asked could not be charted at all: you could count how many households
ticked option 2, one option at a time, and never see the question.

This reads the set as what it is. One row per option, counted across the whole
column, which is the shape a bar chart of a multiple-select wants.

That is one way to read the question, and not the only one. The same columns
also say how the answers differ between groups, which options go together,
and how many each respondent ticked - see VIEWS. Each comes back as an
ordinary result, so the charts, the table and a dashboard draw it without
knowing the question was spread over a dozen columns.
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
    MISSING_LABEL,
    DatasetContext,
    QueryError,
    SQLBuilder,
    _is_missing,
    _label_value,
    _quote_path,
    quote_ident,
    run_sql,
    ticked_sql,
)

# The suffix Survey Solutions puts on each option of a multiple-select. Two
# underscores and a number, which is specific enough not to catch a variable
# that merely ends in a digit.
OPTION = re.compile(r"^(?P<stem>.+?)__(?P<option>\d+)$")

MAX_OPTIONS = 60

#: The ways one question can be read.
#:
#: options       how many chose each option - the bar chart it always was
#: by_group      each option's share within each group of another variable
#: combinations  the sets of options chosen together, most common first
#: how_many      how many options each respondent chose
#: together      of those who chose one option, the share who chose another
VIEWS = ("options", "by_group", "combinations", "how_many", "together")

#: Past this many groups a breakdown is a wall of cells nobody reads.
MAX_GROUPS = 40
#: Every pair of options is a cell, so this grows with the square.
MAX_TOGETHER = 30


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
            {"column": name, "label": shown}
            for name, shown in labelled_options(ctx, columns)
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


def labelled_options(ctx: DatasetContext, columns: list[str]) -> list[tuple[str, str]]:
    """Each option column paired with the name its bar carries, no two alike.

    One function because three things have to agree about these names: the
    tick-list offered when building the chart, the labels drawn on the bars,
    and the map that turns a clicked bar back into the column to filter on.
    That last one is why they are made unique here. Two options can easily
    carry the same words - two "Other" boxes in one question - and a reader
    looking at two identical bars cannot tell them apart either, so the option
    number is added to both rather than to neither.
    """
    stem = OPTION.match(columns[0]) if columns else None
    stem_label = _stem_label(ctx, stem.group("stem"), columns) if stem else ""
    plain = [(name, option_label(ctx, name, stem_label)) for name in columns]
    seen: dict[str, int] = {}
    for _, label in plain:
        seen[label] = seen.get(label, 0) + 1
    out = []
    for name, label in plain:
        if seen[label] > 1:
            match = OPTION.match(name)
            label = f"{label} (option {match.group('option')})" if match else f"{label} ({name})"
        out.append((name, label))
    return out


def _chosen(column: str) -> str:
    """The SQL for "this option was ticked".

    Shared with the `selected` filter operator, so that filtering by an option
    keeps exactly the rows its own bar counted. Clicking a bar is how that
    filter gets made, and the two drifting apart is not something a reader
    could see.
    """
    return ticked_sql(quote_ident(column))


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
    view: str = "options",
    by: str = "",
    top: int = 10,
) -> QueryResult:
    """The question read one of the VIEWS ways; by default, one row per option."""
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
    asked = Asked(ctx=ctx, chosen=chosen, where=where, params=params, percent_of=percent_of)

    if view == "by_group":
        return _by_group(asked, by, sort, show)
    if view == "combinations":
        return _combinations(asked, sort, show, top)
    if view == "how_many":
        return _how_many(asked, show)
    if view == "together":
        return _together(asked, sort, show)

    counts = ", ".join(
        f"SUM(CASE WHEN {_chosen(name)} THEN 1 ELSE 0 END) AS c{index}"
        for index, name in enumerate(chosen)
    )
    names, rows = run_sql(
        f"SELECT {counts}, COUNT(*) AS total_rows, "
        f"SUM(CASE WHEN {_answered(chosen)} THEN 1 ELSE 0 END) AS answered "
        f"FROM {asked.source()}",
        params,
    )
    if not rows:
        return _empty()
    row = dict(zip(names, rows[0], strict=False))

    base = asked.base(row)
    out: list[list[Any]] = []
    for index, (_, label) in enumerate(labelled_options(ctx, chosen)):
        count = int(row.get(f"c{index}") or 0)
        out.append([label, count, _share(count, base) if base else 0.0])
    _ordered(out, sort, count_at=1)

    return _result(
        [QueryColumn(name="option", label="Option", type="dimension", data_type="string")],
        out,
        show,
        asked.share_label(),
        base,
    )


class Asked:
    """What every view starts from: the options, the rows, and the base."""

    def __init__(
        self,
        ctx: DatasetContext,
        chosen: list[str],
        where: str,
        params: list[Any],
        percent_of: str,
    ):
        self.ctx = ctx
        self.chosen = chosen
        self.where = where
        self.params = params
        self.percent_of = percent_of

    def source(self, answered_only: bool = False) -> str:
        """FROM ... WHERE ..., narrowed to the respondents where asked."""
        conditions = [f"({self.where})"] if self.where else []
        if answered_only:
            conditions.append(_answered(self.chosen))
        sql = f"read_parquet({_quote_path(self.ctx.parquet_path)})"
        return sql + (f" WHERE {' AND '.join(conditions)}" if conditions else "")

    def base(self, row: dict[str, Any]) -> int:
        """What a share is of: the respondents, or every row."""
        key = "answered" if self.percent_of == "respondents" else "total_rows"
        return int(row.get(key) or 0)

    def totals(self) -> dict[str, Any]:
        names, rows = run_sql(
            f"SELECT COUNT(*) AS total_rows, SUM(CASE WHEN {_answered(self.chosen)} "
            f"THEN 1 ELSE 0 END) AS answered FROM {self.source()}",
            self.params,
        )
        return dict(zip(names, rows[0], strict=False)) if rows else {}

    def share_label(self) -> str:
        return "% of respondents" if self.percent_of == "respondents" else "% of all rows"

    def labels(self) -> list[str]:
        return [label for _, label in labelled_options(self.ctx, self.chosen)]


def _share(count: int, base: int) -> float | None:
    return round(100 * count / base, 1) if base else None


def _ordered(rows: list[list[Any]], sort: str, count_at: int) -> None:
    if sort == "value_desc":
        rows.sort(key=lambda entry: entry[count_at], reverse=True)
    elif sort == "value_asc":
        rows.sort(key=lambda entry: entry[count_at])
    elif sort == "label_asc":
        rows.sort(key=lambda entry: str(entry[0]))


def _result(
    dimensions: list[QueryColumn],
    rows: list[list[Any]],
    show: str,
    share_label: str,
    base: int,
    count_label: str = "Chose it",
) -> QueryResult:
    """The rows, with the one number a chart draws or both for a table.

    Each row is the dimensions followed by a count and a share. A bar chart
    wants one number per bar: drawn together, a count in the hundreds and a
    percentage under a hundred put the second series flat against the axis.

    The share column says it is a percentage, so a chart does not fold the
    ninth group into an "Other" by adding percentages of different groups
    together - a sum that means nothing.
    """
    width = len(dimensions)
    keep = list(range(width))
    if show in ("count", "both"):
        keep.append(width)
    if show in ("percent", "both"):
        keep.append(width + 1)
    columns = [
        *dimensions,
        QueryColumn(name="chose", label=count_label, type="measure"),
        QueryColumn(name="percent", label=share_label, type="measure", data_type="percent"),
    ]
    return QueryResult(
        columns=[columns[index] for index in keep],
        rows=[[entry[index] for index in keep] for entry in rows],
        row_count=len(rows),
        truncated=False,
        # The base the percentages are of. It is the whole point of them, and
        # belongs with the numbers rather than in the head of whoever built
        # the chart.
        total_rows_scanned=base,
    )


def _by_group(asked: Asked, by: str, sort: str, show: str) -> QueryResult:
    """Each option's share within each group: which provinces use what.

    A share of the group's own respondents, not of everyone, because the
    groups are different sizes: a province with a tenth of the households
    would otherwise read as using everything a tenth as much. A group nobody
    in was asked has no share at all rather than a nought.
    """
    if not by:
        raise QueryError("Choose the variable to break the answers down by")
    info = asked.ctx.require(by)
    if info.name in asked.chosen:
        raise QueryError(f"{by} is one of the options; break down by another variable")
    group = quote_ident(info.name)
    counts = ", ".join(
        f"SUM(CASE WHEN {_chosen(name)} THEN 1 ELSE 0 END) AS c{index}"
        for index, name in enumerate(asked.chosen)
    )
    names, rows = run_sql(
        f"SELECT {group} AS g, {counts}, COUNT(*) AS total_rows, "
        f"SUM(CASE WHEN {_answered(asked.chosen)} THEN 1 ELSE 0 END) AS answered "
        f"FROM {asked.source()} GROUP BY 1",
        asked.params,
    )
    if len(rows) > MAX_GROUPS:
        raise QueryError(
            f"{by} has {len(rows):,} groups, more than the {MAX_GROUPS} a breakdown "
            f"can show and be read. Choose a variable with fewer, or filter to some."
        )

    # In the variable's own order - codes as numbered, names as written - with
    # the blank group last. Two codes under one label are one group.
    records = [dict(zip(names, raw, strict=False)) for raw in rows]
    records.sort(key=lambda r: (r["g"] is None, r["g"] if r["g"] is not None else 0))
    groups: dict[str, dict[str, int]] = {}
    for record in records:
        value = record["g"]
        blank = value is None or value == "" or _is_missing(info, value)
        label = MISSING_LABEL if blank else str(_label_value(info, value))
        into = groups.setdefault(label, {})
        for key, number in record.items():
            if key != "g":
                into[key] = into.get(key, 0) + int(number or 0)

    labels = asked.labels()
    overall = [
        [label, sum(found.get(f"c{index}", 0) for found in groups.values())]
        for index, label in enumerate(labels)
    ]
    _ordered(overall, sort, count_at=1)
    out: list[list[Any]] = []
    for label, _ in overall:
        index = labels.index(label)
        for name, found in groups.items():
            count = found.get(f"c{index}", 0)
            out.append([label, name, count, _share(count, asked.base(found))])

    totals = asked.totals()
    return _result(
        [
            QueryColumn(name="option", label="Option", type="dimension", data_type="string"),
            QueryColumn(
                name="group", label=info.label or info.name, type="dimension", data_type="string"
            ),
        ],
        out,
        show,
        asked.share_label() + " in the group",
        asked.base(totals),
    )


def _combinations(asked: Asked, sort: str, show: str, top: int) -> QueryResult:
    """The sets of options chosen together, most common first.

    Every respondent has exactly one combination - "Piped + Rain", "Well
    only", or none of them - so unlike the options themselves these do add
    to a hundred per cent of respondents, and the tail beyond the top few is
    kept as one bar so that they still do.
    """
    key = ", ".join(
        f"CASE WHEN {_chosen(name)} THEN '{index}' END" for index, name in enumerate(asked.chosen)
    )
    _, rows = run_sql(
        f"SELECT concat_ws('|', {key}) AS combination, COUNT(*) AS n "
        f"FROM {asked.source(answered_only=True)} GROUP BY 1",
        asked.params,
    )
    labels = asked.labels()

    def named(combination: str) -> str:
        picked = [labels[int(index)] for index in combination.split("|") if index != ""]
        if not picked:
            return "None of these"
        return f"{picked[0]} only" if len(picked) == 1 else " + ".join(picked)

    totals = asked.totals()
    base = asked.base(totals)
    found = sorted(
        ((str(combination or ""), int(n or 0)) for combination, n in rows),
        key=lambda one: (-one[1], one[0]),
    )
    kept = found[: max(1, top)]
    rest = found[len(kept) :]
    out = [[named(combination), n, _share(n, base)] for combination, n in kept]
    if sort == "none":
        # In the order of the options: each combination by the options it
        # holds, as a questionnaire would list them.
        position = {named(combination): combination for combination, _ in kept}
        out.sort(
            key=lambda entry: [int(i) for i in position[entry[0]].split("|") if i != ""] or [-1]
        )
    else:
        _ordered(out, sort, count_at=1)
    if rest:
        left = sum(n for _, n in rest)
        out.append([f"Other combinations ({len(rest):,})", left, _share(left, base)])
    return _result(
        [QueryColumn(name="combination", label="Combination", type="dimension",
                     data_type="string")],
        out,
        show,
        asked.share_label(),
        base,
        count_label="Respondents",
    )


def _how_many(asked: Asked, show: str) -> QueryResult:
    """How many options each respondent chose: none, one, two...

    Read in order, whatever the sort says - it is a count, and three options
    drawn before one is not a different view, it is an unreadable one.
    """
    ticked = " + ".join(
        f"CASE WHEN {_chosen(name)} THEN 1 ELSE 0 END" for name in asked.chosen
    )
    _, rows = run_sql(
        f"SELECT ({ticked}) AS k, COUNT(*) AS n FROM {asked.source(answered_only=True)} "
        f"GROUP BY 1",
        asked.params,
    )
    totals = asked.totals()
    base = asked.base(totals)
    found = {int(k): int(n or 0) for k, n in rows}
    most = max(found, default=0)
    out = [[k, found.get(k, 0), _share(found.get(k, 0), base)] for k in range(0, most + 1)]
    return _result(
        [QueryColumn(name="chosen", label="Options chosen", type="dimension",
                     data_type="numeric")],
        out,
        show,
        asked.share_label(),
        base,
        count_label="Respondents",
    )


def _together(asked: Asked, sort: str, show: str) -> QueryResult:
    """Of those who chose one option, the share who also chose each other.

    Read across a row: of the households with piped water, how many also
    collect rain. Not the same the other way round - a common option is
    chosen by most of those who chose a rare one, and not the reverse - which
    is why this is not the share of everyone who chose both.

    A row's own option is left empty when shares are shown: "of those who
    chose it, all of them chose it" is true and says nothing, and drawn as
    the darkest cell on the map it would draw the eye away from what does.
    """
    chosen = asked.chosen
    if len(chosen) > MAX_TOGETHER:
        raise QueryError(
            f"Chosen together compares every pair of options; pick {MAX_TOGETHER} "
            f"or fewer, not {len(chosen)}"
        )
    singles = [
        f"SUM(CASE WHEN {_chosen(name)} THEN 1 ELSE 0 END) AS c{index}"
        for index, name in enumerate(chosen)
    ]
    pairs = [
        f"SUM(CASE WHEN {_chosen(chosen[i])} AND {_chosen(chosen[j])} THEN 1 ELSE 0 END) "
        f"AS p{i}_{j}"
        for i in range(len(chosen))
        for j in range(i + 1, len(chosen))
    ]
    names, rows = run_sql(
        f"SELECT {', '.join(singles + pairs)} FROM {asked.source()}", asked.params
    )
    found = dict(zip(names, rows[0], strict=False)) if rows else {}
    labels = asked.labels()
    single = [int(found.get(f"c{index}") or 0) for index in range(len(chosen))]

    order = [[label, single[index], index] for index, label in enumerate(labels)]
    _ordered(order, sort, count_at=1)
    out: list[list[Any]] = []
    for row_label, row_count, i in order:
        for column_label, _, j in order:
            if i == j:
                out.append([row_label, column_label, row_count, None])
                continue
            both = int(found.get(f"p{min(i, j)}_{max(i, j)}") or 0)
            out.append([row_label, column_label, both, _share(both, row_count)])

    totals = asked.totals()
    return _result(
        [
            QueryColumn(name="option", label="Of those who chose", type="dimension",
                        data_type="string"),
            QueryColumn(name="also", label="Also chose", type="dimension", data_type="string"),
        ],
        out,
        show,
        "% who also chose it",
        asked.base(totals),
        count_label="Chose both",
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
