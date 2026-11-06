"""Every script, and the order they have to run in.

A script belongs to a project, and a project can have several: clean the
roster, build the household file, make the tables. A survey office runs more
than one project too, and the scripts are not independent of each other - one
writes a cleaned person file that another reads to build an indicator table.
Nothing on any single project's page can show that, because the relationship
runs between scripts wherever they live.

So there is one page that shows all of them, with the order read off what
each run actually opened and saved, and it is where they are written too: the
list down its side comes from here, and so does the editor beside it, which
reads, saves, renames, runs and deletes one script at a time by its id. Each
entry says whether this reader may change it, because the page lists every
script they can see and the editor opens read-only on the rest.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Dataset, Project, ProjectScript, Role, User
from app.schemas.common import Message
from app.schemas.project import ScriptOut, ScriptRunIn
from app.schemas.script import (
    ScriptCreateIn,
    ScriptOrderIn,
    ScriptPatchIn,
    ScriptPlace,
    ScriptsOverview,
)
from app.services import archive as archiving
from app.services import project_script, script_language, stata
from app.services.audit import record
from app.services.project_script import running_order
from app.services.projects import can_edit, memberships, scope_for, visible_projects
from app.services.stata import CommandError

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
    """The scripts this reader can see.

    Every row is a script now. A row used to be made for a project the first
    time anybody opened its script tab, so most were empty and were filtered
    out here; a script is made by being started now, under a name, and an
    empty one somebody started is a script they are about to write.

    One definition because two things ask: the page, and the reorder that
    wants to know what a step contains. Asked separately they disagreed, and
    "the whole step" meant more scripts than the page had ever shown.
    """
    allowed = {project.id for project in visible_projects(db, user)}
    return [
        script
        for script in db.scalars(select(ProjectScript)).all()
        if script.project_id in allowed
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
    wanted = list(dict.fromkeys(payload.script_ids))
    if len(wanted) < 2:
        raise HTTPException(
            status_code=422, detail="Give the whole step, in the order you want it"
        )

    scripts = {script.id: script for script in _scripts_for(db, user)}
    missing = [one for one in wanted if one not in scripts]
    if missing:
        # 404 rather than 403, as everywhere else: a project someone cannot
        # see should not be confirmed to exist by the error.
        raise HTTPException(status_code=404, detail="No such script")

    places = {
        place.script_id: place
        for place in running_order(db, list(scripts.values()))
    }
    steps = {places[one].step for one in wanted}
    tangled = [one for one in wanted if places[one].in_a_cycle]
    if tangled:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{places[tangled[0]].label}' is in a ring with another "
                "script - each reads what the other writes, so there is no order "
                "to choose."
            ),
        )
    if len(steps) > 1:
        later = max(wanted, key=lambda one: places[one].step)
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{places[later].label}' waits for "
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
    for script_id in wanted:
        if not can_edit(db, user, scripts[script_id].project_id, Role.manager, held=held):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Changing the order needs the manager role on "
                    f"'{places[script_id].project_name}'."
                ),
            )

    for rank, script_id in enumerate(wanted):
        scripts[script_id].run_rank = rank
    db.commit()
    return overview(db, user)


@router.get("/language", response_model=dict)
def language(user: CurrentUser) -> dict:
    """What the script language understands, for the editor to colour and
    offer. Read off the engine's own tables; see `script_language`."""
    return script_language.language()


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
        project_id
        for project_id in {script.project_id for script in scripts}
        if can_edit(db, user, project_id, Role.manager, held=held)
    }

    places = project_script.running_order(db, scripts)
    by_id = {script.id: script for script in scripts}
    names = _dataset_names(db, places)

    return ScriptsOverview(
        places=[
            ScriptPlace(
                script_id=place.script_id,
                name=place.script_name,
                label=place.label,
                project_id=place.project_id,
                project_name=place.project_name,
                step=place.step,
                waits_for=place.waits_for,
                in_a_cycle=place.in_a_cycle,
                reads=[names[one] for one in place.reads if one in names],
                writes=[names[one] for one in place.writes if one in names],
                lines=_lines_in(_shown_text(by_id[place.script_id])),
                saved=bool(by_id[place.script_id].text.strip()),
                text_kept=bool(_shown_text(by_id[place.script_id]).strip()),
                last_run_at=by_id[place.script_id].last_run_at,
                last_error=by_id[place.script_id].last_error,
                can_edit=place.project_id in editable,
                rank=place.rank,
                created_at=by_id[place.script_id].created_at,
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


# --- one script ---------------------------------------------------------------
#
# After the routes above, so `/language` and `/order` are never read as the id
# of a script.


def _visible_script(db: DbSession, user: User, script_id: str) -> tuple[ProjectScript, Project]:
    """The script, if this reader can see its project; otherwise a 404.

    Missing rather than forbidden, as everywhere else: a 403 would confirm that
    a script exists in a project somebody cannot see.
    """
    script = db.get(ProjectScript, script_id)
    project = db.get(Project, script.project_id) if script is not None else None
    if script is None or project is None or not scope_for(db, user).allows(project.id):
        raise HTTPException(status_code=404, detail="Script not found")
    return script, project


def _editable_script(
    db: DbSession, user: User, script_id: str
) -> tuple[ProjectScript, Project]:
    """The script, if this reader may change it.

    The manager role on its project, not merely the global one. A script writes
    the project's datasets - and may rebuild an output that moved into another
    project - so being able to see a project has never been grounds for
    rewriting its data.
    """
    script, project = _visible_script(db, user, script_id)
    if not can_edit(db, user, project.id, Role.manager):
        raise HTTPException(
            status_code=403,
            detail="Changing a script needs the 'manager' role on its project",
        )
    return script, project


def _editable_project(db: DbSession, user: User, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or not scope_for(db, user).allows(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_edit(db, user, project_id, Role.manager):
        raise HTTPException(
            status_code=403,
            detail="Starting a script needs the 'manager' role on the project",
        )
    return project


@router.post("", response_model=ScriptOut, status_code=201)
def create_script(payload: ScriptCreateIn, db: DbSession, user: CurrentUser) -> ScriptOut:
    """Start a script in a project, under a name.

    With no name it is called what the project has not used yet: "Main
    script", then "Main script 2". A name the project already has, in any case,
    is refused - two scripts called "Clean" in one list would be told apart by
    nothing.
    """
    project = _editable_project(db, user, payload.project_id)
    try:
        name = payload.name.strip() or project_script.free_name(db, project.id)
        script = project_script.create(db, project.id, name, payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    script.updated_by = user.id
    record(
        db,
        user=user,
        action="create_project_script",
        entity_type="project",
        entity_id=project.id,
        detail={"script_id": script.id, "name": script.name},
    )
    db.commit()
    return script_out(db, script, project)


@router.get("/{script_id}", response_model=ScriptOut)
def read_one(script_id: str, db: DbSession, user: CurrentUser) -> ScriptOut:
    """One script, and how its last run went."""
    script, project = _visible_script(db, user, script_id)
    return script_out(db, script, project)


@router.patch("/{script_id}", response_model=ScriptOut)
def change_one(
    script_id: str, payload: ScriptPatchIn, db: DbSession, user: CurrentUser
) -> ScriptOut:
    """Rename a script, keep new text without running it, or both.

    Saving and running are separate on purpose: a script half-written at the
    end of the day should survive being closed, and running it then would
    build half of something.
    """
    script, project = _editable_script(db, user, script_id)
    if payload.name is not None:
        try:
            name = project_script.clean_name(payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if project_script.name_taken(db, project.id, name, but=script.id):
            raise HTTPException(
                status_code=422,
                detail=f"This project already has a script called '{name}'",
            )
        script.name = name
    if payload.text is not None:
        script.text = payload.text
    script.updated_by = user.id
    db.commit()
    return script_out(db, script, project)


@router.delete("/{script_id}", response_model=Message)
def delete_one(script_id: str, db: DbSession, user: CurrentUser) -> Message:
    """Throw a script away, and what its last run recorded with it.

    The data is not touched. A script is a recipe, and deleting the recipe
    does not unmake what it cooked - the datasets it wrote stay exactly as
    they are, and nothing it built is rebuilt or removed.

    What does go is its claim: a script that no longer exists has not built
    anything, so a re-run chain standing on it stops standing on it, and
    moving one of its datasets elsewhere records no permission for it.
    """
    script, project = _editable_script(db, user, script_id)
    name = script.name
    db.delete(script)
    record(
        db,
        user=user,
        action="delete_project_script",
        entity_type="project",
        entity_id=project.id,
        detail={"script_id": script_id, "name": name},
    )
    db.commit()
    return Message(detail=f"'{name}' deleted. The datasets it wrote are untouched.")


@router.post("/{script_id}/run", response_model=dict)
def run_one(
    script_id: str, payload: ScriptRunIn, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Run a script and report what it did, line by line."""
    script, project = _editable_script(db, user, script_id)
    return run_now(db, user, project, script, payload.text)


def run_now(
    db: DbSession, user: User, project: Project, script: ProjectScript, text: str | None
) -> dict[str, Any]:
    """Run one script and say what it did. Shared with the one-script endpoint.

    A line that fails stops the run and the response says which and why.
    Whatever it saved before that point is saved, as in a do-file: the work is
    not unwound, so a script fixed at line nine does not redo lines one to
    eight.
    """
    try:
        archiving.refuse_if_archived(project, "running its script")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    before = script.text
    try:
        outcome = project_script.run(db, script, text)
    except stata.ScriptError as exc:
        # Committed rather than rolled back: what ran, ran.
        db.commit()
        raise HTTPException(
            status_code=422,
            detail=str(exc),
            headers={"X-Script-Line": str(exc.line_number)},
        ) from exc
    except CommandError as exc:
        # Committed, like the branch above. Nothing ran - the script has no
        # command in it, or its first word is not one - so there is no data to
        # unwind, and the one thing worth keeping is the text somebody typed.
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    kept = script.text != before
    if kept:
        script.updated_by = user.id
    record(
        db,
        user=user,
        action="run_project_script",
        entity_type="project",
        entity_id=project.id,
        detail={
            "script_id": script.id,
            "name": script.name,
            "saved": [entry.name for entry in outcome.saved],
            "kept": kept,
        },
    )
    db.commit()
    return {
        # Whether the run's text is now the saved script, so the editor can
        # move its marker without being sent the text back.
        "kept": kept,
        "log": [
            {"command": step.command, "message": step.message}
            for step in outcome.results
        ],
        "saved": [
            {"id": entry.dataset_id, "name": entry.name,
             "created": entry.created, "rows": entry.rows}
            for entry in outcome.saved
        ],
    }


def script_out(db: DbSession, script: ProjectScript, project: Project | None = None) -> ScriptOut:
    """A script as the editor reads it."""

    def named(ids: list[str]) -> list[str]:
        found = [db.get(Dataset, one) for one in ids or []]
        return [one.name for one in found if one is not None]

    if project is None:
        project = db.get(Project, script.project_id)
    ran = script.last_run_text or ""
    # Stripped on both sides: a box of spaces is not a script, and a run of
    # spaces is not worth offering back.
    return ScriptOut(
        id=script.id,
        name=script.name,
        project_id=script.project_id,
        project_name=project.name if project is not None else "",
        text=script.text,
        # Only when it is news. A run of the saved script makes the two the
        # same, and offering to restore what is already there would be noise
        # on every script that works the ordinary way.
        unsaved_run="" if ran.strip() == script.text.strip() else ran,
        reads=named(script.reads),
        writes=named(script.writes),
        last_run_at=script.last_run_at,
        last_error=script.last_error,
        previous_text=(
            ""
            if (script.previous_text or "").strip() == script.text.strip()
            else script.previous_text or ""
        ),
    )
