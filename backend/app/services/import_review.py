"""Prepare immutable candidates, then publish only the exact reviewed versions."""

from __future__ import annotations

from sqlalchemy import select

from app.db.base import utcnow
from app.models import Dataset, DatasetSource, Indicator, JobStatus, Role
from app.services.dataset_versions import as_ingest, describe
from app.services.datasets import _apply_ingest, create_dataset_record
from app.services.ingest import IngestError
from app.services.project_script import without_grant
from app.services.projects import can_edit


def baseline(db, project_id):
    return {
        d.id: describe(d)
        for d in db.scalars(select(Dataset).where(Dataset.project_id == project_id))
    }


def prepare(db, datasets, before):
    candidates, changes = [], []
    for dataset in datasets:
        snapshot = describe(dataset)
        old = before.get(dataset.id, {})
        a = {v["name"]: v for v in old.get("variables", [])}
        b = {v["name"]: v for v in snapshot["variables"]}
        changed = [
            name
            for name in a.keys() & b.keys()
            if any(
                a[name].get(key) != b[name].get(key)
                for key in ("storage_type", "label", "value_labels")
            )
        ]
        from app.services.columnar import connect, quote_path

        con = connect()
        try:
            distinct = con.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT * FROM "
                f"read_parquet({quote_path(dataset.storage_path)}))"
            ).fetchone()[0]
        finally:
            con.close()
        changes.append(
            {
                "name": dataset.name,
                "before_rows": old.get("row_count", 0),
                "after_rows": dataset.row_count,
                "added_variables": sorted(b.keys() - a.keys()),
                "removed_variables": sorted(a.keys() - b.keys()),
                "changed_variables": sorted(changed),
                "duplicate_rows": dataset.row_count - distinct,
                "affected_indicators": list(
                    db.scalars(select(Indicator.name).where(Indicator.dataset_id == dataset.id))
                ),
                "warnings": snapshot["warnings"],
            }
        )
        candidates.append(
            {
                "id": dataset.id,
                "expected_version": old.get("version"),
                "expected_variables": old.get("variables", []),
                "snapshot": snapshot,
                "name": dataset.name,
                "description": dataset.description,
                "source_ref": dataset.source_ref,
                "project_id": dataset.project_id,
                "tags": dataset.tags,
                # Without the rebuild grant: these candidates are parked in
                # the job's parameters, which `/system/jobs` hands back, so a
                # manager of this project would otherwise read the ids of the
                # projects claiming the dataset - ones they may not reach.
                #
                # Dropping it also stops a stale grant coming back. Accepting
                # merges this over what the dataset holds, so a review
                # prepared before the grant was released would otherwise
                # restore it, reviving a permission somebody had given up.
                "meta": {
                    k: v
                    for k, v in without_grant(dataset.meta).items()
                    if k != "retained_versions"
                },
            }
        )
    return candidates, changes


def accept(db, job, user):
    if job.created_by != user.id and not user.has_role(Role.admin):
        raise IngestError("Import review not found")
    if job.status != JobStatus.success or not job.result.get("review"):
        raise IngestError("This import is not awaiting review")
    params = dict(job.params)
    candidates = params.get("candidates", [])
    if not candidates:
        raise IngestError("There are no datasets to import")
    targets = []
    for item in candidates:
        if not can_edit(db, user, item["project_id"], Role.manager):
            raise IngestError("Project access is no longer available")
        target = db.scalar(select(Dataset).where(Dataset.id == item["id"]).with_for_update())
        if item["expected_version"] is not None:
            if (
                target is None
                or target.version != item["expected_version"]
                or target.project_id != item["project_id"]
                or describe(target)["variables"] != item["expected_variables"]
            ):
                raise IngestError(
                    "Data changed after this review. Upload again to review the current changes."
                )
        else:
            from app.services.datasets import ARCHIVE_MEMBER_KEY, find_archive_sibling

            key = item["meta"].get(ARCHIVE_MEMBER_KEY)
            sibling = find_archive_sibling(db, key, item["project_id"]) if key else None
            if target is not None or sibling is not None:
                raise IngestError("A dataset was created after this review. Upload again.")
        targets.append(target)
    published = []
    for item, target in zip(candidates, targets, strict=True):
        if target is None:
            target = create_dataset_record(
                db,
                name=item["name"],
                description=item["description"],
                source=DatasetSource.upload,
                source_ref=item["source_ref"],
                tags=item["tags"],
                created_by=user.id,
                project_id=item["project_id"],
                dataset_id=item["id"],
            )
        target.meta = {**(target.meta or {}), **item["meta"]}
        _apply_ingest(db, target, as_ingest(item["snapshot"]))
        published.append(target)
    from app.services.pipeline import AFTER_IMPORT, Progress, after_import

    # Publishing a reviewed import replaces the data under each dataset, so
    # what was recorded against it is run again - a generated variable is not
    # in the file that was reviewed either - and then everything built on it
    # follows: merges, scripts, indicators, in that order. Before the counts
    # below, which a `drop if` in the history would otherwise leave reporting
    # the file's rows rather than the dataset's. See pipeline.after_import.
    ids = [d.id for d in published]
    # Not saved step by step: this runs in the request that accepted the
    # review, which commits once at the end. The steps are recorded on the job
    # with everything else.
    progress = Progress(None, AFTER_IMPORT)
    aftermath = after_import(db, changed=ids, replaced=ids, replay=True, progress=progress)
    warnings: list[str] = aftermath.notes()
    read = {"key": "read", "label": "Read the uploaded files", "status": "done",
            "detail": "Reviewed and accepted", "items": []}
    job.stages = [read, *progress.stages]
    db.flush()
    for entry in published:
        db.refresh(entry)

    summary = {
        "datasets": [{"id": d.id, "name": d.name, "rows": d.row_count} for d in published],
        "rows": sum(d.row_count for d in published),
        "warnings": warnings,
        "created": [],
        "replaced": [],
        "appended": [],
        "skipped": [],
        "review": False,
    }
    params.pop("candidates", None)
    job.params, job.result, job.finished_at = params, summary, utcnow()
    return summary
