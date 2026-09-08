"""Unauthenticated, read-only access to explicitly shared dashboards."""

from __future__ import annotations

from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, client_ip
from app.api.v1.endpoints.dashboards import (
    _render_widgets,
    background_response,
    boundary_response,
    filter_values_response,
    restrict_to_visible,
    visible_variables,
)
from app.core.rate_limit import enforce
from app.core.security import (
    create_access_token,
    decode_token,
    verify_password,
)
from app.db.base import utcnow
from app.models import Dashboard, ShareLink
from app.schemas.analytics import DashboardDetail
from app.schemas.query import FilterGroup
from app.services.sharing import link_is_open

# The only unauthenticated routes in the platform, and the expensive one among
# them scans a Parquet file per widget. A dashboard opening costs a handful of
# calls and then one per refresh, so this is far above what viewing needs -
# including a whole office behind one address - and far below what it takes to
# read a dataset out through repeated queries.
PUBLIC_REQUESTS_PER_MINUTE = 120


def rate_limit_public(request: Request) -> None:
    enforce(
        f"public:{client_ip(request) or 'unknown'}",
        PUBLIC_REQUESTS_PER_MINUTE,
        60,
        "This dashboard is being requested too quickly. Wait a moment and reload.",
    )


router = APIRouter(dependencies=[Depends(rate_limit_public)])


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


# A grant says "this reader knew the password for this link". It is checked on
# every subsequent request, which is why it exists: bcrypt is deliberately slow,
# and a dashboard on a wall refreshing every minute for a room full of people
# would spend its life hashing. Short-lived, because a link closed this
# afternoon should not still be readable this evening.
GRANT_MINUTES = 720
GRANT_HEADER = "x-share-grant"
LOCKED = "This link needs a password."


def _link_for(token: str, db: DbSession) -> ShareLink | None:
    return db.scalar(select(ShareLink).where(ShareLink.token == token))


def _get_shared(token: str, db: DbSession, request: Request | None = None) -> Dashboard:
    """The dashboard behind a public token, from either kind of link.

    A dashboard's own token is the address it has always had; a ShareLink is
    one of the several a board can be published at, each closable on its own.
    Both are resolved here so nothing downstream has to know which it was
    handed.
    """
    link = _link_for(token, db)
    if link is not None:
        # Closed by hand and run out are one answer to the reader. Which of
        # the two it was is the author's business, and telling a stranger
        # "this expired on the 3rd" says more about the organisation's work
        # than the address itself does.
        if not link_is_open(link):
            raise HTTPException(
                status_code=404, detail="This shared dashboard is not available"
            )
        if link.password_hash and not _granted(token, request):
            raise HTTPException(status_code=401, detail=LOCKED)
        dashboard = db.get(Dashboard, link.dashboard_id)
        if dashboard is None:
            raise HTTPException(
                status_code=404, detail="This shared dashboard is not available"
            )
        return dashboard

    dashboard = db.scalar(
        select(Dashboard).where(
            Dashboard.public_token == token, Dashboard.is_public.is_(True)
        )
    )
    if dashboard is None:
        raise HTTPException(status_code=404, detail="This shared dashboard is not available")
    return dashboard


def _granted(token: str, request: Request | None) -> bool:
    """Whether this request carries a valid grant for this link."""
    raw = (request.headers.get(GRANT_HEADER) if request else "") or ""
    if not raw:
        return False
    try:
        claims = decode_token(raw)
    except jwt.PyJWTError:
        return False
    return claims.get("type") == "share" and claims.get("sub") == token


class Unlock(BaseModel):
    password: str = ""


@router.post("/dashboards/{token}/unlock", response_model=dict)
def unlock_shared_dashboard(token: str, payload: Unlock, db: DbSession) -> dict[str, Any]:
    """Trade the password for a grant the other routes will accept.

    Once per reader rather than once per request. The password itself is
    checked here and nowhere else, so the slow hash is paid on opening the
    dashboard instead of on every refresh of it.
    """
    link = _link_for(token, db)
    if link is None or not link_is_open(link):
        raise HTTPException(status_code=404, detail="This shared dashboard is not available")
    if not link.password_hash:
        # Nothing to unlock, and saying so beats handing back a grant that
        # implies there was.
        return {"grant": "", "required": False}
    if not payload.password or not verify_password(payload.password, link.password_hash):
        raise HTTPException(status_code=401, detail="That password is not right.")
    return {
        "grant": create_access_token(
            token, extra={"type": "share"}, expires_minutes=GRANT_MINUTES
        ),
        "required": True,
    }


@router.get("/dashboards/{token}", response_model=DashboardDetail)
def read_shared_dashboard(token: str, db: DbSession, request: Request) -> DashboardDetail:
    dashboard = _get_shared(token, db, request)
    _count_view(token, db)
    return DashboardDetail.model_validate(dashboard)


def _count_view(token: str, db: DbSession) -> None:
    """How often a link is opened, so a dead one can be recognised as dead."""
    link = _link_for(token, db)
    if link is None:
        return
    link.view_count = (link.view_count or 0) + 1
    link.last_viewed_at = utcnow()
    db.commit()


@router.post("/dashboards/{token}/data", response_model=dict)
def render_shared_dashboard(
    token: str,
    db: DbSession,
    request: Request,
    filters: FilterGroup | None = None,
    every_widget_but: str = "",
) -> dict[str, Any]:
    """A shared dashboard renders like any other, click-to-filter included.

    With one difference: the filter is held to what the dashboard displays. A
    signed-in analyst filtering by a column no widget shows is using the
    dataset they already have; an anonymous visitor doing it is asking the
    dataset questions the link never offered to answer.
    """
    dashboard = _get_shared(token, db, request)
    filters = restrict_to_visible(filters, visible_variables(db, dashboard))
    return _render_widgets(db, dashboard, filters, every_widget_but)


@router.get("/dashboards/{token}/background")
def read_shared_background(token: str, db: DbSession, request: Request) -> Response:
    """A shared dashboard is shown as its owner dressed it, background and all."""
    return background_response(_get_shared(token, db, request))


@router.get("/dashboards/{token}/filter-values/{variable}", response_model=list[dict])
def read_shared_filter_values(
    token: str, variable: str, db: DbSession, request: Request, limit: int = 200
) -> list[dict[str, Any]]:
    """The choices in a shared dashboard's own filter dropdowns.

    Without this the dropdowns on a copied link were empty for anybody not
    already signed in, because the values came from the dataset endpoint and
    that needs an account.
    """
    return filter_values_response(
        _get_shared(token, db, request), variable, db, min(limit, 1000)
    )


@router.get("/dashboards/{token}/boundaries/{layer_id}", response_model=dict)
def read_shared_boundary(
    token: str, layer_id: str, db: DbSession, request: Request
) -> dict[str, Any]:
    """The outlines under a shared map, which are part of what it says."""
    return boundary_response(_get_shared(token, db, request), layer_id, db)


@router.get("/dashboards/{token}/logo")
def read_shared_logo(token: str, db: DbSession, request: Request) -> Response:
    """The logo too: a shared link is where somebody else's badge matters most."""
    return background_response(_get_shared(token, db, request), kind="logo")
