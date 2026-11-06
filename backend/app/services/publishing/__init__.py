"""Publishing dashboards to a web server somewhere else.

The page published is the HTML export - one file, its filters still working,
the drawing libraries and fonts inside it - so what goes online is what the
export button has always produced: the numbers each widget shows, at the grain
its filters need, with the disclosure floor applied, and never a row of data.
This platform can therefore sit on an office network or a laptop while the
board it built is read on GitHub Pages or a ministry's website.

Two rules hold everything here:

- Nothing that this platform did not write is overwritten or deleted. Every
  page it publishes carries a marker in its head, and a file at the address
  without one is somebody else's - a ministry's own front page, an export
  somebody uploaded by hand. Publishing over it takes an explicit yes, and
  unpublishing leaves it where it is.
- A failed publish leaves the last good page online. The address keeps
  working while whatever went wrong is fixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import Dashboard, DashboardView, Project, ProjectStatus, Publication, PublishTarget
from app.services import static_export
from app.services.publishing import contents
from app.services.publishing.sites import (
    AddressTaken,
    Check,
    NotReady,
    PublishError,
    clean_path,
    clean_settings,
    join_url,
    open_site,
    ours,
    page_file,
    seal,
    unseal,
)

logger = get_logger(__name__)

__all__ = [
    "AddressTaken",
    "Check",
    "NotReady",
    "PublishError",
    "build_page",
    "check",
    "clean_path",
    "clean_settings",
    "default_path",
    "publish",
    "republish_after_import",
    "seal",
    "take_down_all",
    "unpublish",
    "unseal",
]

CONTENTS = "index.html"


def default_path(dashboard: Dashboard, view: DashboardView | None = None) -> str:
    """Where a board goes unless somebody says otherwise: its name, and its
    view's after it, as a folder."""
    name = slugify(dashboard.name)[:80] or "dashboard"
    if view is not None:
        name = f"{name}-{slugify(view.name)[:60] or 'view'}"
    return name


def build_page(db: Session, dashboard: Dashboard, view_id: str = "") -> bytes:
    """The board as one HTML file - the export, exactly.

    The renderer lives with the API and is imported here rather than at the
    top, as the report and snapshot jobs do: importing it at module scope
    would pull the whole endpoint layer into the worker at start-up.
    """
    from app.api.v1.endpoints.dashboards import _pinned_from_view, _render_widget

    pinned: dict[str, str] = {}
    if view_id:
        view = db.get(DashboardView, view_id)
        if view is None or view.dashboard_id != dashboard.id:
            raise NotReady(
                "The saved view this page was published from has been deleted. Unpublish "
                "it, or publish the board again without a view."
            )
        pinned, _ = _pinned_from_view(view_id, dashboard.id, db)
    payload = static_export.build_payload(
        db,
        dashboard,
        render=lambda widget, filters: _render_widget(db, widget, filters),
        pinned=pinned,
    )
    html = static_export.render_html(payload, static_export.appearance_css(dashboard))
    return html.encode("utf-8")


def _refuse_if_archived(db: Session, dashboard: Dashboard) -> None:
    project = db.get(Project, dashboard.project_id) if dashboard.project_id else None
    if project is not None and project.status == ProjectStatus.archived:
        raise NotReady(
            f"'{project.name}' is archived, so its data has been cleared and the board "
            "would be published empty. Unarchive the project and import the data again first."
        )


def _contents_page(
    db: Session,
    site: Any,
    target: PublishTarget,
    *,
    including: Publication | None = None,
    excluding: Publication | None = None,
) -> tuple[bytes | None, list[str]]:
    """The destination's front page as it should now read, or None to leave it.

    Left alone where the destination does not keep one, and where the folder
    already has a front page this platform did not write.
    """
    if not (target.settings or {}).get("contents_page"):
        return None, []
    existing = site.read_head(CONTENTS)
    if existing is not None and not ours(existing):
        return None, [
            "The folder already has a front page that SurveyHQ did not write, so the list "
            "of published dashboards was not put there."
        ]
    # Every board with a page there - including one whose last republish
    # failed, because the copy before it is still online and still listed.
    publications = [
        one
        for one in db.scalars(
            select(Publication).where(
                Publication.target_id == target.id, Publication.last_published_at.is_not(None)
            )
        ).all()
        if excluding is None or one.id != excluding.id
    ]
    if including is not None and all(one.id != including.id for one in publications):
        publications.append(including)
    boards = {
        board.id: board
        for board in db.scalars(
            select(Dashboard).where(Dashboard.id.in_({one.dashboard_id for one in publications}))
        ).all()
    }
    views = {
        view.id: view
        for view in db.scalars(
            select(DashboardView).where(
                DashboardView.id.in_({one.view_id for one in publications if one.view_id})
            )
        ).all()
    }
    entries = []
    for one in publications:
        board = boards.get(one.dashboard_id)
        if board is None or not one.path:
            continue
        view = views.get(one.view_id)
        entries.append(
            contents.Entry(
                name=f"{board.name} - {view.name}" if view else board.name,
                description=board.description or "",
                path=one.path,
                updated=utcnow() if one is including else one.last_published_at,
            )
        )
    return contents.render(target.name, entries), []


def publish(
    db: Session,
    publication: Publication,
    *,
    user_id: str | None = None,
    replace_existing: bool = False,
) -> Publication:
    """Put the board on its destination, or bring the copy there up to date.

    On failure the publication is marked failed with the reason and the error
    is raised; whatever was online before stays online.
    """
    target = db.get(PublishTarget, publication.target_id)
    dashboard = db.get(Dashboard, publication.dashboard_id)
    if target is None or dashboard is None:
        raise NotReady("The destination or the dashboard no longer exists.")
    try:
        _refuse_if_archived(db, dashboard)
        if not publication.path and (target.settings or {}).get("contents_page"):
            raise NotReady(
                f"{target.name} keeps a list of its dashboards at the front of its folder, "
                "so a dashboard needs an address of its own there."
            )
        page = build_page(db, dashboard, publication.view_id)
        address = page_file(publication.path)
        with open_site(target) as site:
            existing = site.read_head(address)
            if existing is not None and not ours(existing) and not replace_existing:
                where = f"{publication.path}/" if publication.path else "the front of the folder"
                raise AddressTaken(
                    f"There is already a page at {where} on {target.name} that SurveyHQ did "
                    "not put there. Choose another address, or replace it."
                )
            writes = {address: page}
            index, notes = _contents_page(db, site, target, including=publication)
            if index is not None:
                writes[CONTENTS] = index
            notes = notes + site.apply(writes, [], f"Publish {dashboard.name}")
            url = join_url(site.folder_url(), publication.path)
            _remember_pages_url(target, site)
    except PublishError as exc:
        publication.status = "failed"
        publication.last_error = str(exc)
        raise
    publication.status = "published"
    publication.url = url
    publication.last_published_at = utcnow()
    publication.last_error = ""
    publication.size_bytes = len(page)
    publication.notes = notes
    publication.published_by = user_id
    return publication


def _remember_pages_url(target: PublishTarget, site: Any) -> None:
    learned = getattr(site, "pages_url", "")
    if learned and learned != (target.settings or {}).get("pages_url"):
        target.settings = {**(target.settings or {}), "pages_url": learned}


def unpublish(db: Session, publication: Publication, *, keep_files: bool = False) -> list[str]:
    """Take the board's page down and forget the publication.

    `keep_files` forgets it without touching the destination: for a server
    that no longer exists, or a page somebody wants to leave up by hand. A page
    at the address that this platform did not write is never deleted.
    """
    notes: list[str] = []
    target = db.get(PublishTarget, publication.target_id)
    if not keep_files and target is not None:
        address = page_file(publication.path)
        with open_site(target) as site:
            existing = site.read_head(address)
            deletes = [address] if existing is not None and ours(existing) else []
            if existing is not None and not ours(existing):
                notes.append(
                    f"The page at {publication.path or 'the front of the folder'} was not "
                    "written by SurveyHQ, so it was left there."
                )
            writes: dict[str, bytes] = {}
            index, more = _contents_page(db, site, target, excluding=publication)
            notes.extend(more)
            if index is not None:
                writes[CONTENTS] = index
            if deletes or writes:
                notes.extend(site.apply(writes, deletes, "Unpublish a dashboard"))
    db.delete(publication)
    # Gone from the next contents page too: taking down a board's copies one
    # after another reads the list again for each.
    db.flush()
    return notes


def take_down_all(db: Session, dashboard: Dashboard) -> list[str]:
    """Unpublish every copy of a board that is being deleted.

    Each one is tried, and a destination that cannot be reached does not stop
    the delete - the board is going either way. What could not be taken down is
    returned, so the person deleting it is told where it is still online.
    """
    problems: list[str] = []
    for publication in db.scalars(
        select(Publication).where(Publication.dashboard_id == dashboard.id)
    ).all():
        target = db.get(PublishTarget, publication.target_id)
        try:
            unpublish(db, publication)
        except Exception as exc:  # noqa: BLE001 - reported, and the delete goes on
            logger.warning("Could not take down publication %s: %s", publication.id, exc)
            where = publication.url or f"{target.name if target else 'a destination'}"
            problems.append(f"{where} ({exc})")
            db.delete(publication)
    return problems


def check(db: Session, target: PublishTarget) -> Check:
    """Connect to a destination and try writing to it.

    The one place a new SSH server is trusted: what it presents the first time
    it is tested is kept, and every later connection is checked against it.
    """
    with open_site(target, trust_new_host_key=True) as site:
        result = site.check()
        learned = getattr(site, "learned_host_key", "")
        _remember_pages_url(target, site)
    if learned:
        target.settings = {**(target.settings or {}), "host_key": learned}
    return result


@dataclass
class Republished:
    dashboard: str
    target: str
    ok: bool
    url: str = ""
    error: str = ""
    notes: list[str] = field(default_factory=list)


def republish_after_import(db: Session, dashboard_ids: set[str]) -> list[Republished]:
    """Bring the published copies of these boards up to date.

    Only those set to follow the data. Each failure is reported rather than
    raised: the import has already happened, and a web server that is down is
    a note beside it, not a failed import.
    """
    if not dashboard_ids:
        return []
    outcomes: list[Republished] = []
    publications = db.scalars(
        select(Publication).where(
            Publication.dashboard_id.in_(dashboard_ids), Publication.auto_republish.is_(True)
        )
    ).all()
    for publication in publications:
        dashboard = db.get(Dashboard, publication.dashboard_id)
        target = db.get(PublishTarget, publication.target_id)
        named = dashboard.name if dashboard else "a dashboard"
        where = target.name if target else "a destination"
        try:
            publish(db, publication)
        except Exception as exc:  # noqa: BLE001 - noted on the import, never fatal to it
            logger.warning("Republishing %s to %s failed: %s", named, where, exc)
            if not isinstance(exc, PublishError):
                publication.status = "failed"
                publication.last_error = str(exc)
            outcomes.append(Republished(named, where, False, publication.url, str(exc)))
            continue
        outcomes.append(
            Republished(named, where, True, publication.url, notes=list(publication.notes or []))
        )
    db.flush()
    return outcomes
