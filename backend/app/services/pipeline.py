"""What happens after new data lands, in the order it has to happen.

A newer export is not finished when its files are read. Everything built on
the data has to follow it, and in one order only:

1. the commands recorded on a replaced dataset are applied again, because a
   generated variable is not in the export;
2. the merges standing on what changed are rebuilt, from the data as step 1
   left it;
3. the project scripts reading any of that are re-run, after the merges,
   since a script may read a merged dataset;
4. the dashboards reading any of it are named. Their charts query the data
   as it now is, and the indicator tiles were recomputed as each dataset
   landed (see datasets._apply_ingest), so they show the new data now rather
   than at the next scheduled tick. Alerts and quality checks are left to
   that tick, which is what keeps an import from emailing anybody halfway
   through being written.

Every way data arrives - an upload, a queued upload, a Survey Solutions sync,
a folder connection, a reviewed import, the command line - used to carry its
own copy of this, and the copies had drifted: a sync rebuilt merges and never
ran a script, an append rebuilt nothing at all, and nothing said which
dashboards had moved. So it lives here once, and each path calls it.

Each step is written to the job as it starts and finishes, which is what the
activity panel shows. And nothing is passed over in silence: a merge that
could not be rebuilt, or a script that was not run, is a line in the job and
a note on the dataset rather than an entry in a log nobody reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import (
    Chart,
    Dashboard,
    Dataset,
    Indicator,
    Job,
    Project,
    ProjectScript,
    Widget,
)
from app.services import preferences, project_script, stata
from app.services.derived import MergeOutcome, rebuild_merges

logger = get_logger(__name__)

# The steps after the data is read, as the activity panel names them.
AFTER_IMPORT = [
    ("commands", "Re-apply recorded commands"),
    ("merges", "Rebuild merged datasets"),
    ("scripts", "Run project scripts"),
    ("refresh", "Update indicators and dashboards"),
]


class Progress:
    """The steps of one job, written onto it as they happen.

    Written through whichever session the step is running in, and committed
    there, so that somebody watching sees a step start while it runs rather
    than the whole list appear at the end. That makes each step's own work
    durable as it finishes, which is what these steps already were in effect:
    a merge rebuilt is not undone because a script after it failed.

    With no job - an upload read inside the request that carried it - nothing
    is written, and the steps are returned with the answer instead.
    """

    def __init__(self, job_id: str | None, steps: list[tuple[str, str]]):
        self.job_id = job_id
        self.stages: list[dict[str, Any]] = [
            {"key": key, "label": label, "status": "pending", "detail": "", "items": []}
            for key, label in steps
        ]

    def _stage(self, key: str) -> dict[str, Any]:
        for stage in self.stages:
            if stage["key"] == key:
                return stage
        raise KeyError(key)

    def start(self, db: Session | None, key: str, detail: str = "") -> None:
        stage = self._stage(key)
        stage.update(status="running", detail=detail, started_at=utcnow().isoformat())
        self.save(db)

    def finish(
        self,
        db: Session | None,
        key: str,
        detail: str = "",
        *,
        status: str = "done",
        items: list[dict[str, Any]] | None = None,
    ) -> None:
        """Close a step. `status` is done, warning, failed or skipped."""
        stage = self._stage(key)
        stage.update(status=status, detail=detail, finished_at=utcnow().isoformat())
        if items is not None:
            stage["items"] = items
        self.save(db)

    def skip_rest(self, db: Session | None, detail: str) -> None:
        """Mark every step not yet reached as skipped, saying why."""
        for stage in self.stages:
            if stage["status"] in ("pending", "running"):
                stage.update(status="skipped", detail=detail)
        self.save(db)

    @property
    def fraction(self) -> float:
        closed = sum(1 for s in self.stages if s["status"] not in ("pending", "running"))
        return round(100.0 * closed / len(self.stages), 1) if self.stages else 0.0

    def save(self, db: Session | None) -> None:
        if not self.job_id or db is None:
            return
        job = db.get(Job, self.job_id)
        if job is None:
            return
        # A new list each time: the column is JSON, and a list changed in
        # place is not seen as changed.
        job.stages = [dict(stage) for stage in self.stages]
        job.progress = min(self.fraction, 99.0)
        db.commit()

    def save_now(self) -> None:
        """Save through a session of its own, between transactions."""
        if not self.job_id:
            return
        from app.db.session import session_scope

        with session_scope() as db:
            self.save(db)


@dataclass
class Aftermath:
    """What following the new data did, for the job's summary."""

    merges: list[MergeOutcome] = field(default_factory=list)
    reruns: list[project_script.Rerun] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    indicators: int = 0
    dashboards: list[str] = field(default_factory=list)
    # The datasets the re-run scripts wrote, by name.
    script_outputs: list[str] = field(default_factory=list)

    @property
    def rebuilt(self) -> list[str]:
        return [o.dataset_id for o in self.merges if o.status == "rebuilt"]

    def notes(self) -> list[str]:
        """The lines a person reads in the import's report."""
        lines: list[str] = []
        rebuilt = sorted(o.name for o in self.merges if o.status == "rebuilt")
        if rebuilt:
            lines.append("Rebuilt from the new data: " + ", ".join(rebuilt))
        lines.extend(
            f"'{o.name}' was not rebuilt: {o.message}"
            for o in self.merges
            if o.status != "rebuilt"
        )
        if self.script_outputs:
            lines.append("Rebuilt by the project's script: " + ", ".join(self.script_outputs))
        lines.extend(self.warnings)
        if self.dashboards:
            lines.append("Showing the new data: " + ", ".join(sorted(self.dashboards)))
        return lines


def after_import(
    db: Session,
    *,
    changed: list[str],
    replaced: list[str] | None = None,
    replay: bool = False,
    progress: Progress | None = None,
) -> Aftermath:
    """Bring everything built on these datasets up to date with them.

    `changed` is every dataset the import wrote - replaced, appended to or
    created. An append changes what a merge joins as surely as a replacement
    does, and leaving it out was how an incremental export never reached the
    merges at all.

    `replaced` is the subset whose recorded commands are applied again, and
    only when `replay` is set: a path that already replayed each replacement
    as it landed says so by leaving it unset. An append is never replayed - it
    keeps the generated columns, and applying `replace x = x + 1` again would
    add two.
    """
    progress = progress or Progress(None, AFTER_IMPORT)
    changed = list(dict.fromkeys(changed))
    replaced = list(dict.fromkeys(replaced or []))
    outcome = Aftermath()

    # 1. Recorded commands.
    if replay and replaced:
        progress.start(db, "commands")
        problems: list[str] = []
        for dataset_id in replaced:
            dataset = db.get(Dataset, dataset_id)
            if dataset is not None:
                problems.extend(stata.replay(db, dataset))
        db.flush()
        outcome.warnings.extend(problems)
        progress.finish(
            db,
            "commands",
            f"Applied to {len(replaced)} dataset(s)"
            + (f"; {len(problems)} could not be applied" if problems else ""),
            status="warning" if problems else "done",
            items=[{"name": p, "status": "warning"} for p in problems],
        )
    else:
        progress.finish(
            db,
            "commands",
            "Applied as each dataset was replaced" if replaced else "Nothing was replaced",
            status="done" if replaced else "skipped",
        )

    # 2. Merges, from the data as the commands left it.
    progress.start(db, "merges")
    outcome.merges = rebuild_merges(db, changed)
    db.flush()
    trouble = [o for o in outcome.merges if o.status != "rebuilt"]
    progress.finish(
        db,
        "merges",
        _merge_summary(outcome.merges),
        status="warning" if trouble else ("done" if outcome.merges else "skipped"),
        items=[
            {"name": o.name, "status": o.status, "detail": o.message, "dataset_id": o.dataset_id}
            for o in outcome.merges
        ],
    )

    # 3. Scripts, after the merges: a script may read a merged dataset.
    progress.start(db, "scripts")
    standing = changed + outcome.rebuilt
    outcome.reruns = project_script.rerun_for(db, standing)
    db.flush()
    unsaved = _unsaved_scripts_on(db, standing, {r.project_id for r in outcome.reruns})
    outcome.warnings.extend(project_script.warnings_from(db, outcome.reruns))
    outcome.warnings.extend(
        f"The script for '{name}' reads this data but was never saved, so it was not "
        "re-run. Save it on the project's Script tab to have it run on every import."
        for name in unsaved
    )
    names = _project_names(db, [r.project_id for r in outcome.reruns])
    written = {i for r in outcome.reruns if r.ran for i in r.written}
    outcome.script_outputs = sorted(
        one.name for one in (db.get(Dataset, i) for i in written) if one is not None
    )
    failed = [r for r in outcome.reruns if not r.ran]
    progress.finish(
        db,
        "scripts",
        _script_summary(outcome.reruns, unsaved),
        status=(
            "warning"
            if failed or unsaved
            else ("done" if outcome.reruns else "skipped")
        ),
        items=[
            {
                "name": names.get(r.project_id, "a project"),
                "status": "ran" if r.ran else "failed",
                "detail": r.error,
            }
            for r in outcome.reruns
        ]
        + [{"name": name, "status": "not saved", "detail": ""} for name in unsaved],
    )

    # 4. What a dashboard reads. Nothing is computed here: every dataset
    # written above recomputed its indicators as it landed. This says which
    # boards that reaches, which is the question somebody watching asks.
    progress.start(db, "refresh")
    affected = set(standing) | {i for r in outcome.reruns if r.ran for i in r.written}
    outcome.indicators = _indicators_on(db, affected)
    outcome.dashboards = _dashboards_on(db, affected)
    progress.finish(
        db,
        "refresh",
        _refresh_summary(outcome.indicators, outcome.dashboards),
        status="done" if outcome.indicators or outcome.dashboards else "skipped",
        items=[{"name": name, "status": "updated"} for name in sorted(outcome.dashboards)],
    )
    return outcome


def _merge_summary(merges: list[MergeOutcome]) -> str:
    if not merges:
        return "No merged dataset stands on this data"
    counts = {
        status: sum(1 for o in merges if o.status == status)
        for status in ("rebuilt", "failed", "stuck")
    }
    parts = [f"{counts['rebuilt']} rebuilt"]
    if counts["failed"]:
        parts.append(f"{counts['failed']} failed")
    if counts["stuck"]:
        parts.append(f"{counts['stuck']} could not be rebuilt")
    return ", ".join(parts)


def _script_summary(reruns: list[project_script.Rerun], unsaved: list[str]) -> str:
    if not reruns and not unsaved:
        return "No saved script reads this data"
    parts: list[str] = []
    ran = sum(1 for r in reruns if r.ran)
    if reruns:
        parts.append(f"{ran} ran")
    if len(reruns) - ran:
        parts.append(f"{len(reruns) - ran} failed")
    if unsaved:
        parts.append(f"{len(unsaved)} not run because never saved")
    return ", ".join(parts)


def _refresh_summary(indicators: int, dashboards: list[str]) -> str:
    if not indicators and not dashboards:
        return "No indicator or dashboard reads this data"
    said = f"{indicators} indicator(s) recomputed"
    if dashboards:
        said += f"; {len(dashboards)} dashboard(s) now show the new data"
    return (
        said + f". Alerts and quality checks follow at the next scheduled check "
        f"(every {preferences.value('monitor_tick_minutes')} minutes)."
    )


def _unsaved_scripts_on(db: Session, dataset_ids: list[str], already: set[str]) -> list[str]:
    """Projects whose last run read this data, with nothing saved to run again."""
    wanted = set(dataset_ids)
    found = [
        script.project_id
        for script in db.scalars(select(ProjectScript)).all()
        if script.project_id not in already
        and not script.text.strip()
        and wanted.intersection(script.reads or [])
    ]
    names = _project_names(db, found)
    return sorted(names[one] for one in found if one in names)


def _project_names(db: Session, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = db.execute(select(Project.id, Project.name).where(Project.id.in_(set(ids)))).all()
    return {row[0]: row[1] for row in rows}


def _indicators_on(db: Session, dataset_ids: set[str]) -> int:
    """How many active indicators read these datasets."""
    if not dataset_ids:
        return 0
    return len(
        db.scalars(
            select(Indicator.id).where(
                Indicator.dataset_id.in_(dataset_ids), Indicator.is_active.is_(True)
            )
        ).all()
    )


def _dashboards_on(db: Session, dataset_ids: set[str]) -> list[str]:
    """The dashboards with a widget reading any of these datasets."""
    if not dataset_ids:
        return []
    charts = set(db.scalars(select(Chart.id).where(Chart.dataset_id.in_(dataset_ids))).all())
    indicators = set(
        db.scalars(select(Indicator.id).where(Indicator.dataset_id.in_(dataset_ids))).all()
    )
    boards: set[str] = set()
    for widget in db.scalars(select(Widget)).all():
        if (
            widget.dataset_id in dataset_ids
            or (widget.chart_id and widget.chart_id in charts)
            or (widget.indicator_id and widget.indicator_id in indicators)
        ):
            boards.add(widget.dashboard_id)
    if not boards:
        return []
    return sorted(db.scalars(select(Dashboard.name).where(Dashboard.id.in_(boards))).all())
