"""External data-source connections: CRUD, discovery, testing and sync triggering."""

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
from app.services.projects import can_edit, can_view, restrict, scope_for
from app.services.source_connectors import (
    PROVIDER_LABELS,
    SourceConnectorError,
    make_connector,
)
from app.services.survey_solutions import SurveySolutionsClient, SurveySolutionsError

logger = get_logger(__name__)
router = APIRouter()

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


def _provider(connection: Connection) -> str:
    return connection.provider or "survey_solutions"


def _secret(connection: Connection) -> str:
    return decrypt(connection.password_encrypted) if connection.password_encrypted else ""


def _connector(connection: Connection):
    return make_connector(
        provider=_provider(connection),
        base_url=connection.base_url,
        username=connection.username,
        secret=_secret(connection),
        workspace=connection.workspace,
        verify_ssl=connection.verify_ssl,
        source_config=dict(connection.source_config or {}),
    )


def _saved_credentials_problem(connection: Connection) -> str:
    provider = _provider(connection)
    if provider == "sdmx":
        return ""
    if provider == "kobotoolbox":
        return (
            "Set an API token before testing or importing."
            if not connection.password_encrypted
            else ""
        )
    if not connection.username or not connection.password_encrypted:
        return "Set a user name and password before testing or importing."
    return ""


def _payload_credentials_problem(payload: ConnectionCreate) -> str:
    if payload.provider == "sdmx":
        return ""
    if payload.provider == "kobotoolbox":
        return "Set the Kobo API token before testing." if not payload.password else ""
    if not payload.username or not payload.password:
        return "Set a user name and password before testing."
    return ""


def _get(connection_id: str, db: DbSession, user: User) -> Connection:
    """A connection the caller may reach."""
    connection = db.get(Connection, connection_id)
    if connection is None or not can_view(db, user, connection.project_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


def _editable(connection_id: str, db: DbSession, user: User) -> Connection:
    connection = _get(connection_id, db, user)
    if not can_edit(db, user, connection.project_id, Role.manager):
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


def _test_message(provider: str, info: dict[str, Any]) -> str:
    label = PROVIDER_LABELS.get(provider, provider)
    count = int(info.get("resource_count") or info.get("questionnaire_count") or 0)
    noun = "resource" if count == 1 else "resources"
    suffix = ""
    if provider == "sdmx" and not info.get("configured", True):
        suffix = " Add one or more SDMX data queries before importing."
    return f"Connected to {label}. {count} importable {noun} configured/visible.{suffix}"


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
        provider=payload.provider,
        source_config=payload.source_config,
        workspace=payload.workspace or "primary",
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
            "provider": payload.provider,
        },
    )
    db.commit()
    db.refresh(connection)
    return _to_out(connection)


@router.get("/{connection_id}", response_model=ConnectionOut)
def read_connection(
    connection_id: str, db: DbSession, user: CurrentUser
) -> ConnectionOut:
    return _to_out(_get(connection_id, db, user))


@router.patch("/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: str,
    payload: ConnectionUpdate,
    db: DbSession,
    user: RequireManager,
) -> ConnectionOut:
    connection = _editable(connection_id, db, user)
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    moving = "project_id" in data and data["project_id"] != connection.project_id
    if moving and not can_edit(db, user, data["project_id"], Role.manager):
        raise HTTPException(status_code=404, detail="Project not found")
    provider_changed = "provider" in data and data["provider"] != _provider(connection)
    for field, value in data.items():
        setattr(connection, field, value)
    if password:
        connection.password_encrypted = encrypt(password)
    if provider_changed:
        # A form id on one platform has no meaning on another.
        connection.questionnaires = []
        connection.server_info = {}
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
def delete_connection(
    connection_id: str, db: DbSession, user: RequireManager
) -> Message:
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
    if problem := _saved_credentials_problem(connection):
        return ConnectionTestResult(ok=False, message=problem)
    try:
        with _connector(connection) as source:
            info = source.test_connection()
    except (SourceConnectorError, ValueError) as exc:
        connection.last_sync_error = str(exc)
        db.commit()
        return ConnectionTestResult(ok=False, message=str(exc))

    connection.server_info = info
    connection.last_sync_error = ""
    db.commit()
    return ConnectionTestResult(
        ok=True,
        message=_test_message(_provider(connection), info),
        details=info,
    )


@router.post("/test", response_model=ConnectionTestResult)
def test_unsaved_connection(
    payload: ConnectionCreate, user: RequireManager
) -> ConnectionTestResult:
    """Let the UI validate credentials before the connection is saved."""
    _throttle_tests(user)
    if problem := _payload_credentials_problem(payload):
        return ConnectionTestResult(ok=False, message=problem)
    try:
        with make_connector(
            provider=payload.provider,
            base_url=payload.base_url,
            username=payload.username,
            secret=payload.password,
            workspace=payload.workspace or "primary",
            verify_ssl=payload.verify_ssl,
            source_config=payload.source_config,
        ) as source:
            info = source.test_connection()
    except (SourceConnectorError, ValueError) as exc:
        return ConnectionTestResult(ok=False, message=str(exc))
    return ConnectionTestResult(
        ok=True,
        message=_test_message(payload.provider, info),
        details=info,
    )


def _resource_rows(connection: Connection) -> list[QuestionnaireOut]:
    try:
        with _connector(connection) as source:
            resources = source.list_resources()
    except SourceConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [
        QuestionnaireOut(
            id=row.id,
            version=row.version,
            title=row.title,
            variable=row.variable,
            identity=row.identity,
            last_entry_date=row.last_entry_date,
            kind=row.kind,
        )
        for row in resources
    ]


@router.get("/{connection_id}/resources", response_model=list[QuestionnaireOut])
def list_resources(
    connection_id: str, db: DbSession, user: CurrentUser
) -> list[QuestionnaireOut]:
    """Forms/dictionaries/data queries the connection can import."""
    return _resource_rows(_get(connection_id, db, user))


@router.get("/{connection_id}/questionnaires", response_model=list[QuestionnaireOut])
def list_questionnaires(
    connection_id: str, db: DbSession, user: CurrentUser
) -> list[QuestionnaireOut]:
    """Compatibility alias retained for existing Survey Solutions clients."""
    return _resource_rows(_get(connection_id, db, user))


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
    """Live interview summaries, currently a Survey Solutions capability."""
    connection = _get(connection_id, db, user)
    if _provider(connection) != "survey_solutions":
        raise HTTPException(
            status_code=400,
            detail=(
                "Live interview browsing is currently available for "
                "Survey Solutions connections only."
            ),
        )
    try:
        with SurveySolutionsClient(
            base_url=connection.base_url,
            username=connection.username,
            password=_secret(connection),
            workspace=connection.workspace,
            verify_ssl=connection.verify_ssl,
        ) as client:
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
    connection_id: str,
    payload: SyncRequest,
    db: DbSession,
    user: RequireManager,
) -> Job:
    """Queue an export + import run for selected source resources."""
    connection = _editable(connection_id, db, user)
    if problem := _saved_credentials_problem(connection):
        raise HTTPException(status_code=400, detail=problem)
    target_project = payload.project_id or connection.project_id
    if target_project and not can_edit(db, user, target_project, Role.manager):
        raise HTTPException(status_code=404, detail="Project not found")
    resources = payload.questionnaires or connection.questionnaires
    if not resources:
        raise HTTPException(
            status_code=400,
            detail=(
                "Choose at least one source resource to import, or set a default "
                "list on the connection."
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
        detail={"resources": resources, "provider": _provider(connection)},
    )
    db.commit()
    db.refresh(job)

    from app.workers.source_sync import run_connection_sync

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
    """The raw source export kept for recent sync runs."""
    _get(connection_id, db, user)
    run = db.get(SyncRun, run_id)
    if run is None or run.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Sync run not found")
    path = Path(run.archive_path) if run.archive_path else None
    if path is None or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="The source file for this run is no longer on the server.",
        )
    stem = slugify(run.questionnaire or "export") or "export"
    suffix = path.suffix.lower() or ".dat"
    if suffix == ".zip":
        media = "application/zip"
    elif suffix == ".csv":
        media = "text/csv"
    else:
        media = "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=f"{stem}-{run.started_at:%Y%m%d-%H%M}{suffix}",
    )


@router.get("/{connection_id}/runs", response_model=list[SyncRunOut])
def list_sync_runs(
    connection_id: str,
    db: DbSession,
    user: CurrentUser,
    limit: int = 20,
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
