"""Archiving a project: the data goes, everything built on it stays.

Deleting a project was the only way to stop it costing disk, and disk is the
reason it comes up: a census is tens of gigabytes of Parquet, and a round that
was finished with two years ago is still paying for it. But deleting also threw
away the dashboards, the indicators, the quality rules and the script - months
of somebody's work, none of which is large, to reclaim space taken by something
else entirely.

So archiving separates the two. The microdata is removed; the description of it
is kept. Afterwards the project still lists its datasets with their variables,
row counts and labels, its dashboards still hold their widgets and colours, and
its script still says what it built - and every widget reads empty, because the
rows it counted are gone and pretending otherwise would be worse than saying so.

Re-importing the export fills it back in. That is why the datasets keep their
names and their variables: a replacement import matches on name, so the same
file uploaded again lands back in the same dataset, and the dashboards pointed
at it start working without anything being rebuilt.

What is not touched: boundary layers, dashboard backgrounds and logos. Those are
reference material somebody found and uploaded once, and are not what fills a
disk. Nor are the indicator snapshots, quality results or alerts - those are the
record of what the survey found, which is the part worth keeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import (
    Dashboard,
    Dataset,
    DatasetStatus,
    Project,
    ProjectStatus,
    ShareLink,
)
from app.services.datasets import dataset_directory

logger = get_logger(__name__)


@dataclass
class ArchiveOutcome:
    """What archiving took, so the page can say it rather than guess."""

    datasets: int = 0
    bytes_freed: int = 0
    links_closed: int = 0
    names: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"{self.datasets} dataset(s)", f"{human_size(self.bytes_freed)} freed"]
        if self.links_closed:
            parts.append(f"{self.links_closed} share link(s) closed")
        return ", ".join(parts)


@dataclass
class UnarchiveOutcome:
    links_reopened: int = 0
    datasets_waiting: int = 0


def human_size(count: int) -> str:
    """Bytes as a person would say them."""
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def measure(db: Session, project_id: str) -> int:
    """How much disk archiving this project would give back.

    Asked before anything is deleted, so the confirmation can say the number.
    Read off the files rather than from `file_size`, which records one Parquet
    and not the retained versions beside it.
    """
    total = 0
    for dataset in _datasets(db, project_id):
        total += _directory_size(dataset_directory(dataset.id))
    return total


def _directory_size(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())


def _datasets(db: Session, project_id: str) -> list[Dataset]:
    return list(db.scalars(select(Dataset).where(Dataset.project_id == project_id)))


def archive(db: Session, project: Project) -> ArchiveOutcome:
    """Remove the project's survey data and keep everything else."""
    from app.services.datasets import delete_dataset_files

    outcome = ArchiveOutcome()
    for dataset in _datasets(db, project.id):
        outcome.bytes_freed += _directory_size(dataset_directory(dataset.id))
        delete_dataset_files(dataset)

        dataset.status = DatasetStatus.archived
        # Cleared because it names a file that is gone. The counts and the
        # variables stay: they are the description of what was here, which is
        # the whole point of archiving rather than deleting.
        dataset.storage_path = ""
        dataset.file_size = 0
        # The retained versions were files in the same directory, so the list of
        # them is now a list of nothing. Left in place it would offer a rollback
        # that cannot happen.
        meta = dict(dataset.meta or {})
        meta.pop("retained_versions", None)
        dataset.meta = meta

        outcome.datasets += 1
        outcome.names.append(dataset.name)

    for link in open_links(db, project.id):
        # Closed rather than deleted, and marked as closed by this, so
        # unarchiving can reopen these and leave alone the ones somebody closed
        # on purpose. A live link showing a dashboard of blank charts reads as a
        # broken platform to whoever it was sent to.
        link.is_active = False
        link.closed_by_archive = True
        outcome.links_closed += 1

    project.status = ProjectStatus.archived
    project.archived_at = utcnow()
    db.flush()

    logger.info(
        "Archived project %s: %s datasets, %s bytes freed, %s links closed",
        project.name,
        outcome.datasets,
        outcome.bytes_freed,
        outcome.links_closed,
    )
    return outcome


def unarchive(db: Session, project: Project) -> UnarchiveOutcome:
    """Open the project for work again. The data stays gone until re-imported.

    Nothing here can bring the rows back - they were deleted, which was the
    point. What this does is let the project be worked on again, so that
    uploading the export lands in the datasets that are waiting for it.
    """
    outcome = UnarchiveOutcome()
    for link in db.scalars(
        select(ShareLink)
        .join(Dashboard, ShareLink.dashboard_id == Dashboard.id)
        .where(Dashboard.project_id == project.id, ShareLink.closed_by_archive.is_(True))
    ):
        link.is_active = True
        link.closed_by_archive = False
        outcome.links_reopened += 1

    outcome.datasets_waiting = sum(
        1
        for dataset in _datasets(db, project.id)
        if dataset.status == DatasetStatus.archived
    )

    project.status = ProjectStatus.active
    project.archived_at = None
    db.flush()
    return outcome


def open_links(db: Session, project_id: str) -> list[ShareLink]:
    return list(
        db.scalars(
            select(ShareLink)
            .join(Dashboard, ShareLink.dashboard_id == Dashboard.id)
            .where(Dashboard.project_id == project_id, ShareLink.is_active.is_(True))
        )
    )


def is_archived(project: Project | None) -> bool:
    return project is not None and project.status == ProjectStatus.archived


def refuse_if_archived(project: Project | None, doing: str) -> None:
    """Stop work that would need the data this project no longer has.

    Raised as a ValueError so the endpoints answer it the way they answer every
    other "that cannot be done to this" - a 422 with the reason - rather than
    each one growing its own check.
    """
    if is_archived(project):
        raise ValueError(
            f"'{project.name}' is archived, so {doing} is not possible. Unarchive "
            f"it first; its datasets are waiting for the export to be imported "
            f"again."
        )
