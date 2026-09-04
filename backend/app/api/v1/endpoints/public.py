"""Unauthenticated, read-only access to explicitly shared dashboards."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.v1.endpoints.dashboards import _render_widgets, background_response
from app.models import Dashboard
from app.schemas.analytics import DashboardDetail
from app.schemas.query import FilterGroup

router = APIRouter()


@router.get("/site", response_model=dict)
def resolve_host(request: Request, db: DbSession) -> dict[str, Any]:
    """Whether the host this was asked on is a published dashboard.

    The app is one bundle served for every hostname, so it cannot know from the
    URL alone whether it is the platform or somebody's results page. It asks
    here once, before deciding what to render.

    Only a hostname explicitly assigned to a shared dashboard matches. The Host
    header is a request header like any other - it is looked up, never trusted.
    """
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    if not host:
        return {"dashboard": None}
    dashboard = db.scalar(
        select(Dashboard).where(
            Dashboard.public_hostname == host, Dashboard.is_public.is_(True)
        )
    )
    if dashboard is None or not dashboard.public_token:
        return {"dashboard": None}
    # The token is handed over because this host already grants what the token
    # grants: the same read-only dashboard, to anybody who reaches it.
    return {
        "dashboard": {"token": dashboard.public_token, "name": dashboard.name},
    }


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
    token: str,
    db: DbSession,
    filters: FilterGroup | None = None,
    every_widget_but: str = "",
) -> dict[str, Any]:
    """A shared dashboard renders like any other, click-to-filter included."""
    dashboard = _get_shared(token, db)
    return _render_widgets(db, dashboard, filters, every_widget_but)


@router.get("/dashboards/{token}/background")
def read_shared_background(token: str, db: DbSession) -> Response:
    """A shared dashboard is shown as its owner dressed it, background and all."""
    return background_response(_get_shared(token, db))


@router.get("/dashboards/{token}/logo")
def read_shared_logo(token: str, db: DbSession) -> Response:
    """The logo too: a shared link is where somebody else's badge matters most."""
    return background_response(_get_shared(token, db), kind="logo")
