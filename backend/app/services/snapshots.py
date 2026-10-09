"""Keeping a dashboard as it stood, and throwing the old ones away.

A saved view remembers which filters were chosen; the numbers it opens are
always the current ones. So "how did the board look on the 7th" is a question
views cannot answer, however they are named - and naming them after dates is
exactly what people do, which makes the gap easy to miss.

A snapshot answers it. It is the file the export button already produces - one
self-contained page carrying the data behind every widget - written to disk and
listed against the dashboard.

Writing the file before the row, and the row before the prune, so a failure
anywhere leaves either nothing or something complete. A row pointing at a file
that was never written is worse than no row.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import utcnow
from app.models.analytics import Dashboard, DashboardSnapshot
from app.services import static_export
from app.services.scheduling import is_due, zone

# Monday first, matching date.weekday() and the UI's own order.
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def directory() -> Path:
    place = settings.storage_path / "snapshots"
    place.mkdir(parents=True, exist_ok=True)
    return place


def describe(moment: dt.datetime, timezone: str) -> str:
    """What to call a snapshot, in the board's own zone.

    Formatted once and stored, rather than on every read: the moment meant
    08:00 where the fieldwork is, and a reader in another zone should see that
    rather than their own translation of it.
    """
    local = moment.astimezone(zone(timezone))
    return f"{WEEKDAYS[local.weekday()]} {local.day} {local:%B %Y}, {local:%H:%M}"


def due(dashboard: Dashboard, now: dt.datetime | None = None) -> bool:
    """Whether this board's next capture is owed."""
    if not dashboard.snapshot_enabled:
        return False
    # No guard for an empty times list: is_due already treats a daily schedule
    # with nothing set as never due, and a second check here would be a rule
    # in two places that can only disagree.
    return is_due(
        mode="daily",
        times=list(dashboard.snapshot_times or []),
        timezone=dashboard.snapshot_timezone or "UTC",
        interval_minutes=0,
        last_sync_at=dashboard.last_snapshot_at,
        now=now or utcnow(),
        days=list(dashboard.snapshot_days or []),
    )


def take(
    db: Session,
    dashboard: Dashboard,
    # Takes the filter as well as the widget: build_payload hands one through
    # for a pinned export, and None for an ordinary one like this.
    render: Callable[[Any, Any], Any],
    *,
    automatic: bool = False,
    user_id: str | None = None,
    now: dt.datetime | None = None,
) -> DashboardSnapshot:
    """Capture the board and keep it."""
    moment = now or utcnow()
    payload = static_export.build_payload(db, dashboard, render=render)
    html = static_export.render_html(payload, static_export.appearance_css(dashboard))

    snapshot = DashboardSnapshot(
        dashboard_id=dashboard.id,
        label=describe(moment, dashboard.snapshot_timezone or "UTC"),
        taken_at=moment,
        is_automatic=automatic,
        created_by=user_id,
    )
    db.add(snapshot)
    # Flushed for the id, which names the file: two captures of one board in
    # the same minute would otherwise write over each other.
    db.flush()

    path = directory() / f"{snapshot.id}.html"
    body = html.encode("utf-8")
    path.write_bytes(body)
    snapshot.storage_path = str(path)
    snapshot.size_bytes = len(body)

    dashboard.last_snapshot_at = moment
    return snapshot


def prune(db: Session, dashboard: Dashboard) -> int:
    """Drop the oldest automatic captures beyond what the board keeps.

    Only the automatic ones. A snapshot somebody took by hand was taken for a
    reason, and a schedule quietly deleting it a month later is the kind of
    loss nobody reports until it matters.
    """
    keep = max(int(dashboard.snapshot_keep or 0), 1)
    rows = db.scalars(
        select(DashboardSnapshot)
        .where(
            DashboardSnapshot.dashboard_id == dashboard.id,
            DashboardSnapshot.is_automatic.is_(True),
        )
        .order_by(DashboardSnapshot.taken_at.desc())
    ).all()
    dropped = 0
    for snapshot in rows[keep:]:
        discard_file(snapshot)
        db.delete(snapshot)
        dropped += 1
    return dropped


def discard_file(snapshot: DashboardSnapshot) -> None:
    """Remove a snapshot's file, if it is still there.

    Missing is fine: the row is going either way, and a delete that fails
    because somebody already cleared the disk leaves a row pointing at
    nothing, which is the state this is trying to avoid.
    """
    if not snapshot.storage_path:
        return
    # Suppressed rather than handled: the row is going either way, and a
    # delete that fails because somebody already cleared the disk would
    # otherwise leave a row pointing at nothing, which is the state this is
    # trying to avoid.
    with contextlib.suppress(OSError):
        Path(snapshot.storage_path).unlink(missing_ok=True)
