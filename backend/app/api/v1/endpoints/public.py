"""Unauthenticated, read-only access to explicitly shared dashboards."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.v1.endpoints.dashboards import _render_widgets, background_response
from app.models import Dashboard
from app.schemas.analytics import DashboardDetail
from app.schemas.query import FilterGroup

router = APIRouter()


def _get_shared(token: str, db: DbSession) -> Dashboard:
    dashboard = db.scalar(
        select(Dashboard).where(
            Dashboard.public_token == token, Dashboard.is_public.is_(True)
        )
    )
    if dashboard is None:
        raise HTTPException(status_code=404, detail="This shared dashboard is not available")
    return dashboard


@router.get("/dashboards/{token}", response_model=DashboardDetail)
def read_shared_dashboard(token: str, db: DbSession) -> DashboardDetail:
    return DashboardDetail.model_validate(_get_shared(token, db))


@router.post("/dashboards/{token}/data", response_model=dict)
def render_shared_dashboard(
    token: str, db: DbSession, filters: FilterGroup | None = None
) -> dict[str, Any]:
    dashboard = _get_shared(token, db)
    return _render_widgets(db, dashboard, filters)


@router.get("/dashboards/{token}/background")
def read_shared_background(token: str, db: DbSession) -> Response:
    """A shared dashboard is shown as its owner dressed it, background and all."""
    return background_response(_get_shared(token, db))
