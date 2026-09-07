"""Boundary layers: uploading the frame fieldwork is organised into."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession, RequireManager
from app.core.config import settings
from app.models import BoundaryFormat, BoundaryLayer, Role, User
from app.schemas.common import Message
from app.services import boundary_store, geometry
from app.services.audit import record
from app.services.projects import can_edit, restrict, scope_for

router = APIRouter()

FORMATS = {
    ".geojson": BoundaryFormat.geojson,
    ".json": BoundaryFormat.geojson,
    ".gpkg": BoundaryFormat.geopackage,
    ".zip": BoundaryFormat.shapefile,
}


class BoundaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    project_id: str | None = None
    source_format: str = "geojson"
    source_filename: str = ""
    feature_count: int = 0
    file_size: int = 0
    properties: list[str] = []
    bbox: list[float] = []
    created_at: dt.datetime
    updated_at: dt.datetime


class BoundaryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    project_id: str | None = None


def _get(layer_id: str, db: DbSession, user: User) -> BoundaryLayer:
    layer = db.get(BoundaryLayer, layer_id)
    # Missing rather than forbidden, as everywhere else: a 403 would let the
    # endpoint be used to discover which layers another project holds.
    if layer is None or not scope_for(db, user).allows(layer.project_id):
        raise HTTPException(status_code=404, detail="Boundary layer not found")
    return layer


@router.get("", response_model=list[BoundaryOut])
def list_layers(
    db: DbSession, user: CurrentUser, project_id: str = ""
) -> list[BoundaryLayer]:
    """This project's layers plus every shared one.

    A project filter does not hide the shared area here. A national frame is
    uploaded once and used by every survey that works to it, so narrowing to a
    project has to keep offering the layers that belong to everybody.
    """
    statement = restrict(
        select(BoundaryLayer).order_by(BoundaryLayer.name),
        scope_for(db, user).filter(BoundaryLayer.project_id),
    )
    if project_id and project_id != "none":
        statement = statement.where(
            or_(
                BoundaryLayer.project_id == project_id,
                BoundaryLayer.project_id.is_(None),
            )
        )
    elif project_id == "none":
        statement = statement.where(BoundaryLayer.project_id.is_(None))
    return list(db.scalars(statement).all())


@router.get("/{layer_id}", response_model=BoundaryOut)
def get_layer(layer_id: str, db: DbSession, user: CurrentUser) -> BoundaryLayer:
    return _get(layer_id, db, user)


@router.get("/{layer_id}/geojson")
def get_geometry(layer_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """The areas themselves, for drawing. Served whole: a map needs all of them."""
    layer = _get(layer_id, db, user)
    features, _ = boundary_store.load(layer.storage_path)
    return {"type": "FeatureCollection", "features": features}


@router.post("", response_model=BoundaryOut, status_code=201)
async def upload_layer(
    db: DbSession,
    user: RequireManager,
    file: Annotated[UploadFile, File(description="GeoJSON, GeoPackage, or a zipped shapefile")],
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    project_id: Annotated[str, Form()] = "",
    layer: Annotated[str, Form()] = "",
) -> BoundaryLayer:
    """Read a boundary file and keep it, normalised to GeoJSON.

    Whatever the GIS office exports is accepted, because asking a statistics
    office to convert its frame before it can be used is how a feature goes
    unused. What is stored is one format, so nothing downstream has to care.
    """
    if project_id and not can_edit(db, user, project_id, Role.manager):
        raise HTTPException(status_code=404, detail="Project not found")

    filename = file.filename or ""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in FORMATS:
        raise HTTPException(
            status_code=422,
            detail="Boundaries can be read from GeoJSON, a GeoPackage, or a zipped shapefile",
        )

    raw = await file.read()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(raw) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"This file is larger than the {settings.max_upload_mb} MB upload limit",
        )

    try:
        features = geometry.read(filename, raw, layer)
    except geometry.BoundaryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = BoundaryLayer(
        name=name.strip() or filename.rsplit(".", 1)[0] or "Boundaries",
        description=description.strip(),
        project_id=project_id or None,
        source_format=FORMATS[suffix].value,
        source_filename=filename,
        feature_count=len(features),
        properties=geometry.property_names(features),
        bbox=geometry.bounds(features) or [],
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    path, size = boundary_store.save(row.id, features)
    row.storage_path = str(path)
    row.file_size = size
    db.commit()
    db.refresh(row)
    record(
        db,
        user=user,
        action="boundary.upload",
        entity_type="boundary",
        entity_id=row.id,
        detail={"features": len(features), "format": row.source_format},
    )
    return row


@router.patch("/{layer_id}", response_model=BoundaryOut)
def update_layer(
    layer_id: str, payload: BoundaryUpdate, db: DbSession, user: RequireManager
) -> BoundaryLayer:
    layer = _get(layer_id, db, user)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("project_id") and not can_edit(
        db, user, changes["project_id"], Role.manager
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in changes.items():
        setattr(layer, field, value or None if field == "project_id" else value)
    db.commit()
    db.refresh(layer)
    return layer


@router.delete("/{layer_id}", response_model=Message)
def delete_layer(layer_id: str, db: DbSession, user: RequireManager) -> Message:
    layer = _get(layer_id, db, user)
    name = layer.name
    boundary_store.remove(layer.id)
    db.delete(layer)
    db.commit()
    record(
        db,
        user=user,
        action="boundary.delete",
        entity_type="boundary",
        entity_id=layer_id,
        detail={"name": name},
    )
    return Message(detail="Boundary layer deleted")
