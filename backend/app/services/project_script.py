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
from app.models import ProjectScript
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
                  error=str(exc), ran=source)
        raise
    except CommandError as exc:
        # An empty script, or one whose first word is not a command. Nothing
        # ran, so nothing is recorded but the complaint and the text somebody
        # typed - and nothing is forgotten either.
        _remember_attempt(db, script, error=str(exc), ran=source)
        raise
    _remember(db, script, read=outcome.read, written=outcome.written, error="", ran=source)
    return outcome


def _remember_attempt(
    db: Session, script: ProjectScript, *, error: str, ran: str
) -> None:
    """A run that never started: keep what was typed, forget nothing else.

    `reads` and `writes` are what the last run actually touched. They are how
    a newer export finds the scripts standing on it, and how a script keeps
    the right to rewrite the output it made. A script with no command in it
    touched nothing - and writing that down as "touched nothing" would throw
    away the real run's record, unhooking the script from its data so that a
    fresh export no longer re-runs it and its outputs go quietly stale. That
    is the one thing this whole subsystem exists to prevent.

    `last_run_at` stays where it was for the same reason: nothing ran, so
    nothing here is a newer run than the last one.
    """
    script.last_error = error
    script.last_run_text = ran
    db.flush()


def _remember(
    db: Session,
    script: ProjectScript,
    *,
    read: list[str],
    written: list[str],
    error: str,
    ran: str,
) -> None:
    script.reads = list(dict.fromkeys(read))
    script.writes = list(dict.fromkeys(written))
    script.last_run_at = utcnow()
    script.last_error = error
    # Kept on a failed run too. That is the one you most want back: the editor
    # would otherwise open blank on the script that just went wrong.
    script.last_run_text = ran
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


def _names_of(db: Session, project_ids: list[str]) -> dict[str, str]:
    """Every project's name in one query rather than one query per script."""
    from app.models import Project

    if not project_ids:
        return {}
    rows = db.execute(
        select(Project.id, Project.name).where(Project.id.in_(set(project_ids)))
    ).all()
    return {row[0]: row[1] for row in rows}



@dataclass
class Place:
    """One script's place in the order the scripts run in.

    `step` is how many scripts have to have run before this one can: every
    script at step 0 can run at once, every script at step 1 waits on one of
    those, and so on. A number rather than a position in a list, because the
    order is not a queue. Three scripts that read nothing another script wrote
    are not first, second and third - they are all first, and saying so is the
    difference between a list somebody can act on and a list they have to work
    out for themselves.

    `waits_for` names the scripts immediately above it, which is what makes a
    step legible: step 2 means nothing without knowing who step 2 waited for.
    """

    project_id: str
    project_name: str
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    step: int = 0
    # Where somebody put this script among the ones it shares a step with.
    # A tie-break and nothing more: the step comes from the data.
    rank: int = 0
    waits_for: list[str] = field(default_factory=list)
    # Set when the script is in a ring: it reads something another script
    # writes, which reads something this one writes. Then there is no order,
    # and saying so is the only honest answer.
    in_a_cycle: bool = False


def running_order(db: Session, scripts: list[ProjectScript]) -> list[Place]:
    """What order these scripts have to run in, from what they last touched.

    A script that writes a dataset another script reads has to run first, or
    the second one builds on last week's data. Nobody writes that order down,
    and with a script per project it is not visible from any one of them -
    which is the whole reason for reading it off the record of what each run
    actually opened and saved.

    Derived from `reads` and `writes` rather than from the script text, for
    the same reason the re-run chain is: the text would have to be resolved
    the way `use` does, and would count a line that never ran.

    A script that has never run has nothing recorded, so it has no edges and
    sits at step 0 with everything else that waits on nobody. That is honest -
    it is a draft, and nothing is known about what it will touch.
    """
    names = _names_of(db, [script.project_id for script in scripts])
    places = {
        script.project_id: Place(
            project_id=script.project_id,
            # The plain name. `_project_name` above quotes it, because it is
            # written into a sentence; here it is a heading on a page.
            project_name=names.get(script.project_id, "Unnamed project"),
            reads=list(script.reads or []),
            writes=list(script.writes or []),
            rank=script.run_rank or 0,
        )
        for script in scripts
    }

    # Which scripts write each dataset - all of them, not the first.
    #
    # `save as` refuses a dataset another script owns, which made one writer
    # per dataset look like a rule. It is not: `save, replace` writes back
    # over whatever the script opened, with no claim of ownership, so a second
    # project's script can `use` a dataset and write it while the first still
    # lists the same id from the run that made it. Keeping only the first
    # writer put the reader after one of them and before the other, which is
    # the stale read this page exists to prevent - arrived at by following it.
    written_by: dict[str, set[str]] = {}
    for script in scripts:
        for dataset_id in script.writes or []:
            written_by.setdefault(dataset_id, set()).add(script.project_id)

    # waiting[a] is every script a has to wait for.
    waiting: dict[str, set[str]] = {one: set() for one in places}
    for script in scripts:
        for dataset_id in script.reads or []:
            for writer in written_by.get(dataset_id, ()):
                if writer != script.project_id:
                    waiting[script.project_id].add(writer)

    for project_id, above in waiting.items():
        places[project_id].waits_for = sorted(
            places[one].project_name for one in above
        )

    # Kahn's algorithm, in rounds rather than one at a time: a round is a step,
    # which is what makes "these four can run together" readable off the page.
    left = dict(waiting)
    step = 0
    while left:
        ready = sorted(
            (one for one, above in left.items() if not above & left.keys()),
            key=lambda one: (places[one].rank, places[one].project_name.lower()),
        )
        if not ready:
            # Everything still here is in a ring, or waits on one.
            for one in left:
                places[one].in_a_cycle = True
            break
        for one in ready:
            places[one].step = step
            del left[one]
        step += 1

    # Within a step, the order somebody chose, then the name for anything they
    # have not touched. Across steps the data decides and a rank cannot reach:
    # the step is settled above, before any of this is read.
    return sorted(
        places.values(),
        key=lambda place: (
            place.in_a_cycle,
            place.step,
            place.rank,
            place.project_name.lower(),
        ),
    )

# Where a moved output records the script that may keep rebuilding it.
REBUILT_BY = "rebuilt_by_project"


def claimed_by(db: Session, dataset_id: str) -> list[str]:
    """Every project whose script claims to have built this dataset.

    Every one, not the first that comes back. One writer per dataset looked
    like a rule and is not - `save, replace` writes back over whatever the
    script opened, and claims it the same as `save as` does - so a query for
    one claimant returns whichever row the database happens to yield first.
    That would authorise one writer, refuse the others, and change its mind
    between runs.

    It also means a claim can land on a dataset that arrived in an archive,
    rather than only on one a script created. That is how the grant reaches
    an import review: an archive gets uploaded over again.
    """
    from app.models import ProjectScript as Script

    return sorted(
        {
            script.project_id
            for script in db.scalars(select(Script)).all()
            if dataset_id in (script.writes or [])
        }
    )


def note_move(db: Session, dataset, moved_to: str | None) -> None:
    """Record, at the moment of the move, that a script may still rebuild it.

    A script writes into its own project and reads from its own project, so
    the only way one project's script feeds another's is for somebody to move
    the output across. The script has to go on rebuilding it or the reader is
    left with whatever it held the day it moved - and letting it do that is a
    permission, not a detail.

    Recorded here because this is where the permission is actually granted.
    Moving needs the manager role on both projects, so whoever does it is
    entitled to say that this project's script may write into that one. Read
    off `writes` afterwards instead, the way this started, and the permission
    would be inferred from history by somebody who never agreed to it: the
    source project's manager need never have had any rights over the
    destination, and would still be writing into it.

    The grant travels with the dataset and is rewritten on every move, so
    moving it again re-asks the question of whoever moves it, and moving it
    home clears it.
    """
    meta = dict(dataset.meta or {})
    claimants = [one for one in claimed_by(db, dataset.id) if one != moved_to]
    if claimants:
        meta[REBUILT_BY] = claimants
    else:
        meta.pop(REBUILT_BY, None)
    dataset.meta = meta


def release(db: Session, dataset) -> None:
    """Drop the grant when a dataset is let go rather than moved.

    Deleting a project without its contents releases its datasets to the
    shared area. Nobody chose a destination there, so nobody granted anything,
    and a grant left over from the move that put the dataset in that project
    would outlive the project it was about - letting the script that built it
    go on writing to a dataset now sitting in the open.
    """
    meta = dict(dataset.meta or {})
    if meta.pop(REBUILT_BY, None) is not None:
        dataset.meta = meta


def without_grant(meta: dict | None) -> dict:
    """`meta` as it may leave the server, or be copied into anything that does.

    The grant is authorization state living in a bag that several things hand
    out or copy wholesale, so it is removed here rather than at each of them.
    Two have been found so far - the dataset the API answers with, and the
    candidates an import review parks in a job's parameters - and the second
    was found after the first was filtered, which is the argument for one
    function rather than a filter per exit.
    """
    return {key: one for key, one in (meta or {}).items() if key != REBUILT_BY}


def may_rebuild(dataset, project_id: str | None) -> bool:
    """Whether this project's script may write over a dataset that has moved."""
    if project_id is None:
        return False
    return project_id in ((dataset.meta or {}).get(REBUILT_BY) or [])
