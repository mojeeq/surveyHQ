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

Saving a data file does the same thing as write_dataset(), because that is what
somebody coming from RStudio writes without thinking about it:

    write.csv(adults, "adults.csv")      a dataset here called adults
    haven::write_dta(adults, "adults.dta")

Any .csv, .dta, .sav, .tsv, .xls or .xlsx the run leaves in the working
directory becomes a dataset named after the file. Only files that run wrote:
the directory survives, so a file from three runs ago became a dataset three
runs ago. Anything that does not read as a table stays an ordinary file, so a
log written to .csv is a log.

What the script leaves in R's global environment is listed too, which is what
the Environment pane is drawn from. Every run is a new R session, so that is a
record of what the last run made rather than something the next run can reach.

EXECUTION AND CONFINEMENT
=========================
The default launcher confines R with Landlock and seccomp, plus a timeout and
memory limit. Enabling unconfined execution is an explicit deployment override.
A project lock serialises runs until their database transaction ends, preserving
the persistent workspace. Each run retains its code, inputs and result separately.

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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

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
from app.services.ingest import ingest_frame, read_source
from app.services.sharing import as_utc

logger = get_logger(__name__)

# Where things sit inside a workspace. `data` is written by the platform and
# read by scripts; `out` is the other way round. Everything else in the
# workspace belongs to whoever put it there.
DATA_DIR = "data"
OUT_DIR = "out"
MANIFEST = "susodash_written.json"
ENVIRONMENT = "susodash_environment.csv"
SCRIPT = "susodash_project.R"
# What the launcher answers to --surveyhq-sandbox-probe, and the name the
# image installs it under. Both are matched exactly: a sandbox that cannot
# be identified is not a sandbox.
SANDBOX_PROBE = "surveyhq-r-sandbox-v1"
SANDBOX_BINARY = "surveyhq-r-sandbox"
LIB_DIR = "rlibs"


# Printed output kept from a run. A script that prints a whole data frame can
# produce megabytes, and none of it past the first screenful helps.
MAX_LOG = 20_000

# Data files a script leaves behind are adopted as datasets of the project.
# A narrower list than import accepts: .tab and .txt are how a Survey
# Solutions export arrives, and a script writing one of those is far more
# often writing a log than a dataset.
ADOPTED_EXTENSIONS = (".csv", ".dta", ".sav", ".tsv", ".xlsx", ".xls")

# Ceilings on what one run can produce, so a loop with a bug makes a mess in
# the workspace rather than several thousand rows in the datasets table.
MAX_ADOPTED = 50
MAX_OBJECTS = 200


class RError(RuntimeError):
    """R could not be run, or the script failed."""


class ProjectRError(RError):
    """The workspace could not be prepared, or the script failed."""


# -- where R is, and whether it may be used ---------------------------------


def binary() -> str | None:
    """What R is actually started through, if it is anywhere.

    Normally the sandbox launcher. With the sandbox given up deliberately it
    has to be something else: the launcher installs Landlock or exits, so a
    host that turned R_SANDBOX_REQUIRED off because its kernel cannot enforce
    Landlock would otherwise be handed the one program guaranteed to fail
    there - an opt-out that opts out of running R at all. Only the default is
    swapped, so R_BINARY still names whatever it names.
    """
    settings = get_settings()
    named = (settings.r_binary or "Rscript").strip()
    if not settings.r_sandbox_required and named == SANDBOX_BINARY:
        named = "Rscript"
    return shutil.which(named)


# The self-test runs a subprocess, and the answer cannot change while the
# process lives: the launcher is baked into the image and the kernel is the
# kernel. So it is asked once. None means "not asked yet".
_sandbox_check: tuple[bool, str] | None = None


def sandbox_check(executable: str) -> tuple[bool, str]:
    """Whether this executable is the sandbox and can enforce itself here.

    Two questions, because they fail differently. `--surveyhq-sandbox-probe`
    says the configured program is our launcher rather than a bare Rscript
    somebody pointed R_BINARY at. `--surveyhq-sandbox-selftest` says the
    kernel will actually let it confine anything, which a container on an old
    kernel or a restrictive runtime will not.

    Asked here rather than at the first script so the answer reaches the
    interface as a sentence, not a stack trace an hour into somebody's work.
    """
    global _sandbox_check
    if _sandbox_check is not None:
        return _sandbox_check

    def ask(flag: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [executable, flag],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    try:
        probe = ask("--surveyhq-sandbox-probe")
        if probe.returncode != 0 or probe.stdout.strip() != SANDBOX_PROBE:
            _sandbox_check = (
                False,
                "R_BINARY does not name the SurveyHQ sandbox launcher, so scripts "
                "would run unconfined. Leave R_BINARY unset to use the sandbox "
                "this image builds, or set R_SANDBOX_REQUIRED=false to accept "
                "unconfined R deliberately.",
            )
            return _sandbox_check

        test = ask("--surveyhq-sandbox-selftest")
        if test.returncode != 0:
            detail = (test.stderr or test.stdout).strip().splitlines()
            _sandbox_check = (
                False,
                "The R sandbox cannot be enforced on this host: "
                + (detail[0] if detail else "the self-test failed")
                + " Run surveyhq-check-r-sandbox on the server to see the same "
                "check outside the platform. Set R_SANDBOX_REQUIRED=false to run "
                "R unconfined instead, having read what that allows.",
            )
            return _sandbox_check
    except (OSError, subprocess.SubprocessError) as exc:
        _sandbox_check = (False, f"The R sandbox launcher could not be run: {exc}")
        return _sandbox_check

    _sandbox_check = (True, "")
    return _sandbox_check


def unavailable_reason() -> str:
    """Why R cannot be run here, or an empty string when it can.

    Several different answers, because they need several different actions:
    turn the setting on, rebuild the image, fix the host, or knowingly accept
    unconfined R. One message saying "unavailable" would send most of the
    people who hit it to the wrong place.
    """
    settings = get_settings()
    if not settings.r_scripts_enabled:
        return (
            "Running R is switched off on this server. An administrator turns it "
            "on with R_SCRIPTS_ENABLED=true, having read what it allows."
        )
    executable = binary()
    if not executable:
        named = (settings.r_binary or "Rscript").strip()
        if named == SANDBOX_BINARY:
            return (
                "The R sandbox launcher is not in this image. It is built from "
                "backend/sandbox/r-sandbox.c during the Docker build, so an image "
                "from before the sandbox existed needs rebuilding: "
                "docker compose build api worker && docker compose up -d."
            )
        return (
            f"'{named}' is not on this server's PATH. Install R (apt-get install "
            "r-base-core, or the r-base package for your system) and restart."
        )
    if not settings.r_sandbox_required:
        # Deliberately unconfined, and running through plain Rscript by now -
        # see binary(). Said plainly rather than left to be discovered: this is
        # the arrangement where a project's script can read every other
        # project's files.
        return ""
    ok, why = sandbox_check(executable)
    return "" if ok else why


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
    # What the script left in R's global environment, as
    # {"name", "kind", "type", "shape", "preview", "bytes"}.
    environment: list[dict[str, object]] = field(default_factory=list)


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


def _run(
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
    # Taken before the run so that "the script saved this" can be told from
    # "this was already lying here": the workspace survives between runs, and a
    # file written three runs ago became a dataset three runs ago.
    before = _census(room)
    printed = _execute(room)
    written = _collect(db, project, room, created_by, before)

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
        environment=snapshot(room),
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
            f".susodash_environment_file <- {_r_string(ENVIRONMENT)}",
            ".susodash_written <- character(0)",
            f"datasets <- utils::read.csv(text = {_r_string(_catalogue(ready))}, "
            "stringsAsFactors = FALSE)",
            _READER,
            _WRITER,
            _DESCRIBER,
        ]
    )
    # Written even when the script wrote nothing, so an empty manifest and a
    # crashed run are told apart by the collector rather than guessed at.
    #
    # The environment listing is the same idea for objects rather than
    # datasets, and its failure is swallowed: describing what a script made
    # is a courtesy, and a courtesy must not turn a run that worked into a
    # run that reports an error.
    postamble = "; ".join(
        [
            'writeLines(paste0("[", paste(.susodash_written, collapse = ","), "]"), '
            "file.path(.susodash_out, .susodash_manifest))",
            "tryCatch(utils::write.csv(.susodash_describe(),"
            " file.path(.susodash_out, .susodash_environment_file),"
            " row.names = FALSE), error = function(e) invisible(NULL))",
        ]
    )
    return f"{preamble}\n{code}\n{postamble}\n"


def _catalogue(ready: list[Dataset]) -> str:
    """The available datasets as CSV text.

    CSV rather than JSON because base R reads it with no package installed, and
    "base R is the floor" is the promise the whole feature is built on.
    """
    rows = pd.DataFrame(
        [{"name": d.name, "slug": d.slug, "rows": int(d.row_count or 0)} for d in ready],
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
    ' which, paste(datasets$name, collapse = ", ")));'
    ' utils::read.csv(file.path(.susodash_data, paste0(row$slug[1], ".csv")),'
    " stringsAsFactors = FALSE, check.names = FALSE,"
    ' na.strings = c("NA", "")) }'
)

_WRITER = (
    "write_dataset <- function(frame, name) {"
    ' if (!is.data.frame(frame)) stop("write_dataset() takes a data frame");'
    " if (!is.character(name) || length(name) != 1 || !nzchar(name))"
    ' stop("write_dataset() needs a name to save under");'
    ' safe <- gsub("^-+|-+$", "", gsub("[^A-Za-z0-9]+", "-", name));'
    " if (!nzchar(safe)) stop("
    '"write_dataset() needs a name with some letters or digits in it");'
    ' utils::write.csv(frame, file.path(.susodash_out, paste0(safe, ".csv")),'
    ' row.names = FALSE, na = "");'
    " .susodash_written[[length(.susodash_written) + 1]] <<-"
    ' sprintf(\'{"name":"%s","file":"%s.csv"}\','
    " gsub('\"', \"'\", name), safe);"
    " invisible(frame) }"
)


def _one_line(source: str) -> str:
    """R source written readably, handed to R as a single line.

    The preamble is one line so that an error R reports is at the line the
    person typed, plus one - see _wrap. Keeping that promise by hand means
    writing R as a wall of escaped fragments, which is how the two functions
    above are written and is why they are as short as they are. This collapses
    the line breaks instead, so the describer below can be read as R.

    Only whitespace around a newline is touched, and no string literal in the
    source spans one, so nothing inside quotes moves.
    """
    return re.sub(r"\s*\n\s*", " ", source).strip()


# What the Environment pane is drawn from: one row per object the script left
# in the global environment. Written as a CSV rather than as JSON for the same
# reason the catalogue is - base R writes it with no package installed, and
# write.csv quotes a preview containing a comma or a quote correctly, which
# hand-rolled JSON in R would not.
#
# `ls()` skips dotted names, so the workspace's own values are already out; the
# three public ones are named because they are the platform's, not the script's.
_DESCRIBER = _one_line(
    f"""
    .susodash_describe <- function() {{
      empty <- data.frame(name = character(0), kind = character(0),
                          type = character(0), shape = character(0),
                          preview = character(0), bytes = numeric(0),
                          stringsAsFactors = FALSE);
      found <- setdiff(ls(envir = globalenv()),
                       c("datasets", "read_dataset", "write_dataset"));
      if (length(found) == 0) return(empty);
      if (length(found) > {MAX_OBJECTS}) found <- found[seq_len({MAX_OBJECTS})];
      rows <- lapply(found, function(nm) tryCatch({{
        value <- get(nm, envir = globalenv());
        if (is.function(value)) {{
          kind <- "function";
          shape <- "";
          text <- sub("[[:space:]]*NULL[[:space:]]*$", "",
                      paste(deparse(args(value)), collapse = " "));
        }} else if (is.data.frame(value)) {{
          kind <- "data";
          shape <- paste(format(nrow(value), big.mark = ","), "obs. of", ncol(value),
                         if (ncol(value) == 1) "variable" else "variables");
          text <- paste(names(value), collapse = ", ");
        }} else {{
          kind <- "value";
          shape <- if (!is.null(dim(value))) paste(dim(value), collapse = " x ")
                   else paste("length", length(value));
          text <- tryCatch(if (is.list(value)) paste(names(value), collapse = ", ")
                           else paste(as.character(utils::head(value, 10)), collapse = " "),
                           error = function(e) "");
        }};
        data.frame(name = nm, kind = kind, type = paste(class(value), collapse = "/"),
                   shape = shape,
                   preview = substr(gsub("[[:space:]]+", " ", text), 1, 200),
                   bytes = as.numeric(utils::object.size(value)),
                   stringsAsFactors = FALSE)
      }}, error = function(e) NULL));
      rows <- rows[!vapply(rows, is.null, logical(1))];
      if (length(rows) == 0) return(empty);
      do.call(rbind, rows)
    }}
    """
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
    db: Session,
    project: Project,
    room: Path,
    created_by: str | None,
    before: dict[Path, tuple[int, int]],
) -> list[dict[str, object]]:
    """Turn what the script saved into datasets of this project.

    Two ways in, because people write R two ways. write_dataset() is the
    explicit one and names the dataset itself. The other is the one somebody
    coming from RStudio writes without thinking - write.csv(h, "adults.csv"),
    haven::write_dta(h, "adults.dta") - and that used to leave a file in the
    working directory and nothing else. A data file the run produced is now a
    dataset too, named after itself.

    Only files this run touched: the workspace survives between runs, so a file
    written three runs ago became a dataset three runs ago and re-adopting it
    every time would restamp datasets nobody changed.
    """
    written: list[dict[str, object]] = []
    claimed: set[str] = set()

    for name, source in _manifest_entries(room):
        if name in claimed:
            continue
        try:
            frame = pd.read_csv(source, low_memory=False)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            logger.warning("R script wrote %s but it could not be read: %s", source.name, exc)
            continue
        claimed.add(name)
        written.append(_save(db, project, name, frame, {}, {}, created_by))

    for source in _produced_files(room, before):
        name = source.stem.strip()
        if not name or name in claimed:
            continue
        try:
            frame, variable_labels, value_labels = read_source(source)
        except Exception as exc:  # noqa: BLE001 - see below
            # Deliberately everything. A .csv that is not a table, a half-written
            # .dta, a reader library raising something of its own: the script
            # meant to write the file and it worked, so the file stays in the
            # working directory and the run is still a run that succeeded.
            # Narrowing this would turn somebody's log file into a failed script.
            logger.info("Left %s in the workspace, unreadable as data: %s", source.name, exc)
            continue
        if not len(frame.columns):
            continue
        claimed.add(name)
        written.append(_save(db, project, name, frame, variable_labels, value_labels, created_by))

    return written


def _manifest_entries(room: Path) -> list[tuple[str, Path]]:
    """The (name, file) pairs write_dataset() recorded, if the run got that far."""
    manifest = room / OUT_DIR / MANIFEST
    if not manifest.exists():
        return []
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []

    pairs: list[tuple[str, Path]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        source = room / OUT_DIR / str(entry.get("file") or "")
        if name and source.is_file():
            pairs.append((name, source))
    return pairs


def _census(room: Path) -> dict[Path, tuple[int, int]]:
    """Every adoptable file in the workspace, as it stands, by size and mtime.

    Compared against rather than a clock. Two runs in the same second are
    ordinary here - a saved script that runs after an import takes milliseconds
    - and a timestamp cutoff would re-adopt the previous run's output every
    time, restamping datasets nobody had changed.
    """
    census: dict[Path, tuple[int, int]] = {}
    for path in room.rglob("*"):
        relative = path.relative_to(room)
        if not path.is_file() or is_plumbing(relative):
            continue
        if path.suffix.lower() not in ADOPTED_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        census[relative] = (stat.st_mtime_ns, stat.st_size)
    return census


def _produced_files(room: Path, before: dict[Path, tuple[int, int]]) -> list[Path]:
    """Data files this run wrote: the ones that are new, or are not as they were."""
    found: list[Path] = []
    for relative, state in sorted(_census(room).items()):
        if before.get(relative) == state:
            continue
        found.append(room / relative)
        if len(found) >= MAX_ADOPTED:
            break
    return found


def _save(
    db: Session,
    project: Project,
    name: str,
    frame: pd.DataFrame,
    variable_labels: dict[str, str],
    value_labels: dict[str, dict[str, str]],
    created_by: str | None,
) -> dict[str, object]:
    """Create or replace the project's dataset of this name.

    Replaced in place rather than added beside, so a script run twice does not
    leave two copies and every chart pointing at it goes on working.
    """
    dataset = db.scalar(
        select(Dataset).where(Dataset.project_id == project.id, Dataset.name == name)
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
        ingest_frame(frame, variable_labels, value_labels, dataset_directory(dataset.id), []),
    )
    return {"name": name, "id": dataset.id, "rows": int(len(frame))}


def snapshot(room: Path) -> list[dict[str, object]]:
    """What the last run left in R's global environment.

    Read from the workspace rather than carried in memory, so the pane still
    has something to draw after a reload. It lives in `out`, which is emptied
    at the start of every run: a run that failed leaves no environment, which
    is the truth - nothing it made survived.
    """
    source = room / OUT_DIR / ENVIRONMENT
    if not source.is_file():
        return []
    try:
        # Every column read as text: a preview of "1 2 3" is not a number, and
        # letting pandas decide would turn some previews into NaN.
        frame = pd.read_csv(source, dtype=str, keep_default_na=False)
    except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError):
        return []

    objects: list[dict[str, object]] = []
    for row in frame.to_dict("records"):
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            size = int(float(row.get("bytes") or 0))
        except (TypeError, ValueError):
            size = 0
        objects.append(
            {
                "name": name,
                "kind": str(row.get("kind") or "value"),
                "type": str(row.get("type") or ""),
                "shape": str(row.get("shape") or ""),
                "preview": str(row.get("preview") or ""),
                "bytes": size,
            }
        )
    return objects[:MAX_OBJECTS]


def is_plumbing(relative: Path) -> bool:
    """Files the platform put there, which are not the user's to look at."""
    first = relative.parts[0] if relative.parts else ""
    # `data` is what the platform writes for scripts to read and `out` is where
    # it collects what they wrote; both are cleared and rebuilt, so listing
    # them among somebody's own files would be listing the plumbing.
    return first in (DATA_DIR, OUT_DIR, LIB_DIR) or relative.name in (
        SCRIPT,
        MANIFEST,
        ENVIRONMENT,
    )


def run(
    db: Session, project: Project, code: str, *, created_by: str | None = None
) -> ProjectRResult:
    """Serialise the persistent workspace and retain a separate record of each run."""
    from app.services.operation_lock import acquire

    acquire(db, f"project-r:{project.id}")
    run_id = uuid4().hex
    directory = get_settings().storage_path / "r-runs" / project.id / run_id
    directory.mkdir(parents=True)
    (directory / "script.R").write_text(code, encoding="utf-8")
    state = {
        "id": run_id,
        "status": "running",
        "started_at": utcnow().isoformat(),
        "created_by": created_by,
        "inputs": {d.id: d.version for d in project_datasets(db, project.id)},
    }
    (directory / "run.json").write_text(json.dumps(state), encoding="utf-8")
    try:
        result = _run(db, project, code, created_by=created_by)
        state.update(status="success", result=asdict(result))
        return result
    except Exception as exc:
        state.update(status="failed", error=str(exc))
        raise
    finally:
        state["finished_at"] = utcnow().isoformat()
        (directory / "run.json").write_text(json.dumps(state), encoding="utf-8")
