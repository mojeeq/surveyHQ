"""Dataset upload, browsing and lifecycle."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Any

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
from app.models import Dataset, DatasetSource, DatasetStatus, Variable
from app.schemas.common import Message, Page
from app.schemas.dataset import (
    DatasetDetail,
    DatasetOut,
    DatasetPreview,
    DatasetUpdate,
    VariableOut,
)
from app.schemas.query import FilterGroup
from app.services.archives import is_archive
from app.services.audit import record
from app.services.datasets import (
    append_file_into_dataset,
    create_dataset_record,
    delete_dataset_files,
    load_archive_into_dataset,
    load_file_into_dataset,
)
from app.services.ingest import SUPPORTED_EXTENSIONS, IngestError
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
    _: CurrentUser,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    search: str = "",
    status: DatasetStatus | None = None,
    tag: str = "",
) -> Page[DatasetOut]:
    statement = select(Dataset)
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


@router.post("/upload", response_model=DatasetDetail, status_code=201)
async def upload_dataset(
    db: DbSession,
    user: RequireManager,
    file: Annotated[UploadFile, File(description="Stata, SPSS, CSV, tab or Excel file")],
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    combine_all: Annotated[bool, Form()] = False,
) -> DatasetDetail:
    """Upload a data file, or a zip of them, and ingest it immediately.

    A zip is unpacked and the files inside appended into one dataset, with a
    source_file column recording where each row came from. By default only files
    sharing a column set are appended, because an export archive usually holds
    one file per roster level rather than several rounds; combine_all forces
    everything together on the union of their columns.
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

    settings.ensure_directories()
    dataset = create_dataset_record(
        db,
        name=name.strip() or Path(filename).stem,
        description=description,
        source=DatasetSource.upload,
        source_ref=filename,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        created_by=user.id,
    )

    upload_path = settings.uploads_path / f"{dataset.id}{suffix}"
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
        if is_archive(upload_path):
            load_archive_into_dataset(db, dataset, upload_path, combine_all=combine_all)
        else:
            load_file_into_dataset(db, dataset, upload_path)
    except IngestError as exc:
        db.commit()  # keep the failed record so the user can see why
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        upload_path.unlink(missing_ok=True)

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
def read_dataset(dataset_id: str, db: DbSession, _: CurrentUser) -> DatasetDetail:
    return DatasetDetail.model_validate(get_dataset(dataset_id, db))


@router.patch("/{dataset_id}", response_model=DatasetOut)
def update_dataset(
    dataset_id: str, payload: DatasetUpdate, db: DbSession, user: RequireManager
) -> Dataset:
    dataset = get_dataset(dataset_id, db)
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
    dataset = get_dataset(dataset_id, db)
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
    dataset = get_dataset(dataset_id, db)
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
    dataset = get_dataset(dataset_id, db)
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
    _: CurrentUser,
    search: str = "",
    var_type: str = "",
) -> list[Variable]:
    dataset = get_dataset(dataset_id, db)
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
    _: CurrentUser,
    limit: int = Query(default=50, le=1000),
    offset: int = 0,
    columns: str = "",
    sort_by: str = "",
    sort_dir: str = "asc",
) -> DatasetPreview:
    """Raw row browser for the data tab."""
    dataset = get_ready_dataset(dataset_id, db)
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
    _: CurrentUser,
    limit: int = Query(default=200, le=1000),
) -> list[dict[str, Any]]:
    """Distinct values for building filters in the UI."""
    dataset = get_ready_dataset(dataset_id, db)
    ctx = DatasetContext.from_model(dataset)
    try:
        return distinct_values(ctx, variable, limit)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{dataset_id}/tags", response_model=list[str])
def all_tags(dataset_id: str, db: DbSession, _: CurrentUser) -> list[str]:
    dataset = get_dataset(dataset_id, db)
    return list(dataset.tags or [])
