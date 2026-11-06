"""Publishing dashboards to GitHub Pages and other web servers.

Two halves. The destinations - a repository, a server reached over SFTP, an FTP
host - are set up by an administrator, because each holds the credentials for
somebody else's server. Publishing a board to one is open to anybody who may
share it, as making a share link is: both put the board in front of whoever
has the address.

Publishing happens in the request, as the HTML export does: it is the same
work plus an upload, and whoever pressed the button is waiting to be told it
worked and where the board now is.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import DbSession, RequireAdmin, RequireAnalyst
from app.api.v1.endpoints.dashboards import _get_dashboard, _views_for
from app.models import Dashboard, DashboardView, Publication, PublishTarget
from app.schemas.common import Message
from app.schemas.publishing import (
    CheckOut,
    PublicationIn,
    PublicationOut,
    PublicationPatch,
    RepublishIn,
    TargetIn,
    TargetOut,
    TargetPatch,
)
from app.services import publishing
from app.services.audit import record
from app.services.publishing.sftp import fingerprint
from app.services.publishing.sites import SECRET_KEYS, known_folder_url

router = APIRouter()
# The publications of one board, under the dashboard's own address.
dashboard_router = APIRouter()


# --- destinations -------------------------------------------------------------


def _target_out(db: DbSession, target: PublishTarget) -> TargetOut:
    settings = dict(target.settings or {})
    host_key = str(settings.pop("host_key", "") or "")
    count = db.scalar(
        select(func.count()).select_from(Publication).where(Publication.target_id == target.id)
    )
    try:
        kept = sorted(publishing.unseal(target.secret_encrypted))
    except publishing.PublishError:
        # Sealed under an ENCRYPTION_KEY that has since changed: there is
        # nothing usable kept, and the form should ask for it again.
        kept = []
    return TargetOut(
        id=target.id,
        name=target.name,
        kind=target.kind,  # type: ignore[arg-type]
        settings=settings,
        secrets=kept,
        host_key_fingerprint=fingerprint(host_key) if host_key else "",
        folder_url=known_folder_url(target),
        publications=int(count or 0),
        created_at=target.created_at,
    )


def _target(db: DbSession, target_id: str) -> PublishTarget:
    target = db.get(PublishTarget, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No such destination")
    return target


def _secrets(payload: TargetIn | TargetPatch) -> dict[str, str]:
    return {key: getattr(payload, key).strip() for key in SECRET_KEYS if getattr(payload, key)}


@router.get("/targets", response_model=list[TargetOut])
def list_targets(db: DbSession, user: RequireAnalyst) -> list[TargetOut]:
    """Every destination, for choosing one to publish to. No secrets."""
    targets = db.scalars(select(PublishTarget).order_by(PublishTarget.name)).all()
    return [_target_out(db, target) for target in targets]


@router.post("/targets", response_model=TargetOut, status_code=201)
def create_target(payload: TargetIn, db: DbSession, user: RequireAdmin) -> TargetOut:
    try:
        settings = publishing.clean_settings(payload.kind, payload.settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    target = PublishTarget(
        name=payload.name.strip(),
        kind=payload.kind,
        settings=settings,
        secret_encrypted=publishing.seal(_secrets(payload)),
        created_by=user.id,
    )
    db.add(target)
    db.flush()
    record(
        db,
        user=user,
        action="publish_target.create",
        entity_type="publish_target",
        entity_id=target.id,
        detail={"name": target.name, "kind": target.kind},
    )
    db.commit()
    db.refresh(target)
    return _target_out(db, target)


@router.patch("/targets/{target_id}", response_model=TargetOut)
def update_target(
    target_id: str, payload: TargetPatch, db: DbSession, user: RequireAdmin
) -> TargetOut:
    target = _target(db, target_id)
    if payload.name is not None:
        target.name = payload.name.strip()
    if payload.settings is not None:
        try:
            settings = publishing.clean_settings(
                target.kind, payload.settings, kept=target.settings or {}
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        at_front = db.scalar(
            select(func.count())
            .select_from(Publication)
            .where(Publication.target_id == target.id, Publication.path == "")
        )
        if settings["contents_page"] and at_front:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A dashboard is published at the front of this destination's folder, "
                    "which is where the list would go. Move it to an address of its own first."
                ),
            )
        target.settings = settings
    if payload.forget_host_key:
        target.settings = {**(target.settings or {}), "host_key": ""}
    changed = _secrets(payload)
    if changed:
        try:
            kept = publishing.unseal(target.secret_encrypted)
        except publishing.PublishError:
            kept = {}
        # A password and a key are alternatives: setting one drops the other,
        # so a destination switched to a key does not go on carrying the
        # password it no longer uses.
        if "private_key" in changed:
            kept.pop("password", None)
        if "password" in changed:
            kept.pop("private_key", None)
            kept.pop("passphrase", None)
        target.secret_encrypted = publishing.seal({**kept, **changed})
    record(
        db,
        user=user,
        action="publish_target.update",
        entity_type="publish_target",
        entity_id=target.id,
        detail={"name": target.name, "secrets": sorted(changed)},
    )
    db.commit()
    db.refresh(target)
    return _target_out(db, target)


@router.delete("/targets/{target_id}", response_model=Message)
def delete_target(target_id: str, db: DbSession, user: RequireAdmin) -> Message:
    """Remove a destination that has nothing published on it.

    Refused while it has: deleting it would leave those pages online with
    nothing here that knows about them, and no way to take them down.
    """
    target = _target(db, target_id)
    count = db.scalar(
        select(func.count()).select_from(Publication).where(Publication.target_id == target.id)
    )
    if count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{count} dashboard{'s are' if count != 1 else ' is'} published to "
                f"{target.name}. Unpublish {'them' if count != 1 else 'it'} first, so "
                "nothing is left online that this platform no longer knows about."
            ),
        )
    name = target.name
    db.delete(target)
    record(
        db,
        user=user,
        action="publish_target.delete",
        entity_type="publish_target",
        entity_id=target_id,
        detail={"name": name},
    )
    db.commit()
    return Message(detail=f"Destination '{name}' deleted")


@router.post("/targets/{target_id}/test", response_model=CheckOut)
def test_target(target_id: str, db: DbSession, user: RequireAdmin) -> CheckOut:
    """Connect, and write and remove a file, to show publishing will work."""
    target = _target(db, target_id)
    try:
        found = publishing.check(db, target)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    db.commit()
    host_key = str((target.settings or {}).get("host_key") or "")
    return CheckOut(
        message=found.message,
        url=found.url,
        notes=found.notes,
        host_key_fingerprint=fingerprint(host_key) if host_key else "",
    )


# --- one dashboard's publications ---------------------------------------------


def _publication_out(db: DbSession, publication: Publication) -> PublicationOut:
    target = db.get(PublishTarget, publication.target_id)
    view = db.get(DashboardView, publication.view_id) if publication.view_id else None
    return PublicationOut(
        id=publication.id,
        dashboard_id=publication.dashboard_id,
        target_id=publication.target_id,
        target_name=target.name if target else "",
        target_kind=target.kind if target else "",
        path=publication.path,
        view_id=publication.view_id,
        view_name=view.name if view else ("(deleted view)" if publication.view_id else ""),
        auto_republish=publication.auto_republish,
        status=publication.status,
        url=publication.url,
        last_published_at=publication.last_published_at,
        last_error=publication.last_error,
        size_bytes=publication.size_bytes,
        notes=list(publication.notes or []),
        created_at=publication.created_at,
    )


def _publication(db: DbSession, dashboard: Dashboard, publication_id: str) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None or publication.dashboard_id != dashboard.id:
        raise HTTPException(status_code=404, detail="That dashboard is not published there")
    return publication


@dashboard_router.get("/{dashboard_id}/publications", response_model=list[PublicationOut])
def list_publications(
    dashboard_id: str, db: DbSession, user: RequireAnalyst
) -> list[PublicationOut]:
    dashboard = _get_dashboard(dashboard_id, db, user)
    rows = db.scalars(
        select(Publication)
        .where(Publication.dashboard_id == dashboard.id)
        .order_by(Publication.created_at)
    ).all()
    return [_publication_out(db, row) for row in rows]


@dashboard_router.post(
    "/{dashboard_id}/publications", response_model=PublicationOut, status_code=201
)
def create_publication(
    dashboard_id: str, payload: PublicationIn, db: DbSession, user: RequireAnalyst
) -> PublicationOut:
    """Publish a board to a destination, at an address of its own there.

    Nothing is kept unless the publish goes through: a refusal leaves no
    half-made publication behind to explain.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)
    target = _target(db, payload.target_id)
    view = None
    if payload.view_id:
        view = next(
            (one for one in _views_for(db, dashboard, user) if one.id == payload.view_id), None
        )
        if view is None:
            raise HTTPException(status_code=404, detail="View not found")
    try:
        path = (
            publishing.default_path(dashboard, view)
            if payload.path is None
            else publishing.clean_path(payload.path)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    taken = db.scalar(
        select(Publication).where(Publication.target_id == target.id, Publication.path == path)
    )
    if taken is not None:
        where = f"{path}/" if path else "the front of the folder"
        if taken.dashboard_id == dashboard.id:
            detail = (
                f"This dashboard is already published at {where} on {target.name}. "
                "Publish it again from the list instead."
            )
        else:
            other = db.get(Dashboard, taken.dashboard_id)
            detail = (
                f"'{other.name if other else 'Another dashboard'}' is already published at "
                f"{where} on {target.name}. Choose another address."
            )
        raise HTTPException(status_code=409, detail=detail)

    publication = Publication(
        dashboard_id=dashboard.id,
        target_id=target.id,
        path=path,
        view_id=view.id if view else "",
        auto_republish=payload.auto_republish,
        created_by=user.id,
    )
    db.add(publication)
    db.flush()
    try:
        publishing.publish(
            db, publication, user_id=user.id, replace_existing=payload.replace_existing
        )
    except publishing.PublishError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    record(
        db,
        user=user,
        action="dashboard.publish",
        entity_type="dashboard",
        entity_id=dashboard.id,
        detail={"target": target.name, "path": path, "view": view.name if view else ""},
    )
    db.commit()
    db.refresh(publication)
    return _publication_out(db, publication)


@dashboard_router.patch(
    "/{dashboard_id}/publications/{publication_id}", response_model=PublicationOut
)
def update_publication(
    dashboard_id: str,
    publication_id: str,
    payload: PublicationPatch,
    db: DbSession,
    user: RequireAnalyst,
) -> PublicationOut:
    dashboard = _get_dashboard(dashboard_id, db, user)
    publication = _publication(db, dashboard, publication_id)
    if payload.auto_republish is not None:
        publication.auto_republish = payload.auto_republish
    db.commit()
    db.refresh(publication)
    return _publication_out(db, publication)


@dashboard_router.post(
    "/{dashboard_id}/publications/{publication_id}/publish", response_model=PublicationOut
)
def republish(
    dashboard_id: str,
    publication_id: str,
    payload: RepublishIn,
    db: DbSession,
    user: RequireAnalyst,
) -> PublicationOut:
    """Bring the published copy up to date with the board as it is now."""
    dashboard = _get_dashboard(dashboard_id, db, user)
    publication = _publication(db, dashboard, publication_id)
    try:
        publishing.publish(
            db, publication, user_id=user.id, replace_existing=payload.replace_existing
        )
    except publishing.PublishError as exc:
        # Kept as failed, with the reason: the list says so until it works.
        db.commit()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    record(
        db,
        user=user,
        action="dashboard.republish",
        entity_type="dashboard",
        entity_id=dashboard.id,
        detail={"publication": publication.id, "url": publication.url},
    )
    db.commit()
    db.refresh(publication)
    return _publication_out(db, publication)


@dashboard_router.delete(
    "/{dashboard_id}/publications/{publication_id}", response_model=Message
)
def unpublish(
    dashboard_id: str,
    publication_id: str,
    db: DbSession,
    user: RequireAnalyst,
    keep_files: bool = False,
) -> Message:
    """Take the board's page off the destination and forget it here.

    `keep_files` forgets it without touching the destination, for a server
    that is gone for good. A destination that cannot be reached otherwise
    leaves the publication where it is, so nothing is forgotten that is still
    online.
    """
    dashboard = _get_dashboard(dashboard_id, db, user)
    publication = _publication(db, dashboard, publication_id)
    target = db.get(PublishTarget, publication.target_id)
    where = target.name if target else "the destination"
    try:
        notes = publishing.unpublish(db, publication, keep_files=keep_files)
    except publishing.PublishError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    record(
        db,
        user=user,
        action="dashboard.unpublish",
        entity_type="dashboard",
        entity_id=dashboard.id,
        detail={"target": where, "path": publication.path, "kept_files": keep_files},
    )
    db.commit()
    said = (
        f"Removed from this list; the page on {where} was left as it is."
        if keep_files
        else f"Taken down from {where}."
    )
    return Message(detail=" ".join([said, *notes]))
