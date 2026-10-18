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

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Dataset, ProjectScript, Role
from app.schemas.script import ScriptPlace, ScriptsOverview
from app.services import project_script, stata
from app.services.projects import can_edit, visible_projects

router = APIRouter()


@router.get("", response_model=ScriptsOverview)
def overview(db: DbSession, user: CurrentUser) -> ScriptsOverview:
    """Every script this user can see, in the order they have to run."""
    allowed = {project.id for project in visible_projects(db, user)}
    # Seeing a script and being able to change it are different questions, and
    # the page asks both: it offers an editor, and the editor is the project's,
    # which takes the manager role over that project.
    editable = {
        project_id
        for project_id in allowed
        if can_edit(db, user, project_id, Role.manager)
    }
    # A row is made for a project the first time anybody opens its script tab,
    # so most of them are empty and are not scripts. One that has run is,
    # whatever it holds now: running is deliberately separate from saving -
    # a script is tried before it is kept - so text can be empty while the
    # reads and writes of a real run are recorded against it.
    scripts = [
        script
        for script in db.scalars(select(ProjectScript)).all()
        if script.project_id in allowed
        and (script.text.strip() or script.last_run_at is not None)
    ]

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
                lines=_lines_in(by_project[place.project_id].text),
                last_run_at=by_project[place.project_id].last_run_at,
                last_error=by_project[place.project_id].last_error,
                can_edit=place.project_id in editable,
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
