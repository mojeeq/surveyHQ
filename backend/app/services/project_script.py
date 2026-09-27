"""A project's do-file: where it is kept, and when it runs again.

The script is the recipe, not a one-off. A survey is exported again every
night, and a dataset the script read is replaced under it; the datasets the
script built then hold last week's join and say nothing. So a replacement
re-runs every script that stands on what was replaced.

What "stands on" means is recorded rather than worked out. Each run remembers
the datasets it actually opened, so a later import can ask which scripts read
this one. Reading it out of the text instead would mean resolving names the
way `use` does, and would count a line that never ran because the one above it
failed.

A re-run is the whole script from the top, which is the only version of this
that is honest. A script is a sequence - read these, join them, collapse that -
and re-running half of it would leave the other half describing data that no
longer exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import Dataset, ProjectScript
from app.services import stata
from app.services.stata import CommandError, ScriptError

logger = get_logger(__name__)


@dataclass
class Rerun:
    """What happened to one script when its data changed underneath it."""

    project_id: str
    ran: bool
    error: str = ""
    written: list[str] = field(default_factory=list)


def script_for(db: Session, project_id: str) -> ProjectScript:
    """The project's script, made on first sight so callers never see None."""
    found = db.scalars(
        select(ProjectScript).where(ProjectScript.project_id == project_id)
    ).first()
    if found is not None:
        return found
    made = ProjectScript(project_id=project_id, text="", reads=[], writes=[])
    db.add(made)
    db.flush()
    return made


def run(db: Session, project_id: str, text: str | None = None) -> stata.ScriptOutcome:
    """Run the project's script and remember what it touched.

    `text` runs something other than what is stored, which is what the editor
    does: a script is tried before it is kept, and a run that fails should not
    have to be undone by hand.
    """
    script = script_for(db, project_id)
    source = script.text if text is None else text
    try:
        # What the last run built is what this one may rebuild.
        outcome = stata.run_project_script(
            db, project_id, source, owns=set(script.writes or [])
        )
    except ScriptError as exc:
        _remember(db, script, read=exc.read, written=[s.dataset_id for s in exc.saved],
                  error=str(exc))
        raise
    except CommandError as exc:
        # An empty script, or one whose first word is not a command. Nothing
        # was read, so nothing recorded but the complaint.
        _remember(db, script, read=[], written=[], error=str(exc))
        raise
    _remember(db, script, read=outcome.read, written=outcome.written, error="")
    return outcome


def _remember(
    db: Session,
    script: ProjectScript,
    *,
    read: list[str],
    written: list[str],
    error: str,
) -> None:
    script.reads = list(dict.fromkeys(read))
    script.writes = list(dict.fromkeys(written))
    script.last_run_at = utcnow()
    script.last_error = error
    db.flush()


def standing_on(db: Session, changed_ids: list[str]) -> list[ProjectScript]:
    """The scripts whose last run read one of these datasets.

    A script that has never run reads nothing and so is never picked up here.
    That is deliberate: a script nobody has run once is a draft, and running a
    draft for the first time in the middle of somebody's nightly import is not
    a thing to do unasked.
    """
    if not changed_ids:
        return []
    wanted = set(changed_ids)
    return [
        script
        for script in db.scalars(select(ProjectScript)).all()
        if script.text.strip() and wanted.intersection(script.reads or [])
    ]


def rerun_for(db: Session, changed_ids: list[str]) -> list[Rerun]:
    """Re-run every script standing on the datasets that just changed.

    Works outwards in rounds, the way merges rebuild: a script that reads what
    another script wrote has to wait for that one, and the datasets a script
    writes are themselves changed for the next round. Bounded by the number of
    scripts, which also stops two scripts that read each other's output from
    looping here.

    A script that fails is reported and does not stop the rest. The import has
    already happened; a script that no longer applies is a note beside the data
    rather than a failure of somebody's upload.
    """
    if not changed_ids:
        return []

    stale = set(changed_ids)
    done: set[str] = set()
    outcomes: list[Rerun] = []

    # One round per script is enough for any chain of them: each round runs at
    # least one, or nothing is left that can run.
    for _ in range(len(db.scalars(select(ProjectScript)).all()) or 1):
        ready = [s for s in standing_on(db, sorted(stale)) if s.project_id not in done]
        if not ready:
            break
        for script in ready:
            done.add(script.project_id)
            try:
                outcome = run(db, script.project_id)
            except (ScriptError, CommandError) as exc:
                logger.warning(
                    "The script for project %s could not be re-run: %s",
                    script.project_id,
                    exc,
                )
                outcomes.append(
                    Rerun(project_id=script.project_id, ran=False, error=str(exc))
                )
                continue
            written = outcome.written
            stale.update(written)
            outcomes.append(
                Rerun(project_id=script.project_id, ran=True, written=written)
            )
    return outcomes


def warnings_from(db: Session, outcomes: list[Rerun]) -> list[str]:
    """What to put beside the data when a re-run did not go through.

    Named by project rather than by id, because the person reading this is
    looking at an upload page and has no idea what a uuid is.
    """
    notes: list[str] = []
    for outcome in outcomes:
        if outcome.ran:
            continue
        name = _project_name(db, outcome.project_id)
        notes.append(
            f"The script for {name} could not be re-run against the new data: "
            f"{outcome.error}"
        )
    return notes


def _project_name(db: Session, project_id: str) -> str:
    from app.models import Project

    project = db.get(Project, project_id)
    return f"'{project.name}'" if project is not None else "this project"


def outputs_of(db: Session, project_id: str) -> list[Dataset]:
    """The datasets the script last wrote, for the page that shows them."""
    script = db.scalars(
        select(ProjectScript).where(ProjectScript.project_id == project_id)
    ).first()
    if script is None:
        return []
    found = [db.get(Dataset, dataset_id) for dataset_id in script.writes or []]
    return [dataset for dataset in found if dataset is not None]
