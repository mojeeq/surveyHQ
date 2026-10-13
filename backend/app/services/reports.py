"""One report per value of a filter, in a single run.

A dashboard exports as one file whose filters still work, and with a view
pinned it exports as one province's file. Fourteen provinces is then fourteen
trips through the browser, and somebody has to remember which ones they have
already done.

This does the loop. It enumerates a filter variable's values, builds a pinned
export for each, and writes them into one zip. Each file is narrowed rather
than preselected, exactly as a single pinned export is, so the Northern file in
the zip holds Northern and nothing else and can be forwarded on its own.

It is slow by nature: every value is a full pass over the dataset for every
widget, so fourteen provinces is fourteen times the work of one export. That
is why it runs on the worker behind a job rather than inside a request.

The zips are kept for the last few runs of a board and swept once the job row
that names them has been pruned by age. A board bursting weekly would
otherwise fill the disk the platform runs on a megabyte at a time, to hold
reports nobody is going to ask for again.
"""

from __future__ import annotations

import contextlib
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Dashboard, Job, JobStatus, JobType
from app.services import static_export

logger = get_logger(__name__)

# More reports than anybody reads, and the point past which this is the wrong
# tool. A burst over an interviewer id would be thousands of files and hours
# of work; refusing is kinder than starting it.
MAX_REPORTS = 60

# How many runs of one board's burst to keep the zips of. A burst is a report
# per province for every widget on the board, so a weekly one is megabytes a
# week for as long as the platform runs, and nobody downloads last month's.
# The sync archives keep the last five per connection for the same reason.
BURSTS_KEPT = 5


def directory() -> Path:
    place = settings.storage_path / "reports"
    place.mkdir(parents=True, exist_ok=True)
    return place


class TooMany(Exception):
    """The variable has more values than this is a sensible way to report on."""


def values_for(db: Session, dashboard: Dashboard, variable: str) -> list[str]:
    """What the burst will produce one report for.

    Taken from the dashboard's own filter control rather than from the
    variable alone, so the reports cover exactly the choices the board offers
    and arrive in the same order the dropdown lists them.
    """
    control = next(
        (
            one
            for one in static_export._filters_for(dashboard)
            if one["variable"] == variable
        ),
        None,
    )
    if control is None:
        raise LookupError(f"This dashboard has no {variable} filter.")
    ctx = static_export._ctx_for(db, control["dataset_id"])
    if ctx is None:
        raise LookupError("The dataset behind that filter is not available.")
    return static_export._values_for(ctx, variable)


def burst(
    db: Session,
    dashboard: Dashboard,
    variable: str,
    render: Callable[[Any, Any], Any],
    destination: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Write one pinned export per value into a zip at `destination`.

    A value whose report cannot be built is recorded and skipped rather than
    stopping the rest: thirteen provinces and a note about the fourteenth is
    worth more than nothing at all, and the note says which one to look at.
    """
    values = values_for(db, dashboard, variable)
    if len(values) > MAX_REPORTS:
        raise TooMany(
            f"{variable} has {len(values)} values and this would write that many "
            f"reports. The limit is {MAX_REPORTS}."
        )

    board = slugify(dashboard.name)[:80] or "dashboard"
    stylesheet = static_export.appearance_css(dashboard)
    written: list[str] = []
    skipped: list[dict[str, str]] = []

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Written to a temporary name and moved when complete, so a failure
    # halfway leaves no zip rather than a half one somebody downloads.
    working = destination.with_suffix(".part")
    with zipfile.ZipFile(working, "w", zipfile.ZIP_DEFLATED) as bundle:
        for index, value in enumerate(values):
            try:
                payload = static_export.build_payload(
                    db, dashboard, render=render, pinned={variable: value}
                )
                html = static_export.render_html(payload, stylesheet)
            except Exception as error:  # noqa: BLE001 - one value must not stop the rest
                logger.exception("Report failed for %s = %s", variable, value)
                skipped.append({"value": value, "error": str(error)})
            else:
                name = f"{board}-{slugify(value)[:60] or 'value'}.html"
                bundle.writestr(name, html)
                written.append(value)
            if on_progress:
                on_progress(index + 1, len(values))
    working.replace(destination)

    return {
        "variable": variable,
        "written": written,
        "skipped": skipped,
        "path": str(destination),
        "bytes": destination.stat().st_size,
    }


def _discard(path: Path) -> None:
    """Remove a file if it is still there, and make no fuss if it is not.

    Missing is the state this is trying to reach. A delete that raised because
    somebody had already cleared the disk by hand would leave a job row still
    claiming a file that is gone.
    """
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _burst_file(job: Job) -> Path | None:
    """The zip a run wrote, if it wrote one this module is responsible for.

    The directory is checked rather than taken on trust: a job whose recorded
    path points anywhere else is not a burst zip and is not ours to delete.
    The same check answers a run whose zip has already been pruned, which
    records no path at all - an empty path is not in `reports/` either.
    """
    path = Path(str((job.result or {}).get("path") or ""))
    return path if path.parent == directory() else None


def prune_bursts(db: Session, dashboard_id: str, keep: int = BURSTS_KEPT) -> int:
    """Delete all but the last few burst zips for one board.

    The file goes and the job row stays. The run is then still in the history
    with its list of what was written and what was skipped, and the download
    answers that the file is no longer on disk - which is true, and more use
    than a 404 implying the run never happened.
    """
    runs: list[tuple[Job, Path]] = []
    for job in db.scalars(
        select(Job)
        .where(Job.job_type == JobType.export, Job.status == JobStatus.success)
        .order_by(Job.created_at.desc())
    ).all():
        # Matched here rather than in the query: the board is a key inside a
        # JSON column, and SQLite and PostgreSQL do not read those alike.
        if str((job.params or {}).get("dashboard_id") or "") != dashboard_id:
            continue
        file = _burst_file(job)
        if file is not None:
            runs.append((job, file))

    dropped = 0
    for job, file in runs[keep:]:
        _discard(file)
        # Reassigned rather than edited in place: SQLAlchemy does not notice a
        # JSON column's dict changing under it.
        job.result = {**(job.result or {}), "path": ""}
        dropped += 1
    return dropped


def sweep_bursts(db: Session) -> int:
    """Delete burst files that no job row accounts for.

    A zip is named for the job that wrote it and is recorded nowhere else, so
    once that row is pruned by age the file is unreachable: the download route
    reads the path off the row. Named for the job is also what makes this
    safe - the `.part` file a burst is part way through writing has a row, and
    so stays.
    """
    files = [
        path
        for path in directory().iterdir()
        if path.is_file() and path.suffix in {".zip", ".part"}
    ]
    if not files:
        return 0
    # Every job id rather than a lookup per file, or one `IN` of as many
    # parameters as the directory happens to hold: this runs after the jobs
    # table has been pruned to a month, so it is one column of a few thousand
    # short strings and no query that could grow past what a database takes.
    live = set(db.scalars(select(Job.id)).all())
    swept = 0
    for path in files:
        if path.stem not in live:
            _discard(path)
            swept += 1
    return swept
