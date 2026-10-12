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


def widget_table(widget: dict[str, Any]) -> tuple[list[str], list[list[Any]]] | None:
    """One widget as a heading row and its rows, or None if it has no numbers."""
    kind = str(widget.get("kind") or "")
    if kind == "chart":
        cube = widget.get("cube") or {}
        columns, rows = combine(cube)
        return [column["label"] for column in columns], _sorted(columns, rows, cube)

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
