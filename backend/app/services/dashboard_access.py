"""Server-owned authorisations for data deliberately included in a dashboard.

Dashboard readers (including anonymous readers) consume the author's selected
data. An untrusted widget ID is not permission to read a source. Grants record
the source's project and the editor who actually had access, and are checked
again before querying. Moving a source or revoking the editor's access closes
the grant. Old same-project/shared references remain usable; old cross-project
references must be saved again by an authorised editor.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import BoundaryLayer, Chart, Dashboard, Dataset, Indicator, User
from app.services.projects import scope_for


def _sources(db: Session, dashboard: Dashboard) -> dict[str, Dataset | BoundaryLayer]:
    sources: dict[str, Dataset | BoundaryLayer] = {}

    def add(model, identity):
        if not identity:
            return
        if not isinstance(identity, str):
            raise HTTPException(status_code=422, detail="Invalid dashboard source")
        found = db.get(model, identity)
        if found is None:
            # Deleted sources render as unavailable, as they did before.
            return
        sources[f"{model.__tablename__}:{identity}"] = found

    for control in dashboard.filters or []:
        if isinstance(control, dict):
            add(Dataset, control.get("dataset_id"))
    for widget in dashboard.widgets or []:
        add(Dataset, widget.dataset_id)
        config = widget.config or {}
        add(Dataset, config.get("dataset_id"))
        ids = config.get("dataset_ids") or []
        if not isinstance(ids, list):
            raise HTTPException(status_code=422, detail="Invalid dashboard sources")
        for identity in ids:
            add(Dataset, identity)
        add(BoundaryLayer, config.get("boundary_id"))
        for model, identity in ((Chart, widget.chart_id), (Indicator, widget.indicator_id)):
            if identity:
                found = db.get(model, identity)
                if found is not None:
                    add(Dataset, found.dataset_id)
    return sources


def authorise_sources(db: Session, dashboard: Dashboard, user: User) -> None:
    """Called on source edits only; never accept grants from request JSON."""
    grants = {}
    scope = scope_for(db, user)
    for key, source in _sources(db, dashboard).items():
        if not scope.allows(source.project_id):
            raise HTTPException(status_code=404, detail="Dashboard source not found")
        grants[key] = {"project_id": source.project_id, "user_id": user.id}
    dashboard.source_grants = grants


def require_sources(db: Session, dashboard: Dashboard) -> None:
    """Fail closed before rendering, exporting, or listing filter values."""
    grants = dashboard.source_grants or {}
    scopes = {}
    for key, source in _sources(db, dashboard).items():
        grant = grants.get(key)
        if grant is None:
            if source.project_id is None or source.project_id == dashboard.project_id:
                continue
        elif grant.get("project_id") == source.project_id:
            editor = db.get(User, grant.get("user_id"))
            if editor is not None and editor.is_active:
                if editor.id not in scopes:
                    scopes[editor.id] = scope_for(db, editor)
                if scopes[editor.id].allows(source.project_id):
                    continue
        raise HTTPException(
            status_code=404,
            detail="A dashboard source is no longer authorised. An editor must review its sources.",
        )
