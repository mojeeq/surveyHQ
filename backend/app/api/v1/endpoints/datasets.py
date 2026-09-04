"""Dataset upload, browsing and lifecycle."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select

from app.api.deps import (
    CurrentUser,
    DbSession,
    RequireManager,
    get_dataset,
    get_ready_dataset,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.models import (
    Dataset,
    DatasetSource,
    DatasetStatus,
    Job,
    JobStatus,
    JobType,
    Role,
    Variable,
)
from app.schemas.common import Message, Page
from app.schemas.monitoring import JobOut
from app.schemas.dataset import (
    ArchiveImportOut,
    BulkDeleteRequest,
    CommandRequest,
    DatasetDetail,
    DatasetOut,
    DatasetPreview,
    DatasetUpdate,
    VariableOut,
    VariableUpdate,
)
from app.schemas.query import FilterGroup
from app.services import stata
from app.services.audit import record
from app.services.datasets import (
    append_file_into_dataset,
    create_dataset_record,
    delete_dataset_files,
    load_archive_as_datasets,
    load_file_into_dataset,
)
from app.services.derived import propagate_labels, rebuild_dependents
from app.services.download import FORMATS as DOWNLOAD_FORMATS
from app.services.download import download_file, temp_directory
from app.services.ingest import SUPPORTED_EXTENSIONS, IngestError
from app.services.projects import can_edit, can_view, restrict, scope_for
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    SQLBuilder,
    distinct_values,
    run_sql,
)
from app.services.stata import CommandError
from app.services.stata_expr import ExpressionError

logger = get_logger(__name__)
router = APIRouter()


@router.get("", response_model=Page[DatasetOut])
def list_datasets(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    search: str = "",
    status: DatasetStatus | None = None,
    tag: str = "",
    project_id: str = "",
) -> Page[DatasetOut]:
    statement = restrict(select(Dataset), scope_for(db, user).filter(Dataset.project_id))
    if project_id:
        statement = statement.where(
            Dataset.project_id.is_(None)
            if project_id == "none"
            else Dataset.project_id == project_id
        )
    if search:
        pattern = f"%{search.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Dataset.name).like(pattern),
                func.lower(Dataset.description).like(pattern),
            )
        )
    if status:
        statement = statement.where(Dataset.status == status)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(Dataset.created_at.desc()).limit(limit).offset(offset)
    ).all()
    items = [DatasetOut.model_validate(d) for d in rows]
    if tag:
        items = [d for d in items if tag in (d.tags or [])]
    return Page(items=items, total=total, limit=limit, offset=offset)


def _queue_import(
    db: DbSession,
    *,
    user: Any,
    dataset: Dataset | None,
    upload_path: Path,
    filename: str,
    written: int,
    project_id: str | None,
    combine_all: bool,
    name_prefix: str,
    mode: str,
) -> Job:
    """Hand a large upload to the worker and answer with the job watching it."""
    job = Job(
        job_type=JobType.ingest,
        status=JobStatus.queued,
        title=f"Import {filename}",
        params={
            "upload_path": str(upload_path),
            "filename": filename,
            "dataset_id": dataset.id if dataset else "",
            "project_id": project_id or "",
            "combine_all": combine_all,
            "name_prefix": name_prefix,
            "mode": mode,
            "bytes": written,
        },
        created_by=user.id,
    )
    db.add(job)
    record(
        db,
        user=user,
        action="upload_dataset",
        entity_type="dataset",
        entity_id=dataset.id if dataset else None,
        detail={"filename": filename, "queued": True, "bytes": written},
    )
    db.commit()
    db.refresh(job)

    from app.workers.tasks import run_upload_import

    try:
        async_result = run_upload_import.delay(job.id)
        job.celery_task_id = async_result.id
        db.commit()
        db.refresh(job)
    except Exception as exc:  # noqa: BLE001 - broker unreachable
        logger.error("Could not queue import job %s: %s", job.id, exc)
        job.status = JobStatus.failed
        job.error = (
            "The background worker could not be reached. Check that the worker "
            "and Redis containers are running."
        )
        db.commit()
        db.refresh(job)
    return job


# Above this, an upload is imported by the worker rather than in the request.
# A census roster export is hundreds of megabytes and takes minutes to read,
# which is longer than any proxy in front of this will hold a request open -
# and reading it in the API process starves everyone else's requests of memory
# while it happens. The worker has neither problem, and the browser watches the
# job instead of watching a socket.
INLINE_IMPORT_LIMIT = 48 * 1024 * 1024


@router.post(
    "/upload",
    response_model=DatasetDetail | ArchiveImportOut | JobOut,
    status_code=201,
)
async def upload_dataset(
    request: Request,
    db: DbSession,
    user: RequireManager,
    file: Annotated[UploadFile, File(description="Stata, SPSS, CSV, tab or Excel file")],
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    combine_all: Annotated[bool, Form()] = False,
    project_id: Annotated[str, Form()] = "",
    mode: Annotated[str, Form()] = "replace",
) -> DatasetDetail | ArchiveImportOut | JobOut:
    """Upload a data file, or an export archive, and ingest it immediately.

    A single file becomes one dataset. An archive becomes one dataset per file
    inside it, because a Survey Solutions export holds one file per roster level
    - the interview, the household members, the people abroad - and those are
    different tables, not different rounds.

    Uploading a later archive sends each of its files to the dataset already
    holding that file name. mode="replace" (the default) swaps that dataset's
    data while keeping its id, so relationships, charts, indicators and quality
    rules built on it go on working - which is what a live monitoring tool
    needs. mode="append" adds the rows instead, for genuinely incremental
    exports.

    Pass combine_all for the other case: an archive that really does hold
    several rounds of one table, which goes into a single dataset instead.
    """
    filename = Path(file.filename or "upload.dat").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS and suffix != ".zip":
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{suffix or filename}' is not a supported format. Upload a .zip "
                "archive, or one of: " + ", ".join(sorted(SUPPORTED_EXTENSIONS))
            ),
        )

    if project_id and not can_edit(db, user, project_id, Role.manager):
        raise HTTPException(
            status_code=404, detail="Project not found"
        )

    if mode not in ("replace", "append"):
        raise HTTPException(
            status_code=422, detail="mode must be 'replace' or 'append'"
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    # Refused from the declared length, before a byte of it is stored. The old
    # order - store, count, refuse - meant the whole file was uploaded and
    # written to disk first, and a proxy that had already forwarded a body no
    # longer being read reported it as a bad gateway rather than as the size
    # limit it was.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes + 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=(
                f"This upload is {int(declared) / (1024 * 1024):,.0f} MB and the "
                f"limit is {settings.max_upload_mb} MB. Raise MAX_UPLOAD_MB in "
                ".env and restart, or upload the archive's files separately."
            ),
        )

    settings.ensure_directories()
    archive = suffix == ".zip"
    # An archive creates its own datasets, one per member file, so there is no
    # single record to make up front - and making one would leave an empty
    # dataset behind whenever the archive turned out to hold several tables.
    dataset = (
        None
        if archive
        else create_dataset_record(
            db,
            name=name.strip() or Path(filename).stem,
            description=description,
            source=DatasetSource.upload,
            source_ref=filename,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            created_by=user.id,
            project_id=project_id or None,
        )
    )

    upload_path = settings.uploads_path / f"{dataset.id if dataset else uuid4().hex}{suffix}"
    written = 0
    try:
        with open(upload_path, "wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {settings.max_upload_mb} MB upload limit",
                    )
                handle.write(chunk)
    except HTTPException:
        upload_path.unlink(missing_ok=True)
        db.rollback()
        raise
    finally:
        await file.close()

    if written > INLINE_IMPORT_LIMIT:
        return _queue_import(
            db,
            user=user,
            dataset=dataset,
            upload_path=upload_path,
            filename=filename,
            written=written,
            project_id=project_id or None,
            combine_all=combine_all,
            name_prefix=name.strip(),
            mode=mode,
        )

    try:
        if archive:
            outcome = load_archive_as_datasets(
                db,
                archive_path=upload_path,
                archive_name=filename,
                project_id=project_id or None,
                created_by=user.id,
                combine_all=combine_all,
                name_prefix=name.strip(),
                mode=mode,
                # Variables somebody generated are not in the export, so a
                # replacement drops them and everything built on them. The
                # recorded commands are run again on the new data.
                after_replace=stata.replay,
            )
        else:
            load_file_into_dataset(db, dataset, upload_path)
    except IngestError as exc:
        db.commit()  # keep the failed record so the user can see why
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        upload_path.unlink(missing_ok=True)

    # Whatever was merged out of the replaced files is holding the previous
    # export's join until it is re-run. Nothing on a dashboard would say so:
    # the merged dataset keeps its id, its name and its old row count.
    rebuilt = rebuild_dependents(db, outcome.replaced_ids if archive else [])
    if rebuilt:
        names = [d.name for d in (db.get(Dataset, i) for i in rebuilt) if d]
        outcome.warnings.append(
            "Rebuilt from the new data: " + ", ".join(sorted(names))
        )

    if archive:
        record(
            db,
            user=user,
            action="upload_archive",
            entity_type="dataset",
            detail={"filename": filename, "datasets": len(outcome.datasets)},
        )
        db.commit()
        for item in outcome.datasets:
            db.refresh(item)
        return ArchiveImportOut(
            datasets=[DatasetOut.model_validate(d) for d in outcome.datasets],
            created=outcome.created,
            appended=outcome.appended,
            replaced=outcome.replaced,
            skipped=outcome.skipped,
            warnings=sorted(
                set(outcome.warnings)
                | {w for d in outcome.datasets for w in (d.meta or {}).get("warnings", [])}
            ),
            rows=outcome.rows,
        )

    record(
        db,
        user=user,
        action="upload_dataset",
        entity_type="dataset",
        entity_id=dataset.id,
        detail={"filename": filename, "rows": dataset.row_count},
    )
    db.commit()
    db.refresh(dataset)
    return DatasetDetail.model_validate(dataset)


@router.get("/{dataset_id}", response_model=DatasetDetail)
def read_dataset(dataset_id: str, db: DbSession, user: CurrentUser) -> DatasetDetail:
    return DatasetDetail.model_validate(get_dataset(dataset_id, db, user))


@router.patch("/{dataset_id}", response_model=DatasetOut)
def update_dataset(
    dataset_id: str, payload: DatasetUpdate, db: DbSession, user: RequireManager
) -> Dataset:
    dataset = get_dataset(dataset_id, db, user)
    if payload.name is not None:
        dataset.name = payload.name
    if payload.description is not None:
        dataset.description = payload.description
    if payload.tags is not None:
        dataset.tags = payload.tags
    record(db, user=user, action="update_dataset", entity_type="dataset", entity_id=dataset_id)
    db.commit()
    db.refresh(dataset)
    return dataset


@router.post("/delete", response_model=Message)
def delete_datasets(
    payload: BulkDeleteRequest, db: DbSession, user: RequireManager
) -> Message:
    """Delete several datasets at once, or a whole project's worth.

    A survey export produces eight datasets in one upload, most of them roster
    levels and paradata, so clearing a project one confirmation at a time is
    eight confirmations for one decision.

    Datasets the caller cannot reach are skipped rather than refused: the
    listing they were chosen from is already scoped to what they can see, so a
    stray id is a stale page rather than an attempt at something.
    """
    if payload.project_id is not None:
        # Every dataset in one project, without the caller having to list them.
        statement = restrict(
            select(Dataset).where(Dataset.project_id == (payload.project_id or None)),
            scope_for(db, user).filter(Dataset.project_id),
        )
        targets = list(db.scalars(statement).all())
    else:
        targets = []
        for dataset_id in payload.ids:
            dataset = db.get(Dataset, dataset_id)
            if dataset is not None and can_view(db, user, dataset.project_id):
                targets.append(dataset)

    targets = [
        dataset
        for dataset in targets
        if not dataset.project_id or can_edit(db, user, dataset.project_id, Role.manager)
    ]
    if not targets:
        raise HTTPException(status_code=404, detail="Nothing to delete")

    names = [dataset.name for dataset in targets]
    for dataset in targets:
        delete_dataset_files(dataset)
        db.delete(dataset)
    record(
        db,
        user=user,
        action="delete_datasets",
        entity_type="dataset",
        detail={"count": len(names), "names": names[:20]},
    )
    db.commit()
    return Message(
        detail=f"Deleted {len(names)} dataset(s): " + ", ".join(names[:5])
        + ("…" if len(names) > 5 else "")
    )


@router.delete("/{dataset_id}", response_model=Message)
def delete_dataset(dataset_id: str, db: DbSession, user: RequireManager) -> Message:
    dataset = get_dataset(dataset_id, db, user)
    name = dataset.name
    delete_dataset_files(dataset)
    db.delete(dataset)
    record(
        db,
        user=user,
        action="delete_dataset",
        entity_type="dataset",
        entity_id=dataset_id,
        detail={"name": name},
    )
    db.commit()
    return Message(detail=f"Dataset '{name}' deleted")


@router.post("/{dataset_id}/replace", response_model=DatasetDetail)
async def replace_dataset_data(
    dataset_id: str,
    db: DbSession,
    user: RequireManager,
    file: Annotated[UploadFile, File()],
) -> DatasetDetail:
    """Refresh a dataset in place from a new file, keeping charts pointed at it."""
    dataset = get_dataset(dataset_id, db, user)
    filename = Path(file.filename or "upload.dat").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported format '{suffix}'")

    settings.ensure_directories()
    upload_path = settings.uploads_path / f"{dataset.id}-replace{suffix}"
    with open(upload_path, "wb") as handle:
        shutil.copyfileobj(file.file, handle)
    await file.close()

    try:
        load_file_into_dataset(db, dataset, upload_path)
    except IngestError as exc:
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        upload_path.unlink(missing_ok=True)

    record(
        db, user=user, action="replace_dataset", entity_type="dataset", entity_id=dataset.id
    )
    db.commit()
    db.refresh(dataset)
    return DatasetDetail.model_validate(dataset)


@router.post("/{dataset_id}/append", response_model=DatasetDetail)
async def append_to_dataset(
    dataset_id: str,
    db: DbSession,
    user: RequireManager,
    file: Annotated[UploadFile, File()],
) -> DatasetDetail:
    """Add another round's rows to a dataset rather than replacing them."""
    dataset = get_dataset(dataset_id, db, user)
    filename = Path(file.filename or "upload.dat").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS and suffix != ".zip":
        raise HTTPException(status_code=400, detail=f"Unsupported format '{suffix}'")

    settings.ensure_directories()
    upload_path = settings.uploads_path / f"{dataset.id}-append{suffix}"
    with open(upload_path, "wb") as handle:
        shutil.copyfileobj(file.file, handle)
    await file.close()

    try:
        append_file_into_dataset(db, dataset, upload_path, source_name=filename)
    except IngestError as exc:
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        upload_path.unlink(missing_ok=True)

    record(
        db,
        user=user,
        action="append_dataset",
        entity_type="dataset",
        entity_id=dataset.id,
        detail={"filename": filename, "rows": dataset.row_count},
    )
    db.commit()
    db.refresh(dataset)
    return DatasetDetail.model_validate(dataset)


@router.get("/{dataset_id}/download")
def download_dataset(
    dataset_id: str,
    background: BackgroundTasks,
    db: DbSession,
    user: RequireManager,
    format: str = Query(default="csv", pattern="^(csv|xlsx|dta)$"),
) -> Response:
    """The whole dataset as a file: CSV, Excel or Stata.

    Written from the Parquet the platform queries, not from whatever was
    uploaded, so a merged dataset - which never had a file of its own - comes
    back like any other, and what you get is what the charts are reading.

    Stata carries the labels: the variable labels and, where the codes are
    whole numbers, the value labels. That is the reason to prefer it to CSV.
    """
    dataset = get_ready_dataset(dataset_id, db, user)
    directory = temp_directory()
    try:
        path = download_file(dataset, format, directory)
    except QueryError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    # Deleted once the response has been sent, not before: the file is the
    # response body.
    background.add_task(shutil.rmtree, directory, ignore_errors=True)
    record(
        db,
        user=user,
        action="download_dataset",
        entity_type="dataset",
        entity_id=dataset.id,
        detail={"format": format, "rows": dataset.row_count},
    )
    db.commit()
    return FileResponse(
        path,
        media_type=DOWNLOAD_FORMATS[format][1],
        filename=path.name,
        background=background,
    )


@router.get("/{dataset_id}/variables", response_model=list[VariableOut])
def list_variables(
    dataset_id: str,
    db: DbSession,
    user: CurrentUser,
    search: str = "",
    var_type: str = "",
) -> list[Variable]:
    dataset = get_dataset(dataset_id, db, user)
    variables = dataset.variables
    if search:
        needle = search.lower()
        variables = [
            v for v in variables if needle in v.name.lower() or needle in (v.label or "").lower()
        ]
    if var_type:
        variables = [v for v in variables if v.var_type.value == var_type]
    return variables


@router.get("/{dataset_id}/preview", response_model=DatasetPreview)
def preview_dataset(
    dataset_id: str,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=50, le=1000),
    offset: int = 0,
    columns: str = "",
    sort_by: str = "",
    sort_dir: str = "asc",
) -> DatasetPreview:
    """Raw row browser for the data tab."""
    dataset = get_ready_dataset(dataset_id, db, user)
    ctx = DatasetContext.from_model(dataset)
    selected = [c.strip() for c in columns.split(",") if c.strip()] or None
    sort = [(sort_by, sort_dir)] if sort_by else None
    builder = SQLBuilder(ctx)
    try:
        sql, params = builder.build_rows(selected, FilterGroup(), limit, offset, sort)
        column_names, rows = run_sql(sql, params)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DatasetPreview(
        columns=column_names,
        rows=rows,
        total_rows=dataset.row_count,
        limit=limit,
        offset=offset,
    )


@router.patch("/{dataset_id}/variables/{variable}", response_model=VariableOut)
def update_variable(
    dataset_id: str,
    variable: str,
    payload: VariableUpdate,
    db: DbSession,
    user: RequireManager,
) -> Variable:
    """Name a variable, and name its codes.

    An export often arrives with neither: a column called DEM_SEX holding 1 and
    2, which a table then prints as "1.0" and "2.0". Nothing about the data is
    changed here - only what the platform calls it, everywhere it is shown.

    Kept on the dataset as well as on the variable row, because the variable
    rows are rebuilt from the file every time a newer export replaces it, and
    labels written by hand are not in the file.
    """
    dataset = get_dataset(dataset_id, db, user)
    if dataset.project_id and not can_edit(db, user, dataset.project_id, Role.manager):
        # Same as everywhere else: a dataset the caller cannot edit is reported
        # as missing rather than forbidden.
        raise HTTPException(status_code=404, detail="Dataset not found")
    row = next((v for v in dataset.variables if v.name == variable), None)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"'{dataset.name}' has no variable called '{variable}'"
        )

    data = payload.model_dump(exclude_unset=True)
    meta = dict(dataset.meta or {})
    overrides = dict(meta.get("variable_labels") or {})
    stored = dict(overrides.get(variable) or {})

    if "label" in data:
        row.label = data["label"] or ""
        stored["label"] = row.label
    if "value_labels" in data:
        # Replaces rather than merges: removing a label has to be possible, and
        # the editor sends the whole set it is showing.
        cleaned = {
            str(code): str(text)
            for code, text in (data["value_labels"] or {}).items()
            if str(text).strip()
        }
        row.value_labels = cleaned
        stored["value_labels"] = cleaned
    if "is_hidden" in data:
        row.is_hidden = bool(data["is_hidden"])
        stored["is_hidden"] = row.is_hidden

    overrides[variable] = stored
    meta["variable_labels"] = overrides
    dataset.meta = meta

    # A merge holds its own copy of the labels as they were when it was built,
    # and a merged dataset is usually the one a dashboard points at.
    propagate_labels(db, dataset.id, variable, stored)

    record(
        db,
        user=user,
        action="update_variable",
        entity_type="dataset",
        entity_id=dataset.id,
        detail={"variable": variable},
    )
    db.commit()
    db.refresh(row)
    return row


@router.post("/{dataset_id}/command", response_model=dict)
def run_command(
    dataset_id: str, payload: CommandRequest, db: DbSession, user: RequireManager
) -> dict[str, Any]:
    """Run a Stata-style script against the dataset, a command per line.

    Recorded on the dataset and replayed after a newer export replaces it: a
    variable somebody generated is not in the export file, so otherwise it
    would disappear on exactly the upload this platform is built around.

    A line that fails stops the script, and the response says which line and
    why. Everything above it has already run - as in a do-file - so it is
    committed rather than rolled back, and the log says what got through.
    """
    dataset = get_ready_dataset(dataset_id, db, user)
    if dataset.project_id and not can_edit(db, user, dataset.project_id, Role.manager):
        raise HTTPException(status_code=404, detail="Dataset not found")

    done: list[Any] = []
    failure: str | None = None
    try:
        done = stata.run_script(db, dataset, payload.command)
    except stata.ScriptError as exc:
        done, failure = exc.done, str(exc)
    except (CommandError, ExpressionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if failure and not done:
        # Nothing ran, so nothing to report but the reason.
        db.rollback()
        raise HTTPException(status_code=422, detail=failure)

    result = done[-1]
    rebuilt = (
        rebuild_dependents(db, [dataset.id])
        if any(step.data_changed for step in done)
        else []
    )
    record(
        db,
        user=user,
        action="run_command",
        entity_type="dataset",
        entity_id=dataset.id,
        detail={"commands": [step.command for step in done]},
    )
    db.commit()
    db.refresh(dataset)
    return {
        "results": [
            {
                "command": step.command,
                "message": step.message,
                "variables_added": step.variables_added,
                "variables_removed": step.variables_removed,
            }
            for step in done
        ],
        # The last one, kept so a caller that ran a single command still reads
        # the same fields it always did.
        "command": result.command,
        "message": result.message,
        "error": failure,
        "rows": dataset.row_count,
        "columns": dataset.column_count,
        "variables_added": result.variables_added,
        "variables_removed": result.variables_removed,
        "rebuilt": len(rebuilt),
    }


@router.get("/{dataset_id}/commands", response_model=list[str])
def list_commands(dataset_id: str, db: DbSession, user: CurrentUser) -> list[str]:
    """What has been run against this dataset, in the order it will be replayed."""
    return stata.history(get_dataset(dataset_id, db, user))


@router.delete("/{dataset_id}/commands", response_model=Message)
def clear_commands(dataset_id: str, db: DbSession, user: RequireManager) -> Message:
    """Stop replaying the recorded commands, without undoing what they did."""
    dataset = get_dataset(dataset_id, db, user)
    if dataset.project_id and not can_edit(db, user, dataset.project_id, Role.manager):
        raise HTTPException(status_code=404, detail="Dataset not found")
    stata.forget(dataset)
    db.commit()
    return Message(detail="The command history is cleared. Re-upload to rebuild from source.")


@router.get("/{dataset_id}/variables/{variable}/values", response_model=list[dict])
def variable_values(
    dataset_id: str,
    variable: str,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=200, le=1000),
) -> list[dict[str, Any]]:
    """Distinct values for building filters in the UI."""
    dataset = get_ready_dataset(dataset_id, db, user)
    ctx = DatasetContext.from_model(dataset)
    try:
        return distinct_values(ctx, variable, limit)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{dataset_id}/tags", response_model=list[str])
def all_tags(dataset_id: str, db: DbSession, user: CurrentUser) -> list[str]:
    dataset = get_dataset(dataset_id, db, user)
    return list(dataset.tags or [])
