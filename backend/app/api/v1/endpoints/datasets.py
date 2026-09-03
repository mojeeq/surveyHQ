"""Dataset upload, browsing and lifecycle."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
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
from app.models import Dataset, DatasetSource, DatasetStatus, Role, Variable
from app.schemas.common import Message, Page
from app.schemas.dataset import (
    ArchiveImportOut,
    DatasetDetail,
    DatasetOut,
    DatasetPreview,
    DatasetUpdate,
    VariableOut,
)
from app.schemas.query import FilterGroup
from app.services.audit import record
from app.services.datasets import (
    append_file_into_dataset,
    create_dataset_record,
    delete_dataset_files,
    load_archive_as_datasets,
    load_file_into_dataset,
)
from app.services.ingest import SUPPORTED_EXTENSIONS, IngestError
from app.services.projects import can_edit, restrict, scope_for
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    SQLBuilder,
    distinct_values,
    run_sql,
)

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


@router.post("/upload", response_model=DatasetDetail | ArchiveImportOut, status_code=201)
async def upload_dataset(
    db: DbSession,
    user: RequireManager,
    file: Annotated[UploadFile, File(description="Stata, SPSS, CSV, tab or Excel file")],
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    combine_all: Annotated[bool, Form()] = False,
    project_id: Annotated[str, Form()] = "",
    mode: Annotated[str, Form()] = "replace",
) -> DatasetDetail | ArchiveImportOut:
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
    max_bytes = settings.max_upload_mb * 1024 * 1024
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
            )
        else:
            load_file_into_dataset(db, dataset, upload_path)
    except IngestError as exc:
        db.commit()  # keep the failed record so the user can see why
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        upload_path.unlink(missing_ok=True)

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
