"""A project's R workspace.

A project is an environment, not a folder of files. The scripts that prepare a
survey's data read several of its datasets and write several others - a recode
reads the household file and writes the person file - so pinning a script to
one dataset was always a fiction, and it meant a two-file job had to be written
twice or not at all.

So R runs against the project. Every ready dataset in it is a CSV in the
workspace, a script reads the ones it wants and writes back the ones it makes,
and the working directory survives between runs: an object saved with saveRDS,
a lookup table written to disk, and a package installed into the project's own
library are all still there next time. That is what makes it an environment
rather than a series of unrelated runs.

THE CONTRACT
============
Two functions, defined before the script runs:

    read_dataset("household")            a data frame, by name or by slug
    write_dataset(df, "Adults")          create or replace a dataset here

and one value:

    datasets                             a data frame of what is available

Everything else is base R and whatever the administrator installed.

WHAT THIS IS NOT
================
This is not a sandbox. An R script is a program, and a program can read files
the server can read, open sockets the server can open, and call system(). There
is no blocklist of dangerous calls, because a blocklist over a language with
eval(parse(text=)) would only be a promise nobody can keep. The containment -
a wall-clock timeout, an
address-space cap, a working directory of its own - stops a runaway script, not
a hostile one. It is off unless an administrator turns it on, and only a
manager of the project can reach it.

The workspace persisting is a deliberate widening of that: files a script
leaves are readable by the next script anyone runs in the same project. A
project is a trust boundary here, and the people who can run R in one are the
people who could already read everything in it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import resource
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import Dataset, Project, ProjectScript
from app.services.datasets import (
    _apply_ingest,
    create_dataset_record,
    dataset_directory,
    dataset_is_queryable,
    unique_slug,
)
from app.services.ingest import ingest_frame
from app.services.sharing import as_utc

logger = get_logger(__name__)

# Where things sit inside a workspace. `data` is written by the platform and
# read by scripts; `out` is the other way round. Everything else in the
# workspace belongs to whoever put it there.
DATA_DIR = "data"
OUT_DIR = "out"
MANIFEST = "susodash_written.json"
SCRIPT = "susodash_project.R"
LIB_DIR = "rlibs"


# Printed output kept from a run. A script that prints a whole data frame can
# produce megabytes, and none of it past the first screenful helps.
MAX_LOG = 20_000


class RError(RuntimeError):
    """R could not be run, or the script failed."""


class ProjectRError(RError):
    """The workspace could not be prepared, or the script failed."""


# -- where R is, and whether it may be used ---------------------------------

def binary() -> str | None:
    """Where Rscript is, if it is anywhere."""
    settings = get_settings()
    named = (settings.r_binary or "Rscript").strip()
    return shutil.which(named)


def unavailable_reason() -> str:
    """Why R cannot be run here, or an empty string when it can.

    Two different answers, because they need two different actions: install R,
    or turn the setting on. One message saying "unavailable" would send half of
    the people who hit it to the wrong place.
    """
    settings = get_settings()
    if not settings.r_scripts_enabled:
        return (
            "Running R is switched off on this server. An administrator turns it "
            "on with R_SCRIPTS_ENABLED=true, having read what it allows: an R "
            "script is a program, and it runs with the server's own permissions."
        )
    if not binary():
        return (
            "R is not installed on this server. Install it (apt-get install "
            "r-base-core, or the r-base package for your system) and restart."
        )
    return ""


def available() -> bool:
    return not unavailable_reason()


def _environment(room: Path) -> dict[str, str]:
    """A small environment for the child.

    HOME points at the working directory, which is thrown away: an R that reads
    or writes a history, a workspace or a profile does it somewhere temporary
    rather than in the account the server runs as. The library path is left
    alone, so packages an administrator installed are available - "base R" is
    the floor here, not a ceiling.
    """
    keep = ("PATH", "LANG", "LC_ALL", "TZ", "R_HOME", "R_LIBS", "R_LIBS_SITE")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["HOME"] = str(room)
    env["TMPDIR"] = str(room)
    # Nothing in a script should be waiting on a prompt or a download.
    env["R_LIBS_USER"] = str(room / "rlibs")
    return env


def _limits() -> None:  # pragma: no cover - runs in the forked child
    """Caps applied in the child, between fork and exec.

    An address-space limit is what stops a script that allocates until the
    machine dies from taking the platform with it; the timeout above handles
    one that merely never finishes. Both are about a script that goes wrong,
    not one written to do harm - see the module docstring.
    """
    settings = get_settings()
    limit = max(256, settings.r_memory_mb) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    # No core dumps: a crashed R inside a container would otherwise write one
    # the size of its heap into a directory nobody looks at.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _trim(out: str, err: str) -> str:
    """What the script printed, both streams, short enough to read."""
    text = "\n".join(part.strip() for part in (out, err) if part and part.strip())
    if len(text) <= MAX_LOG:
        return text
    return text[:MAX_LOG] + f"\n... and {len(text) - MAX_LOG:,} more characters"



@dataclass
class ProjectRResult:
    """What one run did."""

    message: str
    output: str = ""
    # Datasets the script wrote, as {"name": ..., "id": ..., "rows": ...}
    written: list[dict[str, object]] = field(default_factory=list)
    # Files the script left in the workspace, so the panel can list them.
    files: list[str] = field(default_factory=list)


def workspace(project_id: str) -> Path:
    """The project's own directory, made if it is not there yet."""
    room = get_settings().workspaces_path / project_id
    (room / DATA_DIR).mkdir(parents=True, exist_ok=True)
    (room / OUT_DIR).mkdir(parents=True, exist_ok=True)
    (room / LIB_DIR).mkdir(parents=True, exist_ok=True)
    return room


def forget(project_id: str) -> None:
    """Throw the workspace away, with everything anyone left in it."""
    shutil.rmtree(get_settings().workspaces_path / project_id, ignore_errors=True)


def project_datasets(db: Session, project_id: str) -> list[Dataset]:
    return [
        dataset
        for dataset in db.scalars(
            select(Dataset).where(Dataset.project_id == project_id).order_by(Dataset.name)
        ).all()
        if dataset_is_queryable(dataset)
    ]


def sync_inputs(db: Session, project_id: str) -> list[Dataset]:
    """Put every dataset in the project into the workspace as a CSV.

    Only the ones that have changed: a project with twenty files would
    otherwise spend most of a run rewriting nineteen CSVs nobody asked for.
    Staleness is the dataset's own updated_at against the file's timestamp,
    which covers a re-import, an append and a script that wrote it.
    """
    room = workspace(project_id)
    ready = project_datasets(db, project_id)
    for dataset in ready:
        target = room / DATA_DIR / f"{dataset.slug}.csv"
        # SQLite hands back a naive timestamp and PostgreSQL an aware one, and
        # comparing the two raises rather than answering; as_utc reads a naive
        # value as UTC, which is what the platform stores everywhere.
        changed = as_utc(dataset.updated_at)
        if target.exists() and changed is not None:
            written = dt.datetime.fromtimestamp(target.stat().st_mtime, dt.UTC)
            if written >= changed:
                continue
        pd.read_parquet(dataset.storage_path).to_csv(target, index=False)
    # A dataset that has left the project should not go on being readable in it.
    keep = {f"{dataset.slug}.csv" for dataset in ready}
    for stale in (room / DATA_DIR).glob("*.csv"):
        if stale.name not in keep:
            stale.unlink(missing_ok=True)
    return ready


def run(
    db: Session,
    project: Project,
    code: str,
    *,
    created_by: str | None = None,
) -> ProjectRResult:
    """Run one script in the project's workspace and keep what it wrote."""
    reason = unavailable_reason()
    if reason:
        raise ProjectRError(reason)
    code = code.strip()
    if not code:
        raise ProjectRError(
            'Type some R, for example: write_dataset(read_dataset("household"), "Copy")'
        )

    ready = sync_inputs(db, project.id)
    room = workspace(project.id)
    # Cleared before rather than after: a run that fails halfway leaves its
    # half-written output behind, and the next run must not adopt it.
    for leftover in (room / OUT_DIR).iterdir():
        if leftover.is_file():
            leftover.unlink(missing_ok=True)

    (room / SCRIPT).write_text(_wrap(code, ready), encoding="utf-8")
    printed = _execute(room)
    written = _collect(db, project, room, created_by)

    files = sorted(
        str(path.relative_to(room))
        for path in room.rglob("*")
        if path.is_file() and not is_plumbing(path.relative_to(room))
    )
    made = ", ".join(str(item["name"]) for item in written)
    return ProjectRResult(
        message=(
            f"Ran against {len(ready)} "
            + ("dataset" if len(ready) == 1 else "datasets")
            + (f", wrote {made}" if made else ", wrote nothing back")
        ),
        output=printed,
        written=written,
        files=files[:200],
    )


def run_saved(
    db: Session, project: Project, script: ProjectScript, created_by: str | None = None
) -> ProjectRResult:
    """Run a saved script and record on it how the run went."""
    try:
        result = run(db, project, script.code, created_by=created_by)
    except RError as exc:
        script.last_run_at = utcnow()
        script.last_ok = False
        script.last_output = str(exc)[:MAX_LOG]
        raise
    script.last_run_at = utcnow()
    script.last_ok = True
    script.last_output = (result.output or result.message)[:MAX_LOG]
    return result


def run_on_import(db: Session, project_id: str | None, created_by: str | None = None) -> list[str]:
    """Re-run the scripts a project marked "after each import".

    A derived variable is not in the export that arrives, so without this it
    disappears on exactly the upload the platform exists to make routine. Run
    in the order the project keeps them in, because they build on each other.

    Failures are reported, not raised: an import that succeeded should not be
    reported as failed because a script written weeks ago no longer matches the
    data. The warning says which script and why.
    """
    if not project_id or unavailable_reason():
        return []
    project = db.get(Project, project_id)
    if project is None:
        return []
    scripts = list(
        db.scalars(
            select(ProjectScript)
            .where(
                ProjectScript.project_id == project_id,
                ProjectScript.run_on_import.is_(True),
            )
            .order_by(ProjectScript.display_order, ProjectScript.name)
        ).all()
    )
    notes: list[str] = []
    for script in scripts:
        try:
            result = run_saved(db, project, script, created_by)
        except RError as exc:
            logger.warning("Project script %s failed on import: %s", script.name, exc)
            notes.append(f"'{script.name}' did not run: {exc}")
            continue
        notes.append(f"Ran '{script.name}': {result.message}")
    return notes


# -- the R side -------------------------------------------------------------


def r_name(slug: str) -> str:
    """The slug as something R can hold in a variable name, if anyone wants to."""
    cleaned = re.sub(r"[^A-Za-z0-9_.]", "_", slug)
    return cleaned if re.match(r"^[A-Za-z.]", cleaned) else f"d_{cleaned}"


def _wrap(code: str, ready: list[Dataset]) -> str:
    """The script with the workspace's own vocabulary put in front of it.

    Written as a file rather than passed with -e so that an error reports the
    line it happened on, and the preamble is one line so the numbers R reports
    differ from what the person typed by exactly one.
    """
    preamble = "; ".join(
        [
            f".susodash_data <- {_r_string(DATA_DIR)}",
            f".susodash_out <- {_r_string(OUT_DIR)}",
            f".susodash_manifest <- {_r_string(MANIFEST)}",
            ".susodash_written <- character(0)",
            f"datasets <- utils::read.csv(text = {_r_string(_catalogue(ready))}, "
            "stringsAsFactors = FALSE)",
            _READER,
            _WRITER,
        ]
    )
    # Written even when the script wrote nothing, so an empty manifest and a
    # crashed run are told apart by the collector rather than guessed at.
    postamble = (
        'writeLines(paste0("[", paste(.susodash_written, collapse = ","), "]"), '
        "file.path(.susodash_out, .susodash_manifest))"
    )
    return f"{preamble}\n{code}\n{postamble}\n"


def _catalogue(ready: list[Dataset]) -> str:
    """The available datasets as CSV text.

    CSV rather than JSON because base R reads it with no package installed, and
    "base R is the floor" is the promise the whole feature is built on.
    """
    rows = pd.DataFrame(
        [
            {"name": d.name, "slug": d.slug, "rows": int(d.row_count or 0)}
            for d in ready
        ],
        columns=["name", "slug", "rows"],
    )
    return rows.to_csv(index=False)


def _r_string(value: str) -> str:
    """A Python string as an R string literal."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r")
    return f'"{escaped}"'


# Both written on one line: the preamble is joined into a single line so that
# an error R reports is at the line the person typed, plus one.
_READER = (
    "read_dataset <- function(which) {"
    " row <- datasets[datasets$name == which | datasets$slug == which, , drop = FALSE];"
    " if (nrow(row) == 0) stop(sprintf("
    "\"There is no dataset called '%s' in this project. Try one of: %s\","
    " which, paste(datasets$name, collapse = \", \")));"
    " utils::read.csv(file.path(.susodash_data, paste0(row$slug[1], \".csv\")),"
    " stringsAsFactors = FALSE, check.names = FALSE,"
    " na.strings = c(\"NA\", \"\")) }"
)

_WRITER = (
    "write_dataset <- function(frame, name) {"
    " if (!is.data.frame(frame)) stop(\"write_dataset() takes a data frame\");"
    " if (!is.character(name) || length(name) != 1 || !nzchar(name))"
    " stop(\"write_dataset() needs a name to save under\");"
    " safe <- gsub(\"^-+|-+$\", \"\", gsub(\"[^A-Za-z0-9]+\", \"-\", name));"
    " if (!nzchar(safe)) stop("
    "\"write_dataset() needs a name with some letters or digits in it\");"
    " utils::write.csv(frame, file.path(.susodash_out, paste0(safe, \".csv\")),"
    " row.names = FALSE, na = \"\");"
    " .susodash_written[[length(.susodash_written) + 1]] <<-"
    " sprintf('{\"name\":\"%s\",\"file\":\"%s.csv\"}',"
    " gsub('\"', \"'\", name), safe);"
    " invisible(frame) }"
)


def _execute(room: Path) -> str:
    """Run Rscript with the workspace as its home, and hand back what it printed."""
    settings = get_settings()
    executable = binary()
    assert executable  # unavailable_reason has already been checked

    env = _environment(room)
    # The one difference from a dataset run: the library path is the project's
    # own and it is kept, so install.packages() in a project is done once.
    env["R_LIBS_USER"] = str(room / LIB_DIR)
    try:
        finished = subprocess.run(  # noqa: S603 - the command is ours; see the docstring
            [executable, "--vanilla", SCRIPT],
            cwd=room,
            env=env,
            capture_output=True,
            text=True,
            timeout=max(5, settings.r_timeout_seconds),
            start_new_session=True,
            preexec_fn=_limits,  # noqa: PLW1509 - see _limits
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProjectRError(
            f"The script was still running after {settings.r_timeout_seconds} "
            "seconds and was stopped. Nothing was saved back."
        ) from exc

    printed = _trim(finished.stdout, finished.stderr)
    if finished.returncode != 0:
        raise ProjectRError(
            "R stopped with an error. Nothing was saved back.\n\n"
            + (printed or f"R exited with status {finished.returncode}.")
        )
    return printed


def _collect(
    db: Session, project: Project, room: Path, created_by: str | None
) -> list[dict[str, object]]:
    """Turn what write_dataset() left in `out` into datasets of this project.

    A name that is already a dataset here is replaced in place, so a script run
    twice does not leave two copies and every chart pointing at it goes on
    working. A name that is not becomes a new dataset in this project.
    """
    manifest = room / OUT_DIR / MANIFEST
    if not manifest.exists():
        return []
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []

    written: list[dict[str, object]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        source = room / OUT_DIR / str(entry.get("file") or "")
        if not name or not source.is_file():
            continue
        frame = pd.read_csv(source, low_memory=False)
        dataset = db.scalar(
            select(Dataset).where(
                Dataset.project_id == project.id, Dataset.name == name
            )
        )
        if dataset is None:
            dataset = create_dataset_record(
                db,
                name=name,
                description=f"Written by an R script in {project.name}",
                created_by=created_by,
                project_id=project.id,
            )
        else:
            # A rename is the author's to make; what changed here is the data.
            dataset.slug = dataset.slug or unique_slug(db, name, exclude_id=dataset.id)
        _apply_ingest(
            db,
            dataset,
            ingest_frame(frame, {}, {}, dataset_directory(dataset.id), []),
        )
        written.append(
            {"name": name, "id": dataset.id, "rows": int(len(frame))}
        )
    return written


def is_plumbing(relative: Path) -> bool:
    """Files the platform put there, which are not the user's to look at."""
    first = relative.parts[0] if relative.parts else ""
    # `data` is what the platform writes for scripts to read and `out` is where
    # it collects what they wrote; both are cleared and rebuilt, so listing
    # them among somebody's own files would be listing the plumbing.
    return first in (DATA_DIR, OUT_DIR, LIB_DIR) or relative.name in (SCRIPT, MANIFEST)
