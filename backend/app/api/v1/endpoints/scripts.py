"""Every project's script, and the order they have to run in.

A script belongs to a project and is edited there, which is right: it is that
project's recipe. But a survey office runs more than one project, and the
scripts are not independent of each other - one writes a cleaned person file
that another reads to build an indicator table. Nothing on any single
project's page can show that, because the relationship is between projects.

So there is one page that shows all of them, with the order read off what
each run actually opened and saved. Running them is still done from the
project that owns the script, where the log and the editor are, and the page
links straight there - for the readers who may, which is why each entry says
whether this one can.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Dataset, ProjectScript, Role
from app.schemas.script import ScriptOrderIn, ScriptPlace, ScriptsOverview
from app.services import project_script, stata
from app.services.project_script import running_order
from app.services.projects import can_edit, memberships, visible_projects

router = APIRouter()


def _shown_text(script: ProjectScript) -> str:
    """The script a reader is looking at: the saved one, or what last ran.

    Stripped rather than merely truthy, the same test that decides whether it
    counts as saved. A box cleared to spaces and saved is empty to one and a
    script to the other, so the card counted the whitespace, found no commands
    in it, and said "Run without being saved" over a run of three.
    """
    return script.text if script.text.strip() else (script.last_run_text or "")


def _scripts_for(db: DbSession, user: CurrentUser) -> list[ProjectScript]:
    """The rows this reader can see that are actually scripts.

    A row is made for a project the first time anybody opens its script tab,
    so most of them are empty and are not scripts. One that has run is,
    whatever it holds now: running is deliberately separate from saving - a
    script is tried before it is kept - so text can be empty while the reads
    and writes of a real run are recorded against it.

    One definition because two things ask: the page, and the reorder that
    wants to know what a step contains. Asked separately they disagreed - the
    reorder counted the empty rows, so "the whole step" meant more scripts
    than the page had ever shown, and every reordering was refused.
    """
    allowed = {project.id for project in visible_projects(db, user)}
    return [
        script
        for script in db.scalars(select(ProjectScript)).all()
        if script.project_id in allowed
        and (script.text.strip() or script.last_run_at is not None)
    ]


@router.put("/order", response_model=ScriptsOverview)
def set_order(
    payload: ScriptOrderIn, db: DbSession, user: CurrentUser
) -> ScriptsOverview:
    """Put the scripts of one step in the order somebody wants them run.

    Only within a step. Which script has to run before which comes from what
    they read and write - one writes the file another reads, so the second
    cannot go first and no preference changes that. Inside a step nothing
    waits on anything, the page says as much, and the order there was
    alphabetical: no order at all for somebody who knows which one they do
    first on a Monday.

    So a list spanning two steps is refused, naming what it is that fixes
    them, rather than accepted and quietly ignored - which is what storing a
    rank the sort could not honour would amount to.
    """
    wanted = list(dict.fromkeys(payload.project_ids))
    if len(wanted) < 2:
        raise HTTPException(
            status_code=422, detail="Give the whole step, in the order you want it"
        )

    scripts = {script.project_id: script for script in _scripts_for(db, user)}
    missing = [one for one in wanted if one not in scripts]
    if missing:
        # 404 rather than 403, as everywhere else: a project someone cannot
        # see should not be confirmed to exist by the error.
        raise HTTPException(status_code=404, detail="No such script")

    places = {
        place.project_id: place
        for place in running_order(db, list(scripts.values()))
    }
    steps = {places[one].step for one in wanted}
    tangled = [one for one in wanted if places[one].in_a_cycle]
    if tangled:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{places[tangled[0]].project_name}' is in a ring with another "
                "script - each reads what the other writes, so there is no order "
                "to choose."
            ),
        )
    if len(steps) > 1:
        later = max(wanted, key=lambda one: places[one].step)
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{places[later].project_name}' waits for "
                f"{', '.join(places[later].waits_for)}, so it cannot be moved "
                "among these. Only scripts in the same step can be reordered."
            ),
        )

    # The whole step, so that nothing is left at a rank somebody did not mean.
    # A ring is not part of it: those scripts have no order, sit at step 0 for
    # want of anywhere else, and the page draws them in a section of their own.
    # Counted here, one tangled pair anywhere made every step-0 group
    # unreorderable - refused for not being the whole step by a list that was.
    step = next(iter(steps))
    whole = {
        one
        for one, place in places.items()
        if place.step == step and not place.in_a_cycle
    }
    if whole != set(wanted):
        raise HTTPException(
            status_code=422,
            detail="Give the whole step, in the order you want it",
        )

    held = {} if user.role is Role.admin else memberships(db, user)
    for project_id in wanted:
        if not can_edit(db, user, project_id, Role.manager, held=held):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Changing the order needs the manager role on "
                    f"'{places[project_id].project_name}'."
                ),
            )

    for rank, project_id in enumerate(wanted):
        scripts[project_id].run_rank = rank
    db.commit()
    return overview(db, user)


@router.get("", response_model=ScriptsOverview)
def overview(db: DbSession, user: CurrentUser) -> ScriptsOverview:
    """Every script this user can see, in the order they have to run."""
    scripts = _scripts_for(db, user)

    # Seeing a script and being able to change it are different questions, and
    # the page asks both: it offers an editor, and the editor is the project's,
    # which takes the manager role over that project.
    #
    # Asked of the scripts being drawn rather than of every project the reader
    # can see, and from one reading of their memberships rather than one per
    # project. Asking project by project cost a query each: six projects, seven
    # queries, and an office with a hundred would have paid for all of them to
    # draw the handful that have a script.
    held = {} if user.role is Role.admin else memberships(db, user)
    editable = {
        script.project_id
        for script in scripts
        if can_edit(db, user, script.project_id, Role.manager, held=held)
    }

    places = project_script.running_order(db, scripts)
    by_project = {script.project_id: script for script in scripts}
    names = _dataset_names(db, places)

    return ScriptsOverview(
        places=[
            ScriptPlace(
                project_id=place.project_id,
                project_name=place.project_name,
                step=place.step,
                waits_for=place.waits_for,
                in_a_cycle=place.in_a_cycle,
                reads=[names[one] for one in place.reads if one in names],
                writes=[names[one] for one in place.writes if one in names],
                lines=_lines_in(_shown_text(by_project[place.project_id])),
                saved=bool(by_project[place.project_id].text.strip()),
                last_run_at=by_project[place.project_id].last_run_at,
                last_error=by_project[place.project_id].last_error,
                can_edit=place.project_id in editable,
                rank=place.rank,
            )
            for place in places
        ]
    )


def _dataset_names(db: DbSession, places: list[project_script.Place]) -> dict[str, str]:
    """The datasets every script touched, in one query rather than per id."""
    wanted = {one for place in places for one in place.reads + place.writes}
    if not wanted:
        return {}
    rows = db.execute(
        select(Dataset.id, Dataset.name).where(Dataset.id.in_(wanted))
    ).all()
    return {row[0]: row[1] for row in rows}


def _lines_in(text: str) -> int:
    """Commands, not lines in the box.

    The engine's own splitter rather than a count of non-blank lines: it is
    the one that decides what a command is, and it disagrees with counting
    in both directions. A `//` line is a comment and not a command, and a
    line ending `///` is joined to the next, so one command written over
    four lines is one command. A second opinion about that here would show a
    number the log never agrees with.
    """
    return len(stata.commands(text))
