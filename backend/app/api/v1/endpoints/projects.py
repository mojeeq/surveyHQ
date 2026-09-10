"""Projects: grouping data and dashboards, and deciding who may reach them."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from slugify import slugify
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DbSession, RequireManager
from app.models import (
    AlertRule,
    Chart,
    Connection,
    Dashboard,
    Dataset,
    DatasetRelationship,
    Indicator,
    Project,
    ProjectMember,
    ProjectScript,
    QualityRule,
    Role,
    SavedQuery,
    User,
)
from app.schemas.common import Message
from app.schemas.project import (
    AssignProjectIn,
    ProjectDetail,
    ProjectIn,
    ProjectMemberIn,
    ProjectMemberOut,
    ProjectOut,
    ProjectScriptIn,
    ProjectScriptOut,
    ProjectScriptPatch,
    ProjectUpdate,
    RunScriptIn,
)
from app.services import rproject
from app.services.audit import record
from app.services.dashboard_assets import remove_all
from app.services.datasets import delete_dataset_files
from app.services.projects import (
    can_edit,
    effective_role,
    scope_for,
    visible_projects,
)

router = APIRouter()


@router.get("", response_model=list[ProjectOut])
def list_projects(db: DbSession, user: CurrentUser) -> list[ProjectOut]:
    """Only the projects this user may reach; there is no full list for others."""
    projects = visible_projects(db, user)
    return [_to_out(project, db, user) for project in projects]


@router.post("", response_model=ProjectDetail, status_code=201)
def create_project(payload: ProjectIn, db: DbSession, user: RequireManager) -> ProjectDetail:
    project = Project(
        name=payload.name.strip(),
        slug=_unique_slug(db, payload.name),
        description=payload.description,
        status=payload.status,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        created_by=user.id,
    )
    db.add(project)
    db.flush()
    # Without this the creator would immediately lose sight of what they made,
    # since a non-admin only sees projects they belong to.
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=Role.manager))
    db.commit()
    db.refresh(project)
    record(
        db,
        user=user,
        action="project.create",
        entity_type="project",
        entity_id=project.id,
        detail={"name": project.name})
    return _to_detail(project, db, user)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, db: DbSession, user: CurrentUser) -> ProjectDetail:
    return _to_detail(_visible_project(project_id, db, user), db, user)


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: str, payload: ProjectUpdate, db: DbSession, user: CurrentUser
) -> ProjectDetail:
    project = _editable_project(project_id, db, user, Role.manager)
    fields = payload.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(project, key, value)
    if "name" in fields:
        project.name = project.name.strip()
    db.commit()
    db.refresh(project)
    record(
        db,
        user=user,
        action="project.update",
        entity_type="project",
        entity_id=project.id,
        detail={key: str(value) for key, value in fields.items()},
    )
    return _to_detail(project, db, user)


@router.delete("/{project_id}", response_model=Message)
def delete_project(
    project_id: str,
    db: DbSession,
    user: CurrentUser,
    contents: Literal["release", "delete"] = "release",
) -> Message:
    """Delete the project, and either release its contents or destroy them.

    Releasing is the old behaviour and stays the default: a project is an
    organising idea, and dissolving one need not throw away the data organised
    by it. But a round that is finished with is finished with, and moving eight
    datasets to the shared area to delete them one at a time is not tidying up
    - so contents="delete" takes the lot.

    What "the lot" means: the project's datasets and their stored files, and
    everything hanging off them - charts, indicators and their history, quality
    rules and results, alert rules and the alerts they raised, relationships,
    and any dataset merged out of them - plus its dashboards and their widgets.
    Connections are released rather than deleted: a connection is a server and
    a set of credentials, which outlive the project pointed at it.
    """
    project = _editable_project(project_id, db, user, Role.manager)
    name = project.name

    if contents == "delete":
        # Deleted through the ORM rather than by statement, so the cascades
        # declared on the relationships run and nothing is left orphaned.
        datasets = list(db.scalars(select(Dataset).where(Dataset.project_id == project_id)))
        dashboards = list(
            db.scalars(select(Dashboard).where(Dashboard.project_id == project_id))
        )
        relationships = list(
            db.scalars(
                select(DatasetRelationship).where(
                    DatasetRelationship.project_id == project_id
                )
            )
        )
        for relationship in relationships:
            db.delete(relationship)
        for dashboard in dashboards:
            remove_all(dashboard.id)
            db.delete(dashboard)

        # Everything hanging off those datasets, deleted by name rather than
        # left to ON DELETE CASCADE. The constraint is real on PostgreSQL and
        # silently absent on SQLite, which does not enforce foreign keys unless
        # asked - so relying on it makes the same delete behave differently on
        # the two databases this runs on.
        ids = [dataset.id for dataset in datasets]
        if ids:
            indicators = list(
                db.scalars(select(Indicator).where(Indicator.dataset_id.in_(ids)))
            )
            for indicator in indicators:
                db.delete(indicator)  # its snapshots go with it
            rules = list(
                db.scalars(select(AlertRule).where(AlertRule.dataset_id.in_(ids)))
            )
            for rule in rules:
                db.delete(rule)  # and the alerts it raised
            for quality_rule in db.scalars(
                select(QualityRule).where(QualityRule.dataset_id.in_(ids))
            ):
                db.delete(quality_rule)
            for chart in db.scalars(select(Chart).where(Chart.dataset_id.in_(ids))):
                db.delete(chart)
            for query in db.scalars(select(SavedQuery).where(SavedQuery.dataset_id.in_(ids))):
                db.delete(query)
            db.flush()

        for dataset in datasets:
            delete_dataset_files(dataset)
            db.delete(dataset)
        removed = {
            "datasets": len(datasets),
            "dashboards": len(dashboards),
            "relationships": len(relationships),
        }
        summary = (
            f"Project '{name}' deleted, with {removed['datasets']} dataset(s), "
            f"{removed['dashboards']} dashboard(s) and everything built on them"
        )
    else:
        removed = {}
        summary = f"Project '{name}' deleted; its data moved to the shared area"

    # Released here rather than by ON DELETE SET NULL. On a database upgraded in
    # place the project_id column is added by ALTER TABLE, which carries no
    # foreign key, so the constraint would not fire and the rows would be left
    # pointing at a project that no longer exists - visible to nobody but an
    # administrator. Doing it explicitly works the same either way.
    for model in (Dataset, Dashboard, DatasetRelationship, Connection):
        db.execute(
            update(model).where(model.project_id == project_id).values(project_id=None)
        )
    db.delete(project)
    db.commit()
    record(
        db,
        user=user,
        action="project.delete",
        entity_type="project",
        entity_id=project_id,
        detail={"name": name, "contents": contents, **removed},
    )
    return Message(detail=summary)


# --- membership -------------------------------------------------------------


@router.get("/{project_id}/members", response_model=list[ProjectMemberOut])
def list_members(project_id: str, db: DbSession, user: CurrentUser) -> list[ProjectMemberOut]:
    _visible_project(project_id, db, user)
    return _members(project_id, db)


@router.put("/{project_id}/members", response_model=ProjectMemberOut)
def upsert_member(
    project_id: str, payload: ProjectMemberIn, db: DbSession, user: CurrentUser
) -> ProjectMemberOut:
    """Add a member, or change the role of one already there."""
    _editable_project(project_id, db, user, Role.manager)
    member_user = db.get(User, payload.user_id)
    if member_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == payload.user_id,
        )
    )
    if membership is None:
        membership = ProjectMember(project_id=project_id, user_id=payload.user_id)
        db.add(membership)
    membership.role = payload.role
    db.commit()
    db.refresh(membership)
    record(
        db,
        user=user,
        action="project.member.set",
        entity_type="project",
        entity_id=project_id,
        detail={"user_id": payload.user_id, "role": payload.role.value},
    )
    return ProjectMemberOut(
        id=membership.id,
        user_id=member_user.id,
        role=membership.role,
        email=member_user.email,
        full_name=member_user.full_name,
    )


@router.delete("/{project_id}/members/{user_id}", response_model=Message)
def remove_member(
    project_id: str, user_id: str, db: DbSession, user: CurrentUser
) -> Message:
    _editable_project(project_id, db, user, Role.manager)
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="That user is not a member")
    db.delete(membership)
    db.commit()
    record(
        db,
        user=user,
        action="project.member.remove",
        entity_type="project",
        entity_id=project_id,
        detail={"user_id": user_id}
    )
    return Message(detail="Member removed")


# --- assigning resources ----------------------------------------------------


# --- the project's R workspace ---------------------------------------------
#
# R runs against the project rather than against one dataset: a recode reads
# the household file and writes the person file, and pinning it to either was
# always a fiction. The working directory survives between runs, so a project
# is an environment - see services/rproject.py.


@router.get("/{project_id}/tools", response_model=dict)
def project_tools(project_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Whether R can be run here, and what there is to run it against.

    Asked before the console is drawn, so a server without R does not offer a
    box that can only fail. The reason travels with the answer: "install R" and
    "switch it on" are different jobs for different people.
    """
    _visible_project(project_id, db, user)
    reason = rproject.unavailable_reason()
    return {
        "r": {"enabled": not reason, "reason": reason},
        "datasets": [
            {"name": dataset.name, "slug": dataset.slug, "rows": dataset.row_count or 0}
            for dataset in rproject.project_datasets(db, project_id)
        ],
    }


@router.get("/{project_id}/scripts", response_model=list[ProjectScriptOut])
def list_scripts(
    project_id: str, db: DbSession, user: CurrentUser
) -> list[ProjectScript]:
    _visible_project(project_id, db, user)
    return list(
        db.scalars(
            select(ProjectScript)
            .where(ProjectScript.project_id == project_id)
            .order_by(ProjectScript.display_order, ProjectScript.name)
        ).all()
    )


@router.post(
    "/{project_id}/scripts", response_model=ProjectScriptOut, status_code=201
)
def create_script(
    project_id: str, payload: ProjectScriptIn, db: DbSession, user: RequireManager
) -> ProjectScript:
    project = _editable_project(project_id, db, user, Role.manager)
    highest = db.scalar(
        select(func.max(ProjectScript.display_order)).where(
            ProjectScript.project_id == project.id
        )
    )
    script = ProjectScript(
        project_id=project.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        code=payload.code,
        run_on_import=payload.run_on_import,
        display_order=(highest or 0) + 1,
        created_by=user.id,
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    return script


@router.patch(
    "/{project_id}/scripts/{script_id}", response_model=ProjectScriptOut
)
def update_script(
    project_id: str,
    script_id: str,
    payload: ProjectScriptPatch,
    db: DbSession,
    user: RequireManager,
) -> ProjectScript:
    project = _editable_project(project_id, db, user, Role.manager)
    script = _project_script(db, project, script_id)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"]:
        script.name = changes["name"].strip()
    if "description" in changes:
        script.description = (changes["description"] or "").strip()
    if "code" in changes:
        script.code = changes["code"] or ""
    if "run_on_import" in changes:
        script.run_on_import = bool(changes["run_on_import"])
    if "display_order" in changes and changes["display_order"] is not None:
        script.display_order = int(changes["display_order"])
    db.commit()
    db.refresh(script)
    return script


@router.delete("/{project_id}/scripts/{script_id}", response_model=Message)
def delete_script(
    project_id: str, script_id: str, db: DbSession, user: RequireManager
) -> Message:
    project = _editable_project(project_id, db, user, Role.manager)
    script = _project_script(db, project, script_id)
    name = script.name
    db.delete(script)
    db.commit()
    return Message(detail=f"'{name}' deleted. What it already wrote stays.")


@router.post("/{project_id}/scripts/{script_id}/run", response_model=dict)
def run_saved_script(
    project_id: str, script_id: str, db: DbSession, user: RequireManager
) -> dict[str, Any]:
    project = _editable_project(project_id, db, user, Role.manager)
    script = _project_script(db, project, script_id)
    try:
        result = rproject.run_saved(db, project, script, user.id)
    except rproject.RError as exc:
        # The failure is recorded on the script before it is raised, so the
        # panel can show what went wrong without running it again.
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record(
        db,
        user=user,
        action="project.run_script",
        entity_type="project",
        entity_id=project.id,
        detail={"script": script.name, "wrote": [w["name"] for w in result.written]},
    )
    db.commit()
    return _run_payload(result)


@router.post("/{project_id}/run", response_model=dict)
def run_console(
    project_id: str, payload: RunScriptIn, db: DbSession, user: RequireManager
) -> dict[str, Any]:
    """Run code that is not saved, the way a console is used.

    Saved or not, it runs in the same workspace and can write datasets, so it
    is recorded in the audit trail in full: this is arbitrary code changing a
    project's data.
    """
    project = _editable_project(project_id, db, user, Role.manager)
    try:
        result = rproject.run(db, project, payload.code, created_by=user.id)
    except rproject.RError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record(
        db,
        user=user,
        action="project.run_console",
        entity_type="project",
        entity_id=project.id,
        detail={"code": payload.code[:10000]},
    )
    db.commit()
    return _run_payload(result)


@router.get("/{project_id}/workspace", response_model=dict)
def list_workspace(
    project_id: str, db: DbSession, user: RequireManager
) -> dict[str, Any]:
    """What is in the project's working directory, which survives between runs."""
    project = _editable_project(project_id, db, user, Role.manager)
    room = rproject.workspace(project.id)
    files = []
    for path in sorted(room.rglob("*")):
        relative = path.relative_to(room)
        if not path.is_file() or rproject.is_plumbing(relative):
            continue
        files.append({"path": str(relative), "bytes": path.stat().st_size})
        if len(files) >= 200:
            break
    return {"files": files}


@router.delete("/{project_id}/workspace", response_model=Message)
def clear_workspace(
    project_id: str, db: DbSession, user: RequireManager
) -> Message:
    """Empty the working directory, packages and saved objects included.

    The datasets are not touched: they live in the platform, and the workspace
    is only the scratch space around them.
    """
    project = _editable_project(project_id, db, user, Role.manager)
    rproject.forget(project.id)
    return Message(detail="The workspace is empty. The project's datasets are untouched.")


def _project_script(db: DbSession, project: Project, script_id: str) -> ProjectScript:
    script = db.get(ProjectScript, script_id)
    if script is None or script.project_id != project.id:
        raise HTTPException(status_code=404, detail="Script not found")
    return script


def _run_payload(result: rproject.ProjectRResult) -> dict[str, Any]:
    return {
        "message": result.message,
        "output": result.output,
        "written": result.written,
        "files": result.files,
    }


@router.put("/assign/dataset/{dataset_id}", response_model=Message)
def assign_dataset(
    dataset_id: str, payload: AssignProjectIn, db: DbSession, user: CurrentUser
) -> Message:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    _check_move(db, user, dataset.project_id, payload.project_id)
    dataset.project_id = payload.project_id
    db.commit()
    record(
        db,
        user=user,
        action="project.assign",
        entity_type="dataset",
        entity_id=dataset_id,
        detail={"project_id": payload.project_id},
    )
    return Message(detail=_moved(payload.project_id, db))


@router.put("/assign/dashboard/{dashboard_id}", response_model=Message)
def assign_dashboard(
    dashboard_id: str, payload: AssignProjectIn, db: DbSession, user: CurrentUser
) -> Message:
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _check_move(db, user, dashboard.project_id, payload.project_id)
    dashboard.project_id = payload.project_id
    db.commit()
    record(
        db,
        user=user,
        action="project.assign",
        entity_type="dashboard",
        entity_id=dashboard_id,
        detail={"project_id": payload.project_id},
    )
    return Message(detail=_moved(payload.project_id, db))


# --- helpers ----------------------------------------------------------------


def _unique_slug(db: DbSession, name: str) -> str:
    base = slugify(name)[:180] or "project"
    candidate = base
    suffix = 2
    while db.scalar(select(Project).where(Project.slug == candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _visible_project(project_id: str, db: DbSession, user: User) -> Project:
    project = db.get(Project, project_id)
    # A project the caller may not see is reported as missing, not forbidden:
    # a 403 would confirm it exists and leak the project list.
    if project is None or not scope_for(db, user).allows(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _editable_project(
    project_id: str, db: DbSession, user: User, minimum: Role
) -> Project:
    project = _visible_project(project_id, db, user)
    if not can_edit(db, user, project_id, minimum):
        raise HTTPException(
            status_code=403,
            detail=f"This action requires the '{minimum.value}' role on this project",
        )
    return project


def _check_move(
    db: DbSession, user: User, current: str | None, target: str | None
) -> None:
    """Moving needs manager rights on both sides.

    Requiring it on the source too stops a project manager from pulling a
    dataset out of a project they have no say over.
    """
    for project_id in {current, target}:
        if project_id is not None and not scope_for(db, user).allows(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        if not can_edit(db, user, project_id, Role.manager):
            raise HTTPException(
                status_code=403,
                detail="Moving this needs the 'manager' role on both projects",
            )


def _moved(project_id: str | None, db: DbSession) -> str:
    if project_id is None:
        return "Moved to the shared area"
    project = db.get(Project, project_id)
    return f"Moved to '{project.name}'" if project else "Moved"


def _members(project_id: str, db: DbSession) -> list[ProjectMemberOut]:
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.email)
    ).all()
    return [
        ProjectMemberOut(
            id=membership.id,
            user_id=member.id,
            role=membership.role,
            email=member.email,
            full_name=member.full_name,
        )
        for membership, member in rows
    ]


def _counts(project_id: str, db: DbSession) -> tuple[int, int, int]:
    def count(model, column) -> int:
        return db.scalar(select(func.count()).select_from(model).where(column == project_id)) or 0

    return (
        count(Dataset, Dataset.project_id),
        count(Dashboard, Dashboard.project_id),
        count(ProjectMember, ProjectMember.project_id),
    )


def _to_out(project: Project, db: DbSession, user: User) -> ProjectOut:
    datasets, dashboards, members = _counts(project.id, db)
    return ProjectOut(
        **{
            field: getattr(project, field)
            for field in (
                "id", "name", "slug", "description", "status",
                "starts_on", "ends_on", "created_at", "updated_at",
            )
        },
        dataset_count=datasets,
        dashboard_count=dashboards,
        member_count=members,
        your_role=effective_role(db, user, project.id),
    )


def _to_detail(project: Project, db: DbSession, user: User) -> ProjectDetail:
    return ProjectDetail(
        **_to_out(project, db, user).model_dump(),
        members=_members(project.id, db),
    )
