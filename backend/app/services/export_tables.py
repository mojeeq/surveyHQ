"""A widget's numbers as a table, for the exports that write tables.

The exported web page carries each widget's numbers as a cube - the widget's
own groupings crossed with every filter variable on the page - because that
is what lets the page answer a filter with no database behind it. Anything
writing those numbers into a document has to add that extra grain back up
first, and has to do it the way the page does: a mean from its total and its
count rather than averaged twice, a share of the table it is on.

This was part of the workbook export until the workbook was taken out. The
arithmetic stayed, because the Word report is still built from it, and one
day a workbook may be again.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

#: Widgets whose numbers no table can hold. A map's answer is where things
#: are, a text box has no numbers in it at all; both are named in their place
#: rather than dropped silently, so a reader can see nothing went missing.
NO_NUMBERS = {
    "text": "a text box",
    "html": "an embedded page",
    "countdown": "a countdown",
    "map": "a map of locations",
    "freshness": "a freshness panel",
    "quality": "a data quality panel",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN is not a number here


#: What the exported page prints where a cell is withheld under disclosure
#: control, and where there is no number to print at all. The same two marks
#: here, because a reader holding both files should not have to learn a second
#: notation for the same two things.
WITHHELD = "*"
MISSING = "-"


def figure(value: Any) -> str:
    """A number as a report writes one.

    Thousands separated, and decimals only where there are any: a column of
    counts with ".0" after each one reads as a measurement rather than a
    count.
    """
    number = _number(value)
    if number is None:
        return ""
    if number == int(number) and abs(number) < 1e15:
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _text(value: Any) -> str:
    """A category label as the page writes one."""
    if value is None:
        return ""
    written = str(value)
    # A day is stored as a moment at midnight, and a row headed
    # "2026-07-19 00:00:00" is a machine talking to itself.
    if len(written) >= 19 and written[10] in " T" and written[11:19] == "00:00:00":
        return written[:10]
    return written


def combine(cube: dict[str, Any]) -> tuple[list[dict[str, str]], list[list[Any]]]:
    """A cube added back up to the widget's own grouping.

    The cube is held at a finer grain than the widget draws - the widget's
    groupings crossed with every filter variable on the page - because that is
    what lets the exported page answer a filter without going back to the
    database. A document answers no filters, so the extra grain is added up
    again here, the way the page adds it up: totals and minima and maxima
    combine as themselves, a mean comes back from its total and its count, and
    a share is worked out last, once there is a total to be a share of.
    """
    at = {column["name"]: index for index, column in enumerate(cube.get("columns") or [])}
    dimensions = [name for name in (cube.get("dimensions") or []) if name in at]
    measures = cube.get("measures") or []

    buckets: dict[tuple[Any, ...], dict[str, float]] = {}
    keys: list[tuple[Any, ...]] = []
    for row in cube.get("rows") or []:
        key = tuple(row[at[name]] for name in dimensions)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {}
            buckets[key] = bucket
            keys.append(key)
        for measure in measures:
            for part in measure.get("parts") or []:
                if part not in at:
                    continue
                value = _number(row[at[part]])
                if value is None:
                    continue
                held = bucket.get(part)
                if held is None:
                    bucket[part] = value
                elif measure.get("how") == "min":
                    bucket[part] = min(held, value)
                elif measure.get("how") == "max":
                    bucket[part] = max(held, value)
                else:
                    bucket[part] = held + value

    rows: list[list[Any]] = []
    for key in keys:
        bucket = buckets[key]
        out: list[Any] = list(key)
        for measure in measures:
            parts = measure.get("parts") or []
            if measure.get("how") == "mean" and len(parts) == 2:
                count = bucket.get(parts[1])
                total = bucket.get(parts[0])
                out.append(total / count if count and total is not None else None)
            else:
                out.append(bucket.get(parts[0]) if parts else None)
        rows.append(out)

    # A share is a share of what is in the table, which cannot be known until
    # the table is whole.
    for index, measure in enumerate(measures):
        if measure.get("how") != "share":
            continue
        column = len(dimensions) + index
        total = sum(_number(row[column]) or 0 for row in rows)
        for row in rows:
            row[column] = ((_number(row[column]) or 0) / total) * 100 if total else 0

    labels = {column["name"]: column.get("label") or column["name"] for column in cube["columns"]}
    columns = [{"name": name, "label": labels.get(name, name)} for name in dimensions]
    for measure in measures:
        name = measure.get("name") or ""
        columns.append({"name": name, "label": measure.get("label") or name})
    return columns, rows


def _sorted(columns: list[dict[str, str]], rows: list[list[Any]], cube: dict[str, Any]):
    """The widget's own order, so a table reads like the chart it came from."""
    index = {column["name"]: position for position, column in enumerate(columns)}
    for instruction in reversed(cube.get("sort") or []):
        position = index.get(str(instruction.get("field") or ""))
        if position is None:
            continue
        rows.sort(
            key=lambda row, at=position: (row[at] is None, row[at]),
            reverse=str(instruction.get("direction") or "asc").lower() == "desc",
        )
    return rows


def indicator_value(widget: dict[str, Any]) -> tuple[float | None, list[tuple[Any, float]]]:
    """An indicator tile's headline and its breakdown, as the page works them out.

    A percentage is a rate rather than a share of the whole country: the count
    this indicator measures over the count it is a percentage of, both narrowed
    the same way.
    """
    spec = widget.get("indicator") or {}
    cube = widget.get("cube") or {}
    _, rows = combine(cube)
    # The measure sits after the groupings, which is one column when the tile
    # shows a breakdown and none when it shows a single figure.
    grouped = len([name for name in (cube.get("dimensions") or []) if name])
    total = 0.0
    breakdown: list[tuple[Any, float]] = []
    for row in rows:
        value = _number(row[grouped]) or 0.0
        total += value
        if grouped:
            breakdown.append((row[0], value))

    if not spec.get("percent_of") or not widget.get("denominator"):
        return (total if rows else None), breakdown

    _, denominator_rows = combine(widget["denominator"])
    below = len([name for name in (widget["denominator"].get("dimensions") or []) if name])
    whole = sum(_number(row[below]) or 0 for row in denominator_rows)
    per = (
        {row[0]: (_number(row[below]) or 0) for row in denominator_rows} if below else {}
    )
    share = (total / whole) * 100 if whole else None
    if breakdown and per:
        breakdown = [
            (name, (value / per[name]) * 100) for name, value in breakdown if per.get(name)
        ]
    return share, breakdown


def crosstab_table(widget: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    """A cross-tabulation as the grid the board shows, not as a list of cells.

    A crosstab's cube is one row per combination, which is how the page can
    re-add it under a filter but not how anybody reads a cross-tabulation: the
    row variable down the side, the column variable across the top, the cell
    where they meet. So the grid is laid out again here the way the exported
    page lays it out, including the percentages and the totals the widget was
    set to show, and a reader comparing the two files finds the same table in
    both.
    """
    spec = widget.get("crosstab") or {}
    if spec.get("fixed"):
        return _finished_crosstab(spec)

    columns, rows = combine(widget.get("cube") or {})
    # A table can be asked for with no cell values at all: the categories of
    # the one variable it has and nothing beside them. There is nothing to
    # total either, so the stand-in column and both total lines go.
    shows_values = spec.get("show_values") is not False
    with_totals = bool(spec.get("include_totals")) and shows_values
    crossed = len(columns) > 2

    down: list[str] = []
    across: list[str] = []
    cells: dict[tuple[str, str], float] = {}
    for row in rows:
        side = _text(row[0]) or "(missing)"
        top = (_text(row[1]) or "(missing)") if crossed else str(spec.get("measure_label") or "")
        if side not in down:
            down.append(side)
        if shows_values and top not in across:
            across.append(top)
        cells[(side, top)] = cells.get((side, top), 0.0) + (_number(row[-1]) or 0.0)
    down.sort()
    across.sort()

    along = {side: sum(cells.get((side, top), 0.0) for top in across) for side in down}
    downwards = {top: sum(cells.get((side, top), 0.0) for side in down) for top in across}
    whole = sum(along.values())

    def shown(value: float, side: str, top: str) -> Any:
        """A cell as the widget shows it: a count, or its share of a margin."""
        of = spec.get("percentages")
        base = along.get(side) if of == "row" else downwards.get(top) if of == "column" else whole
        if of in ("row", "column", "total"):
            return f"{(value / base) * 100:,.1f}%" if base else MISSING
        return value

    heading = [str(spec.get("row_variable") or spec.get("column_variable") or "")]
    heading.extend(across)
    if with_totals:
        heading.append("Total")

    out: list[list[Any]] = []
    for side in down:
        line: list[Any] = [side]
        line.extend(shown(cells.get((side, top), 0.0), side, top) for top in across)
        if with_totals:
            line.append(along[side])
        out.append(line)
    if with_totals:
        last: list[Any] = ["Total"]
        last.extend(downwards[top] for top in across)
        last.append(whole)
        out.append(last)
    return heading, out


def _finished_crosstab(spec: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    """A crosstab that arrived already computed, under disclosure control.

    Where a disclosure floor is set the table is worked out on the server and
    travels finished, because a cube is the cell values and the withheld ones
    are exactly what must not travel. Nothing is recomputed here either: the
    withheld cells stay withheld, marked as the page marks them.
    """
    fixed = spec.get("fixed") or {}
    across = [str(label) for label in fixed.get("column_labels") or []]
    down = fixed.get("row_labels") or []
    values = fixed.get("values") or []
    hidden = fixed.get("suppressed") or []
    with_totals = bool(spec.get("include_totals")) and bool(across)
    with_row_totals = len(across) > 1
    suffix = "" if spec.get("percentages") == "none" else "%"

    def margin(value: Any) -> Any:
        return WITHHELD if value is None else value

    heading = [str(spec.get("row_variable") or spec.get("column_variable") or "")]
    heading.extend(across)
    if with_row_totals:
        heading.append("Total")

    out: list[list[Any]] = []
    for index, label in enumerate(down):
        line: list[Any] = [str(label)]
        withheld = hidden[index] if index < len(hidden) else []
        for column, value in enumerate(values[index] if index < len(values) else []):
            if column < len(withheld) and withheld[column]:
                line.append(WITHHELD)
            elif value is None:
                line.append(MISSING)
            else:
                line.append(figure(value) + suffix if suffix else value)
        if with_row_totals:
            line.append(margin((fixed.get("row_totals") or [None] * len(down))[index]))
        out.append(line)
    if with_totals and len(down) > 1:
        last: list[Any] = ["Total"]
        last.extend(margin(value) for value in fixed.get("column_totals") or [])
        if with_row_totals:
            last.append(margin(fixed.get("grand_total")))
        out.append(last)
    return heading, out


def disclosure_note(widget: dict[str, Any]) -> str:
    """What a withheld cell means, for the foot of a table that has any.

    An asterisk nobody explains is worse than a gap: a reader takes it for a
    footnote that went missing. Said only where the table actually withheld
    something, or dropped a category for being below the floor.
    """
    fixed = (widget.get("crosstab") or {}).get("fixed") or {}
    if not fixed:
        return ""
    floor = fixed.get("threshold")
    withheld = any(any(row or []) for row in fixed.get("suppressed") or [])
    dropped = int(fixed.get("rows_withheld") or 0)
    said = []
    if withheld:
        said.append(f"{WITHHELD} withheld to protect fewer than {floor} records.")
    if dropped:
        said.append(
            f"{dropped} categor{'y' if dropped == 1 else 'ies'} below that floor "
            + ("is" if dropped == 1 else "are")
            + " not listed."
        )
    return " ".join(said)


def widget_table(widget: dict[str, Any]) -> tuple[list[str], list[list[Any]]] | None:
    """One widget as a heading row and its rows, or None if it has no numbers."""
    kind = str(widget.get("kind") or "")
    if kind == "chart":
        cube = widget.get("cube") or {}
        columns, rows = combine(cube)
        return [column["label"] for column in columns], _sorted(columns, rows, cube)

    if kind == "crosstab":
        return crosstab_table(widget)

    if kind == "indicator":
        spec = widget.get("indicator") or {}
        value, breakdown = indicator_value(widget)
        unit = "%" if spec.get("percent_of") else (spec.get("unit") or "")
        heading = [str(spec.get("breakdown_variable") or "Indicator"), spec.get("name") or "Value"]
        rows: list[list[Any]] = []
        if breakdown:
            rows.extend([name, number] for name, number in breakdown)
        rows.append(["Total" if breakdown else (spec.get("name") or "Value"), value])
        if spec.get("target_value") is not None:
            rows.append(["Target", spec.get("target_value")])
        if unit:
            heading[1] = f"{heading[1]} ({unit})"
        return heading, rows

    return None


def _said_plainly(stamp: str) -> str:
    """An ISO timestamp as a person writes one.

    The line at the top of a report is read by whoever it was sent to, and
    "2026-10-12T02:09:15.191504+00:00" is a machine talking to itself.
    """
    try:
        moment = dt.datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    return moment.strftime("%d %B %Y, %H:%M UTC")
