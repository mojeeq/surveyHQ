"""When a connection's next automatic import is due.

Two shapes, because they answer different questions. An interval - "every six
hours" - keeps data no older than a known age. A clock time - "06:00 and 18:00"
- puts the import where the day has room for it: before the office opens, after
the field teams sync their tablets. A monitoring dashboard is usually read at a
particular hour, and the useful guarantee is that it was refreshed just before.

The times are read in the connection's own zone. Fieldwork happens somewhere,
and 06:00 means six in the morning there, not six in UTC - which in Vanuatu is
five in the afternoon the day before.
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def valid_time(text: str) -> bool:
    return bool(TIME_PATTERN.match(text.strip()))


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        # A zone the database no longer knows is not worth failing an import
        # over; UTC is wrong by hours, never wrong by a day.
        return ZoneInfo("UTC")


def last_occurrence(times: list[str], now: dt.datetime, timezone: str) -> dt.datetime | None:
    """The most recent scheduled moment at or before `now`, as an instant.

    None when nothing is scheduled. Yesterday's last time counts: a check at
    00:30 is looking back at an 18:00 slot, not forward at tomorrow's.
    """
    valid = sorted(t.strip() for t in times if valid_time(t))
    if not valid:
        return None

    tz = zone(timezone)
    local = now.astimezone(tz)
    candidates: list[dt.datetime] = []
    for day in (local.date(), local.date() - dt.timedelta(days=1)):
        for text in valid:
            hour, minute = (int(part) for part in text.split(":"))
            # Built in the zone rather than converted into it, so the moment
            # follows the clock across a daylight-saving change instead of
            # drifting an hour.
            candidates.append(
                dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz)
            )
    passed = [moment for moment in candidates if moment <= local]
    return max(passed) if passed else None


def is_due(
    *,
    mode: str,
    times: list[str],
    timezone: str,
    interval_minutes: int,
    last_sync_at: dt.datetime | None,
    now: dt.datetime,
) -> bool:
    """Whether an automatic import should be started now."""
    if mode == "daily":
        occurrence = last_occurrence(times, now, timezone)
        if occurrence is None:
            return False
        if last_sync_at is None:
            return True
        last = last_sync_at if last_sync_at.tzinfo else last_sync_at.replace(tzinfo=dt.UTC)
        # Due when the slot has passed and nothing has run since it. The check
        # runs every few minutes, so a slot is caught shortly after it opens
        # and then not again until the next one.
        return last < occurrence

    if last_sync_at is None:
        return True
    last = last_sync_at if last_sync_at.tzinfo else last_sync_at.replace(tzinfo=dt.UTC)
    return (now - last).total_seconds() >= max(interval_minutes, 1) * 60
