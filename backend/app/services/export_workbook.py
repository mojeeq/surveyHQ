"""A board's numbers as a workbook.

The HTML export is the board itself: its filters still work and its charts
redraw. A workbook is the other thing an export gets asked for - the figures,
in the tool people put their own arithmetic beside, to reconcile against
another system or to paste into an annex.

One sheet per widget, behind a cover saying which board this was, what it was
narrowed to, and when. The numbers are rebuilt here from the same cube and
the same recipes the exported page rebuilds them from, so a mean comes back
from its total and its count rather than being averaged twice, and a share is
a share of the sheet it is on. Two exports of one board that disagreed with
each other would be worse than having only one of them.

What a sheet carries is the widget's own grouping, as the board draws it, but
in full: a widget showing only its top few shows all of them here, because a
sheet is read by somebody who wants the rest.
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Any

#: Widgets whose numbers no workbook can hold. A map's answer is where things
#: are, a text box has no numbers in it at all; both are named on the cover
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
    database. A workbook answers no filters, so the extra grain is added up
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

    # A share is a share of what is on the sheet, which cannot be known until
    # the sheet is whole.
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
    """The widget's own order, so a sheet reads like the chart it came from."""
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


def _said_plainly(stamp: str) -> str:
    """An ISO timestamp as a person writes one.

    A cover sheet is read by whoever the file was sent to, and
    "2026-10-12T02:09:15.191504+00:00" is a machine talking to itself.
    """
    try:
        moment = dt.datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    return moment.strftime("%d %B %Y, %H:%M UTC")


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


def _cover(workbook: Any, payload: dict[str, Any], sheets: list[dict[str, Any]]) -> None:
    """What this workbook is of, and what is on each sheet.

    A folder of exports all called the same thing is the usual way one of
    these gets detached from what it says, so the board, the date and what it
    was narrowed to are written into the file rather than left to its name.
    """
    sheet = workbook.add_worksheet("About")
    title = workbook.add_format({"bold": True, "font_size": 15})
    label = workbook.add_format({"bold": True})
    muted = workbook.add_format({"font_color": "#6b7280"})
    header = workbook.add_format(
        {"bold": True, "bg_color": "#1e293b", "font_color": "#ffffff", "border": 1}
    )
    sheet.set_column(0, 0, 34)
    sheet.set_column(1, 3, 22)

    sheet.write(0, 0, payload.get("name") or "Dashboard", title)
    row = 1
    if payload.get("description"):
        sheet.write(row, 0, payload["description"], muted)
        row += 1
    sheet.write(row, 0, "Exported", label)
    sheet.write(row, 1, _said_plainly(str(payload.get("generated_at") or "")))
    row += 1
    for pin in payload.get("pinned") or []:
        sheet.write(row, 0, str(pin.get("label") or pin.get("variable") or ""), label)
        sheet.write(row, 1, str(pin.get("value") or ""))
        row += 1
    row += 1
    sheet.write(
        row,
        0,
        "Each sheet holds the numbers behind one widget, in full: a widget "
        "showing only its top few shows all of them here.",
        muted,
    )
    row += 2

    for index, name in enumerate(("Sheet", "Widget", "Page", "Rows")):
        sheet.write(row, index, name, header)
    row += 1
    for entry in sheets:
        sheet.write(row, 0, entry["sheet"])
        sheet.write(row, 1, entry["title"])
        sheet.write(row, 2, entry["page"])
        if entry.get("rows") is None:
            sheet.write(row, 3, entry["why"], muted)
        else:
            sheet.write_number(row, 3, entry["rows"])
        row += 1


def workbook(payload: dict[str, Any]) -> bytes:
    """The board's figures: a cover, then one sheet per widget that has any."""
    import xlsxwriter

    from app.services.exporters import _safe_sheet_name, _write_cell

    buffer = io.BytesIO()
    book = xlsxwriter.Workbook(buffer, {"in_memory": True, "default_date_format": "yyyy-mm-dd"})
    header = book.add_format(
        {"bold": True, "bg_color": "#1e293b", "font_color": "#ffffff", "border": 1}
    )
    number = book.add_format({"num_format": "#,##0.####"})

    pages = [str((page or {}).get("name") or "") for page in payload.get("pages") or []]
    used: set[str] = {"About"}
    listed: list[dict[str, Any]] = []
    tables: list[tuple[str, list[str], list[list[Any]]]] = []

    for widget in payload.get("widgets") or []:
        index = int(widget.get("page") or 0)
        where = pages[index] if index < len(pages) else f"Page {index + 1}"
        title = str(widget.get("title") or "").strip() or "Untitled widget"
        table = widget_table(widget)
        if table is None:
            listed.append({
                "sheet": "-",
                "title": title,
                "page": where,
                "rows": None,
                "why": "Not in the workbook: "
                + NO_NUMBERS.get(str(widget.get("type") or ""), "it carries no numbers"),
            })
            continue
        name = _safe_sheet_name(title, used)
        heading, rows = table
        tables.append((name, heading, rows))
        listed.append({"sheet": name, "title": title, "page": where, "rows": len(rows)})

    _cover(book, payload, listed)

    for name, heading, rows in tables:
        sheet = book.add_worksheet(name)
        for column, label in enumerate(heading):
            sheet.write(0, column, label, header)
            sheet.set_column(column, column, max(len(str(label)) + 4, 14))
        for position, row in enumerate(rows, start=1):
            for column, value in enumerate(row):
                _write_cell(sheet, position, column, value, number)
        sheet.freeze_panes(1, 0)
        if rows:
            sheet.autofilter(0, 0, len(rows), max(0, len(heading) - 1))

    book.close()
    return buffer.getvalue()
