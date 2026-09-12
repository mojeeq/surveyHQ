"""External data connections: CRUD, testing, discovery and sync triggering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from slugify import slugify
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, RequireManager
from app.core.crypto import decrypt, encrypt
from app.core.logging import get_logger
from app.core.rate_limit import enforce
from app.models import Connection, Job, JobStatus, JobType, Role, SyncRun, User
from app.schemas.common import Message
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionOut,
    ConnectionTestResult,
    ConnectionUpdate,
    QuestionnaireOut,
    SyncRequest,
    SyncRunOut,
)
from app.schemas.monitoring import JobOut
from app.services.audit import record
from app.services.external_sources import (
    ExternalSourceClient,
    SourceError,
    SourceResource,
    source_label,
)
from app.services.projects import can_edit, can_view, restrict, scope_for
from app.services.survey_solutions import (
    SurveySolutionsClient,
    SurveySolutionsError,
)

logger = get_logger(__name__)
router = APIRouter()

# Testing a connection makes this server fetch a URL the caller chose. Managers
# are trusted, so this is not a wall - it is what turns "probe every port on the
# internal network" from a script into an afternoon.
TESTS_PER_MINUTE = 10


def _throttle_tests(user: User) -> None:
    enforce(
        f"connection-test:{user.id}",
        TESTS_PER_MINUTE,
        60,
        "Too many connection tests. Wait a minute and try again.",
    )


def _to_out(connection: Connection) -> ConnectionOut:
    out = ConnectionOut.model_validate(connection)
    out.has_password = bool(connection.password_encrypted)
    return out


def _survey_solutions_client(connection: Connection) -> SurveySolutionsClient:
    return SurveySolutionsClient(
        base_url=connection.base_url,
        username=connection.username,
        password=decrypt(connection.password_encrypted),
        workspace=connection.workspace,
        verify_ssl=connection.verify_ssl,
    )


def _external_client(connection: Connection) -> ExternalSourceClient:
    return ExternalSourceClient(
        source_type=connection.source_type,
        base_url=connection.base_url,
        workspace=connection.workspace,
        username=connection.username,
        secret=decrypt(connection.password_encrypted),
        verify_ssl=connection.verify_ssl,
        config=dict(connection.source_config or {}),
    )


def _external_client_from_payload(payload: ConnectionCreate) -> ExternalSourceClient:
    return ExternalSourceClient(
        source_type=payload.source_type,
        base_url=payload.base_url,
        workspace=payload.workspace,
        username=payload.username,
        secret=payload.password,
        verify_ssl=payload.verify_ssl,
        config=dict(payload.source_config or {}),
    )


def _needs_credentials(source_type: str) -> str:
    """What must be present before an authenticated adapter can be used."""
    if source_type == "sdmx":
        return "none"
    if source_type == "kobo":
        return "secret"
    return "both"


def _credentials_ready(
    source_type: str, username: str, has_secret: bool
) -> bool:
    need = _needs_credentials(source_type)
    if need == "none":
        return True
    if need == "secret":
        return has_secret
    return bool(username) and has_secret


def _credential_message(source_type: str) -> str:
    if source_type == "kobo":
        return "Set the Kobo API token before testing or importing."
    if source_type == "sdmx":
        return ""
    return f"Set the {source_label(source_type)} user name and password before testing or importing."


def _get(connection_id: str, db: DbSession, user: User) -> Connection:
    """A connection the caller may reach.

    Every route here takes an id, and a connection is not an innocuous record:
    it names a server, it can be made to import, and its runs can expose raw
    exports. Scoping the listing alone would leave all of that reachable to
    anyone who knew the id.
    """
    connection = db.get(Connection, connection_id)
    if connection is None or not can_view(db, user, connection.project_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


def _editable(connection_id: str, db: DbSession, user: User) -> Connection:
    connection = _get(connection_id, db, user)
    if not can_edit(db, user, connection.project_id, Role.manager):
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


def _resource_out(resource: SourceResource) -> QuestionnaireOut:
    return QuestionnaireOut(
        id=resource.id,
        version=resource.version,
        title=resource.title,
        variable=resource.variable,
        identity=resource.identity,
        last_entry_date=resource.last_entry_date,
        kind=resource.kind,
        meta=resource.meta,
    )


@router.get("", response_model=list[ConnectionOut])
def list_connections(db: DbSession, user: CurrentUser) -> list[ConnectionOut]:
    rows = db.scalars(
        restrict(
            select(Connection), scope_for(db, user).filter(Connection.project_id)
        ).order_by(Connection.created_at.desc())
    ).all()
    return [_to_out(c) for c in rows]


@router.post("", response_model=ConnectionOut, status_code=201)
def create_connection(
    payload: ConnectionCreate, db: DbSession, user: RequireManager
) -> ConnectionOut:
    if payload.project_id and not can_edit(db, user, payload.project_id, Role.manager):
        raise HTTPException(status_code=404, detail="Project not found")
    connection = Connection(
        name=payload.name,
        base_url=payload.base_url,
        source_type=payload.source_type,
        source_config=payload.source_config,
        workspace=payload.workspace or "",
        username=payload.username,
        password_encrypted=encrypt(payload.password) if payload.password else "",
        verify_ssl=payload.verify_ssl,
        sync_enabled=payload.sync_enabled,
        sync_interval_minutes=payload.sync_interval_minutes,
        export_format=payload.export_format,
        questionnaires=payload.questionnaires,
        interview_status=payload.interview_status,
        project_id=payload.project_id,
        sync_mode=payload.sync_mode,
        sync_times=payload.sync_times,
        sync_timezone=payload.sync_timezone,
        created_by=user.id,
    )
    db.add(connection)
    record(
        db,
        user=user,
        action="create_connection",
        entity_type="connection",
        detail={
            "name": payload.name,
            "url": payload.base_url,
            "source_type": payload.source_type,
        },
    )
    db.commit()
    db.refresh(connection)
    return _to_out(connection)


@router.get("/{connection_id}", response_model=ConnectionOut)
def read_connection(connection_id: str, db: DbSession, user: CurrentUser) -> ConnectionOut:
    return _to_out(_get(connection_id, db, user))


@router.patch("/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: str, payload: ConnectionUpdate, db: DbSession, user: RequireManager
) -> ConnectionOut:
    connection = _editable(connection_id, db, user)
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    moving = "project_id" in data and data["project_id"] != connection.project_id
    if moving and data["project_id"] and not can_edit(
        db, user, data["project_id"], Role.manager
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in data.items():
        setattr(connection, field, value)
    if password:
        connection.password_encrypted = encrypt(password)
    record(
        db,
        user=user,
        action="update_connection",
        entity_type="connection",
        entity_id=connection_id,
    )
    db.commit()
    db.refresh(connection)
    return _to_out(connection)


@router.delete("/{connection_id}", response_model=Message)
def delete_connection(connection_id: str, db: DbSession, user: RequireManager) -> Message:
    connection = _editable(connection_id, db, user)
    name = connection.name
    db.delete(connection)
    record(
        db,
        user=user,
        action="delete_connection",
        entity_type="connection",
        entity_id=connection_id,
        detail={"name": name},
    )
    db.commit()
    return Message(detail=f"Connection '{name}' deleted")


@router.post("/{connection_id}/test", response_model=ConnectionTestResult)
def test_connection(
    connection_id: str, db: DbSession, user: RequireManager
) -> ConnectionTestResult:
    connection = _editable(connection_id, db, user)
    _throttle_tests(user)
    if not _credentials_ready(
        connection.source_type,
        connection.username,
        bool(connection.password_encrypted),
    ):
        return ConnectionTestResult(
            ok=False, message=_credential_message(connection.source_type)
        )
    try:
        if connection.source_type == "survey_solutions":
            with _survey_solutions_client(connection) as client:
                info = client.test_connection()
            message = (
                f"Connected to workspace '{info['workspace']}'. "
                f"{info['questionnaire_count']} questionnaire(s) visible."
            )
        else:
            with _external_client(connection) as client:
                info = client.test_connection()
            message = (
                f"Connected to {source_label(connection.source_type)}. "
                f"{info.get('resource_count', 0)} resource(s) visible."
            )
    except (SurveySolutionsError, SourceError, ValueError) as exc:
        connection.last_sync_error = str(exc)
        db.commit()
        return ConnectionTestResult(ok=False, message=str(exc))

    connection.server_info = info
    connection.last_sync_error = ""
    db.commit()
    return ConnectionTestResult(ok=True, message=message, details=info)


@router.post("/test", response_model=ConnectionTestResult)
def test_unsaved_connection(
    payload: ConnectionCreate, user: RequireManager
) -> ConnectionTestResult:
    """Let the UI validate credentials before the connection is saved."""
    _throttle_tests(user)
    if not _credentials_ready(payload.source_type, payload.username, bool(payload.password)):
        return ConnectionTestResult(
            ok=False, message=_credential_message(payload.source_type)
        )
    try:
        if payload.source_type == "survey_solutions":
            with SurveySolutionsClient(
                base_url=payload.base_url,
                username=payload.username,
                password=payload.password,
                workspace=payload.workspace or "primary",
                verify_ssl=payload.verify_ssl,
            ) as client:
                info = client.test_connection()
            message = (
                f"Connected to workspace '{info['workspace']}'. "
                f"{info['questionnaire_count']} questionnaire(s) visible."
            )
        else:
            with _external_client_from_payload(payload) as client:
                info = client.test_connection()
            message = (
                f"Connected to {source_label(payload.source_type)}. "
                f"{info.get('resource_count', 0)} resource(s) visible."
            )
    except (SurveySolutionsError, SourceError, ValueError) as exc:
        return ConnectionTestResult(ok=False, message=str(exc))
    return ConnectionTestResult(ok=True, message=message, details=info)


@router.get("/{connection_id}/resources", response_model=list[QuestionnaireOut])
@router.get("/{connection_id}/questionnaires", response_model=list[QuestionnaireOut])
def list_resources(
    connection_id: str, db: DbSession, user: CurrentUser
) -> list[QuestionnaireOut]:
    """Discover forms/dictionaries/dataflows visible through this connection.

    ``/questionnaires`` remains as an alias so older Survey Solutions clients
    and the existing frontend keep working while the UI moves to generic
    resource language.
    """
    connection = _get(connection_id, db, user)
    try:
        if connection.source_type == "survey_solutions":
            with _survey_solutions_client(connection) as client:
                questionnaires = client.list_questionnaires()
            return [
                QuestionnaireOut(
                    id=q.id,
                    version=q.version,
                    title=q.title,
                    variable=q.variable,
                    identity=q.identity,
                    last_entry_date=q.last_entry_date,
                    kind="questionnaire",
                )
                for q in questionnaires
            ]
        with _external_client(connection) as client:
            return [_resource_out(resource) for resource in client.list_resources()]
    except (SurveySolutionsError, SourceError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{connection_id}/interviews", response_model=dict)
def list_interviews(
    connection_id: str,
    db: DbSession,
    user: CurrentUser,
    questionnaire_id: str = "",
    version: int | None = None,
    status: str = "",
    limit: int = Query(default=200, le=1000),
) -> dict[str, Any]:
    """Live Survey Solutions interview summaries, without exporting."""
    connection = _get(connection_id, db, user)
    if connection.source_type != "survey_solutions":
        raise HTTPException(
            status_code=400,
            detail="Live interview status is currently available for Survey Solutions connections only.",
        )
    try:
        with _survey_solutions_client(connection) as client:
            interviews: list[dict[str, Any]] = []
            for interview in client.iter_interviews(
                questionnaire_id=questionnaire_id or None,
                version=version,
                status=status or None,
            ):
                interviews.append(interview)
                if len(interviews) >= limit:
                    break
    except SurveySolutionsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    by_status: dict[str, int] = {}
    for interview in interviews:
        key = str(interview.get("Status") or "Unknown")
        by_status[key] = by_status.get(key, 0) + 1
    return {"interviews": interviews, "count": len(interviews), "by_status": by_status}


@router.post("/{connection_id}/sync", response_model=JobOut, status_code=202)
def trigger_sync(
    connection_id: str, payload: SyncRequest, db: DbSession, user: RequireManager
) -> Job:
    """Queue an import for the selected remote resources."""
    connection = _editable(connection_id, db, user)
    if not _credentials_ready(
        connection.source_type,
        connection.username,
        bool(connection.password_encrypted),
    ):
        raise HTTPException(
            status_code=400, detail=_credential_message(connection.source_type)
        )
    target_project = payload.project_id or connection.project_id
    if target_project and not can_edit(db, user, target_project, Role.manager):
        raise HTTPException(status_code=404, detail="Project not found")
    resources = payload.questionnaires or connection.questionnaires
    if not resources:
        raise HTTPException(
            status_code=400,
            detail=(
                "Choose at least one remote resource to import, or set a default "
                "resource list on the connection."
            ),
        )

    job = Job(
        job_type=JobType.sync,
        status=JobStatus.queued,
        title=f"Import from {connection.name}",
        params={
            "connection_id": connection.id,
            "questionnaires": resources,
            "interview_status": payload.interview_status or connection.interview_status,
            "project_id": target_project,
            "mode": payload.mode,
        },
        created_by=user.id,
    )
    db.add(job)
    record(
        db,
        user=user,
        action="trigger_sync",
        entity_type="connection",
        entity_id=connection_id,
        detail={"resources": resources, "source_type": connection.source_type},
    )
    db.commit()
    db.refresh(job)

    from app.workers.tasks import run_connection_sync

    try:
        async_result = run_connection_sync.delay(job.id)
        job.celery_task_id = async_result.id
        db.commit()
        db.refresh(job)
    except Exception as exc:  # noqa: BLE001 - broker unreachable
        logger.error("Could not queue sync job %s: %s", job.id, exc)
        job.status = JobStatus.failed
        job.error = (
            "The background worker could not be reached. Check that the worker and "
            "Redis containers are running."
        )
        db.commit()
        db.refresh(job)
    return job


@router.get("/{connection_id}/runs/{run_id}/archive")
def download_sync_archive(
    connection_id: str, run_id: str, db: DbSession, user: CurrentUser
) -> Response:
    """The raw Survey Solutions export zip, where this source produces one."""
    _get(connection_id, db, user)
    run = db.get(SyncRun, run_id)
    if run is None or run.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Sync run not found")
    path = Path(run.archive_path) if run.archive_path else None
    if path is None or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="The export file for this run is no longer on the server.",
        )
    stem = slugify(run.questionnaire or "export") or "export"
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{stem}-{run.started_at:%Y%m%d-%H%M}.zip",
    )


@router.get("/{connection_id}/runs", response_model=list[SyncRunOut])
def list_sync_runs(
    connection_id: str, db: DbSession, user: CurrentUser, limit: int = 20
) -> list[SyncRunOut]:
    _get(connection_id, db, user)
    runs = db.scalars(
        select(SyncRun)
        .where(SyncRun.connection_id == connection_id)
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
    ).all()
    out: list[SyncRunOut] = []
    for run in runs:
        item = SyncRunOut.model_validate(run)
        item.has_archive = bool(run.archive_path) and Path(run.archive_path).is_file()
        out.append(item)
    return out
