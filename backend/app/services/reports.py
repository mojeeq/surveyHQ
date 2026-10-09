"""One report per value of a filter, in a single run.

A dashboard exports as one file whose filters still work, and with a view
pinned it exports as one province's file. Fourteen provinces is then fourteen
trips through the browser, and somebody has to remember which ones they have
already done.

This does the loop. It enumerates a filter variable's values, builds a pinned
export for each, and writes them into one zip. Each file is narrowed rather
than preselected, exactly as a single pinned export is, so the Shefa file in
the zip holds Shefa and nothing else and can be forwarded on its own.

It is slow by nature: every value is a full pass over the dataset for every
widget, so fourteen provinces is fourteen times the work of one export. That
is why it runs on the worker behind a job rather than inside a request.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from slugify import slugify
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Dashboard
from app.services import static_export

logger = get_logger(__name__)

# More reports than anybody reads, and the point past which this is the wrong
# tool. A burst over an interviewer id would be thousands of files and hours
# of work; refusing is kinder than starting it.
MAX_REPORTS = 60


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
