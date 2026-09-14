# Reliability upgrade

This change fixes Cramér’s V, rejects unsupported survey weights, retains dataset
versions, introduces import review and queued R runs, and makes database upgrades
and backups explicit.

## Upgrade an existing installation

1. Keep a verified backup of the database, data volume and encryption key.
2. Pull the new code and run `docker compose up -d --build`.
3. Compose runs the one-shot `migrate` service before the API and workers start.
   If migration fails, inspect `docker compose logs migrate`; the application
   does not start with an incomplete schema.

Outside Compose, run `python -m app.cli migrate` before starting the API or workers.
The first migration adopts existing tables, adds supported missing columns and
indexes, backfills usernames, and records the baseline revision. An unsafe column
addition or invalid unique index stops the migration and must be resolved first.
Future schema changes belong in new Alembic revisions; do not edit the baseline.
Use `alembic revision --autogenerate -m "description"` from `backend`, review the
revision and test upgrading a populated database before release. Downgrading the
baseline is deliberately refused: restore the verified pre-upgrade backup.

## Statistics

Weights are supported for counts, shares, sums and means. Medians, percentiles,
standard deviations, distinct counts and extrema reject a weight parameter.
Explore disables the weight selector for those calculations, and box plots are
explicitly unweighted. Existing saved queries with unsupported weights report a
validation error; edit them to remove the weight or calculate the statistic in R.
This release does not add complex survey variance estimation.

## Import review and retained versions

The upload dialog now uses **Upload and review**. The background worker prepares
candidate files and shows row changes, added/removed variables, changed types or
labels, duplicate complete rows, affected indicators and import warnings. Choose
**Accept import** to publish, or **Discard import** to remove the candidates.
If the current dataset changed since the review, acceptance is refused; upload
again to review against the new version. Scheduled Survey Solutions imports and
existing API clients continue their automatic workflow.

Every writer uses a new Parquet path. A database rollback leaves the previous
committed path readable. The dataset version participates in optimistic conflict
checks, so two simultaneous refreshes cannot silently overwrite each other.
Previous versions are available on the dataset page under **Previous dataset
versions**, or at `GET /api/v1/datasets/{id}/versions`. Restoring a version retains
the current version too and rebuilds dependent merges.

Retained snapshots are not automatically pruned in this release. Plan storage
for repeated exports; do not delete files from the data volume while the service
is running. Discarding a reviewed import removes its candidate files. Failed or
abandoned preparations can leave unreferenced files; safe retention/garbage
collection is a follow-up operational improvement.

## R execution

The R interface submits jobs to `POST /api/v1/projects/{id}/queue-run`. Jobs retain
the submitted code, status, result and error and can be inspected in Background
jobs. A cross-process project lock protects the persistent working directory
until the transaction commits or rolls back. A busy queued run retries; direct
legacy run endpoints return a conflict. Workspace clearing uses the same lock.
Each execution also retains its script, input dataset versions and result in a
separate `r-runs/{project}/{run}` directory. The persistent project workspace is
shared sequentially so existing saved objects and libraries continue to work.
The existing Landlock/seccomp sandbox remains the default when R is enabled.

## Backup and restore

`make backup` temporarily stops all running application writers, including
`worker-monitoring`, while capturing both Postgres and the data volume. Writers
are restarted even if backup fails. A data-copy error is fatal and cannot create
a successful empty backup. Data is streamed to the host to avoid bind-mount
permissions on temporary directories. Archives include SHA-256 checksums.

`make restore FILE=...` requires the complete checksummed backup format created
by this version. Keep older backups for restoration with their matching release.
Restore validates the archive and checks the encryption key before stopping all
writers. PostgreSQL errors stop restore immediately. On failure, writers remain
stopped so a partial restore is not served. Resolve the error and retry; after a
successful restore, migrations run and the application services restart.

Backups contain sensitive survey data and the environment file. They are created
with restrictive permissions and should be held in the deployment's protected
backup location.

## Verification

Backend regression tests cover rectangular/transposed contingency tables,
unsupported weights, failure after a file write, rollback, retained-version
restore, review/accept conflicts, queued R results, project locking, populated
legacy migration and backup/restore scripts. CI additionally runs the full
PostgreSQL suite and sandbox tests, a real browser workflow from upload through
anonymous dashboard sharing, and backup/restore of the populated Docker stack.
