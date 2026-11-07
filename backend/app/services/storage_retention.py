"""Restore-point limits, and safe removal of dataset files nothing needs.

Every refresh writes a new Parquet file and keeps a small JSON record of the
version it replaced (dataset_versions.remember_version), so a dataset can be
put back. Nothing removed those, and a failed or rolled-back import could
leave its new files behind with nothing pointing at them. This works out which
files are still needed and removes the rest, carefully:

- **Reachability first.** A file is needed if a dataset reads it now
  (``storage_path``), if a restore point that is still listed refers to it, or
  if an import waiting for review will publish it. Anything else under a
  dataset's folder is unused.
- **Restore-point limit.** Each dataset keeps its newest
  ``dataset_versions_keep`` restore points. Older ones are taken off its list
  first (an optimistic update: a dataset that changed meanwhile is skipped),
  and only then do their files become unused.
- **Grace period.** An unused file is never removed until it is at least
  ``storage_cleanup_grace_hours`` old, because an import that is still running
  has written files it hasn't committed yet. The minimum is longer than any
  job may run.
- **Checked again just before deleting.** The references are read afresh from
  the database immediately before removal, and a file that has become needed
  in the meantime is kept.
- **One at a time.** A cross-process lock stops two clean-ups overlapping.
- **Report before delete.** By default the nightly run only reports what it
  would remove. ``storage_cleanup_delete`` turns removal on.

Only ``data-*.parquet`` files, ``versions/*.json`` records and the folders of
datasets that no longer exist are ever touched, and only under the datasets
directory.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import settings
from app.core.logging import get_logger
from app.services import preferences

logger = get_logger(__name__)

#: The latest report, for Administration -> Background jobs -> Storage.
REPORT_NAME = "storage-report.json"
#: Below this share of the disk free, administrators are warned.
LOW_DISK_FREE_PERCENT = 10

LIMIT = "restore point past the limit"
UNUSED = "not used by any dataset, restore point or import waiting for review"
UNLISTED = "record of a version that was never kept (a failed or rolled-back import)"
GONE = "left in the folder of a dataset that no longer exists"


@dataclass
class Removal:
    path: str
    bytes: int
    reason: str
    dataset_id: str


@dataclass
class Report:
    checked_at: str
    deleted: bool
    keep_versions: int
    grace_hours: int
    removable: list[Removal] = field(default_factory=list)
    removed_files: int = 0
    removed_bytes: int = 0
    pruned_versions: int = 0
    skipped_changed: list[str] = field(default_factory=list)
    recent_unused_files: int = 0
    recent_unused_bytes: int = 0
    usage: dict[str, Any] = field(default_factory=dict)
    disk: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["removable_files"] = len(self.removable)
        data["removable_bytes"] = sum(item.bytes for item in self.removable)
        by_reason: dict[str, dict[str, int]] = {}
        for item in self.removable:
            entry = by_reason.setdefault(item.reason, {"files": 0, "bytes": 0})
            entry["files"] += 1
            entry["bytes"] += item.bytes
        data["by_reason"] = by_reason
        # The full list can run to thousands of paths; the page needs a sample.
        data["removable"] = data["removable"][:200]
        return data


# --- What is needed ------------------------------------------------------------


def _key(path: str | Path | None) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


@dataclass
class VersionRecord:
    json_path: str
    parquet_path: str
    version: int


def _listed_versions(dataset) -> list[VersionRecord]:
    """The restore points a dataset lists whose record can be read."""
    found = []
    for filename in (dataset.meta or {}).get("retained_versions") or []:
        file = Path(filename)
        if not file.is_file():
            continue
        try:
            snapshot = json.loads(file.read_text(encoding="utf-8"))
            found.append(
                VersionRecord(str(file), str(snapshot["parquet_path"]), int(snapshot["version"]))
            )
        except (OSError, ValueError, KeyError, TypeError):
            # Unreadable: kept, and so is whatever it might point at. Never
            # guess at removing something because its record is damaged.
            found.append(VersionRecord(str(file), "", -1))
    return found


def over_limit(dataset, keep: int) -> list[VersionRecord]:
    """Restore points past the newest ``keep`` shown on the dataset's page.

    Mirrors dataset_versions.list_versions, which shows each version below the
    current one once (the first record listed for it) and only if its file is
    still there. Anything it would not show is left as it is.
    """
    if keep <= 0:
        return []
    shown: dict[int, VersionRecord] = {}
    for record in _listed_versions(dataset):
        if 0 <= record.version < (dataset.version or 0) and Path(record.parquet_path).is_file():
            shown.setdefault(record.version, record)
    newest_first = sorted(shown.values(), key=lambda r: r.version, reverse=True)
    return newest_first[keep:]


def _pending_candidates(db: Session) -> set[str]:
    """Files an import waiting for review will publish if it is accepted."""
    from app.models import Job

    needed = set()
    for params in db.scalars(select(Job.params)).all():
        for item in (params or {}).get("candidates") or []:
            path = ((item or {}).get("snapshot") or {}).get("parquet_path")
            if path:
                needed.add(_key(path))
    return needed


@dataclass
class Needed:
    files: set[str]
    dataset_ids: set[str]
    pruned_json: set[str]


def needed_files(db: Session, keep: int) -> Needed:
    """Every file a dataset, a kept restore point or a pending review needs.

    Restore points past the limit are counted as already let go, so a dry run
    reports what a real run would remove.
    """
    from app.models import Dataset

    files: set[str] = set()
    ids: set[str] = set()
    pruned: set[str] = set()
    # populate_existing: a dataset already loaded in this session is read
    # again, not served from memory, so a just-committed import is seen.
    for dataset in db.scalars(
        select(Dataset).execution_options(populate_existing=True)
    ).all():
        ids.add(dataset.id)
        files.add(_key(dataset.storage_path))
        dropping = {record.json_path for record in over_limit(dataset, keep)}
        pruned |= {_key(path) for path in dropping}
        for record in _listed_versions(dataset):
            if record.json_path in dropping:
                continue
            files.add(_key(record.json_path))
            files.add(_key(record.parquet_path))
    files |= _pending_candidates(db)
    files.discard("")
    return Needed(files, ids, pruned)


# --- What could go -------------------------------------------------------------


def _candidates(root: Path) -> list[tuple[Path, str]]:
    """The only kinds of file this may ever remove, with the dataset they sit under."""
    found = []
    if not root.is_dir():
        return found
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in sorted(directory.glob("data-*.parquet")):
            found.append((path, directory.name))
        for path in sorted((directory / "versions").glob("*.json")):
            found.append((path, directory.name))
    return found


def _reason(path: Path, dataset_id: str, needed: Needed, released: set[str]) -> str:
    key = _key(path)
    if dataset_id not in needed.dataset_ids:
        return GONE
    if key in needed.pruned_json or key in released:
        return LIMIT
    return UNLISTED if path.suffix == ".json" else UNUSED


def _released_parquet(db: Session, keep: int, released_json: set[str]) -> set[str]:
    """The Parquet files of restore points past the limit, whether still listed or just let go."""
    from app.models import Dataset

    found = set()
    for dataset in db.scalars(select(Dataset)).all():
        found |= {_key(record.parquet_path) for record in over_limit(dataset, keep)}
    for json_path in released_json:
        try:
            found.add(_key(json.loads(Path(json_path).read_text(encoding="utf-8"))["parquet_path"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def plan(
    db: Session,
    now: dt.datetime,
    keep: int,
    grace: dt.timedelta,
    released: set[str] | None = None,
) -> Report:
    """What could be removed now, without removing anything.

    ``released`` is the restore-point records this run has already taken off
    their datasets' lists, so they are reported as past the limit.
    """
    released = {_key(path) for path in (released or set())}
    needed = needed_files(db, keep)
    limit_parquet = _released_parquet(db, keep, released)
    report = Report(
        checked_at=now.isoformat(),
        deleted=False,
        keep_versions=keep,
        grace_hours=int(grace.total_seconds() // 3600),
    )
    for path, dataset_id in _candidates(settings.datasets_path):
        if path.is_symlink() or _key(path) in needed.files:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        modified = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.UTC)
        if now - modified < grace:
            report.recent_unused_files += 1
            report.recent_unused_bytes += stat.st_size
            continue
        reason = _reason(path, dataset_id, needed, released | limit_parquet)
        report.removable.append(Removal(str(path), stat.st_size, reason, dataset_id))
    report.pruned_versions = len(needed.pruned_json) + len(released)
    report.usage = usage(db)
    report.disk = disk()
    return report


# --- Usage ---------------------------------------------------------------------


def usage(db: Session) -> dict[str, Any]:
    """How much disk the datasets take: in use, as restore points, and the rest."""
    from app.models import Dataset

    root = settings.datasets_path
    total = sum(_size(path) for path in root.rglob("*") if path.is_file()) if root.is_dir() else 0
    current = 0
    restore = 0
    largest = []
    for dataset in db.scalars(select(Dataset)).all():
        now_reading = _key(dataset.storage_path)
        size = _size(Path(dataset.storage_path)) if dataset.storage_path else 0
        current += size
        seen = {now_reading}
        kept = 0
        for record in _listed_versions(dataset):
            key = _key(record.parquet_path)
            if key and key not in seen:
                seen.add(key)
                kept += _size(Path(record.parquet_path))
        restore += kept
        largest.append(
            {
                "id": dataset.id,
                "name": dataset.name,
                "current_bytes": size,
                "restore_point_bytes": kept,
            }
        )
    largest.sort(key=lambda row: row["current_bytes"] + row["restore_point_bytes"], reverse=True)
    return {
        "datasets_bytes": total,
        "current_bytes": current,
        "restore_point_bytes": restore,
        "other_bytes": max(total - current - restore, 0),
        "largest": largest[:10],
    }


def disk() -> dict[str, Any]:
    try:
        measured = shutil.disk_usage(settings.storage_path)
    except OSError:
        return {}
    free_percent = round(100 * measured.free / measured.total, 1) if measured.total else 0.0
    return {
        "total_bytes": measured.total,
        "used_bytes": measured.used,
        "free_bytes": measured.free,
        "free_percent": free_percent,
        "low": free_percent < LOW_DISK_FREE_PERCENT,
    }


# --- Doing it ------------------------------------------------------------------


def _prune_lists(db: Session, keep: int, report: Report) -> set[str]:
    """Take restore points past the limit off each dataset's list. Returns their records.

    Saved one dataset at a time. The dataset's version is checked on update, so
    one that an import changed in the meantime is skipped this time round.
    """
    from app.models import Dataset

    let_go: set[str] = set()
    for dataset_id in db.scalars(select(Dataset.id)).all():
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            continue
        dropping = {record.json_path for record in over_limit(dataset, keep)}
        if not dropping:
            continue
        meta = dict(dataset.meta or {})
        meta["retained_versions"] = [
            path for path in meta.get("retained_versions") or [] if path not in dropping
        ]
        dataset.meta = meta
        try:
            db.commit()
        except StaleDataError:
            db.rollback()
            report.skipped_changed.append(dataset_id)
            continue
        let_go |= dropping
    return let_go


def _within(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(settings.datasets_path.resolve())
    except OSError:
        return False


class CleanupBusy(RuntimeError):
    """Another storage clean-up is running."""


def run(
    db: Session,
    *,
    delete: bool,
    now: dt.datetime | None = None,
    keep: int | None = None,
    grace: dt.timedelta | None = None,
) -> Report:
    """Work out what can go and, if ``delete``, remove it. Saves and returns the report."""
    now = now or dt.datetime.now(dt.UTC)
    keep = int(preferences.value("dataset_versions_keep")) if keep is None else keep
    if grace is None:
        grace = dt.timedelta(hours=int(preferences.value("storage_cleanup_grace_hours")))

    if not delete:
        report = plan(db, now, keep, grace)
        db.rollback()
        save(report)
        return report

    from app.db.session import SessionLocal
    from app.services.operation_lock import OperationBusy, acquire

    # A session of its own holds the lock for the whole run: the work below
    # commits per dataset, which would release a lock taken on `db`.
    holder = SessionLocal()
    try:
        try:
            acquire(holder, "storage-cleanup")
        except OperationBusy as exc:
            raise CleanupBusy("A storage clean-up is already running.") from exc

        report = Report(
            checked_at=now.isoformat(),
            deleted=True,
            keep_versions=keep,
            grace_hours=int(grace.total_seconds() // 3600),
        )
        released = _prune_lists(db, keep, report)

        # Read again now the lists are saved, and once more immediately before
        # anything is removed. Each read starts a new transaction, so what an
        # import committed in between is seen.
        db.rollback()
        final = plan(db, now, keep, grace, released)
        db.rollback()
        still_needed = needed_files(db, keep).files
        removed: list[Removal] = []
        for item in final.removable:
            path = Path(item.path)
            if _key(path) in still_needed or not _within(path) or path.is_symlink():
                continue
            try:
                modified = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
            except OSError:
                continue
            if now - modified < grace:
                continue
            path.unlink(missing_ok=True)
            removed.append(item)
        _remove_gone_folders(db, removed, now, grace)
        db.rollback()

        report.removable = removed
        report.removed_files = len(removed)
        report.removed_bytes = sum(item.bytes for item in removed)
        report.pruned_versions = len(released)
        report.recent_unused_files = final.recent_unused_files
        report.recent_unused_bytes = final.recent_unused_bytes
        report.usage = usage(db)
        report.disk = disk()
        db.rollback()
    finally:
        holder.rollback()
        holder.close()
    save(report)
    logger.info(
        "Storage clean-up removed %s file(s), %s bytes", report.removed_files, report.removed_bytes
    )
    return report


def _remove_gone_folders(
    db: Session, removed: list[Removal], now: dt.datetime, grace: dt.timedelta
) -> None:
    """The folder of a dataset that no longer exists, once nothing in it is needed."""
    from app.models import Dataset

    for dataset_id in {item.dataset_id for item in removed if item.reason == GONE}:
        folder = settings.datasets_path / dataset_id
        if not folder.is_dir() or folder.is_symlink() or not _within(folder):
            continue
        if db.get(Dataset, dataset_id) is not None:
            continue
        left = [p for p in folder.rglob("*") if p.is_file()]
        # Only the small summary file a dataset's monitoring writes may remain,
        # and only if it too is past the grace period.
        if any(p.name != "monitoring-summary.json" for p in left):
            continue
        if any(
            now - dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.UTC) < grace for p in left
        ):
            continue
        shutil.rmtree(folder, ignore_errors=True)


# --- The saved report ----------------------------------------------------------


def report_path() -> Path:
    return settings.storage_path / REPORT_NAME


def save(report: Report) -> None:
    try:
        report_path().write_text(json.dumps(report.as_dict()), encoding="utf-8")
    except OSError:
        logger.warning("could not save the storage report", exc_info=True)


def latest() -> dict[str, Any] | None:
    try:
        return json.loads(report_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
