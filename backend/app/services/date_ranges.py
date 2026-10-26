"""A date-range filter's choice, as conditions on a date variable.

A dashboard's filters were dropdowns, and dates were left out of them on
purpose - two hundred dates make a list nobody can use, and a date wants a
range. So a date variable gets a control of its own: Today, Yesterday, the last
seven or thirty days, this week, this month, last month, or two days of your
choosing.

A choice is stored as text, like any other filter's value, so a saved view
keeps it: ``dates:last_7`` or ``dates:2026-11-01..2026-11-15`` (either side of
the two dots may be empty). A named range stays relative - a view saved as
"Last 7 days" is the last seven days whenever it is opened.

The live page works its ranges out in the reader's browser, where "today" is
the reader's today (frontend/src/lib/date-range.ts). This is the same rule for
the server's own use: an exported file or report made from a saved view, where
the range is fixed on the day the file is made. Both are tested against the
same cases.
"""

from __future__ import annotations

import datetime as dt

from app.schemas.query import Condition

PREFIX = "dates:"

PRESETS: dict[str, str] = {
    "today": "Today",
    "yesterday": "Yesterday",
    "last_7": "Last 7 days",
    "last_30": "Last 30 days",
    "this_week": "This week",
    "this_month": "This month",
    "last_month": "Last month",
}


def is_selection(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def _day(text: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(text.strip()) if text.strip() else None
    except ValueError:
        return None


def bounds(value: str, today: dt.date) -> tuple[dt.date | None, dt.date | None]:
    """The first day in the range, and the first day after it.

    The end is the day after rather than the last day, so a record at five in
    the afternoon on the last day is inside the range: "up to the 15th" means
    the whole of the 15th.
    """
    choice = value[len(PREFIX):] if is_selection(value) else value
    if choice == "today":
        return today, today + dt.timedelta(days=1)
    if choice == "yesterday":
        return today - dt.timedelta(days=1), today
    if choice == "last_7":
        return today - dt.timedelta(days=6), today + dt.timedelta(days=1)
    if choice == "last_30":
        return today - dt.timedelta(days=29), today + dt.timedelta(days=1)
    if choice == "this_week":
        # From Monday, as an ISO week runs.
        return today - dt.timedelta(days=today.weekday()), today + dt.timedelta(days=1)
    if choice == "this_month":
        return today.replace(day=1), today + dt.timedelta(days=1)
    if choice == "last_month":
        first_this = today.replace(day=1)
        first_last = (first_this - dt.timedelta(days=1)).replace(day=1)
        return first_last, first_this
    start, _, end = choice.partition("..")
    first = _day(start)
    last = _day(end)
    return first, (last + dt.timedelta(days=1)) if last else None


def conditions(variable: str, value: str, today: dt.date) -> list[Condition]:
    """The range as conditions the query engine understands."""
    first, after = bounds(value, today)
    found: list[Condition] = []
    if first is not None:
        found.append(Condition(variable=variable, operator="on_or_after", value=first.isoformat()))
    if after is not None:
        found.append(Condition(variable=variable, operator="before", value=after.isoformat()))
    return found


def describe(value: str, today: dt.date) -> str:
    """The choice in words, with the days it stood for when it is a named one."""
    choice = value[len(PREFIX):] if is_selection(value) else value
    first, after = bounds(value, today)
    last = after - dt.timedelta(days=1) if after else None

    def written(day: dt.date) -> str:
        return f"{day.day} {day.strftime('%b')} {day.year}"

    span = (
        written(first) if first and last and first == last
        else f"{written(first)} to {written(last)}" if first and last
        else f"from {written(first)}" if first
        else f"up to {written(last)}" if last
        else "all dates"
    )
    name = PRESETS.get(choice)
    return f"{name} ({span})" if name else span
