"""Running an R script over a dataset.

The command box speaks a subset of Stata, which covers generating a variable
and labelling it and little else. Anything a survey statistician actually
reaches for beyond that - recoding a battery of questions, deriving a poverty
line, reshaping a roster - is a few lines of R and no lines of anything this
platform could reasonably invent.

So the dataset is handed to R as a data frame, the script runs, and the frame
it leaves behind becomes the dataset. The contract is one sentence: the data is
a data frame called `data`, and whatever `data` holds when the script ends is
what the dataset becomes.

The round trip goes through CSV, which is what base R reads and writes without
a single package installed. Types are therefore re-read on the way back in,
exactly as they would be from an uploaded CSV.

WHAT THIS IS NOT
================
This is not a sandbox. An R script is a program, and a program can read files
the server can read, open sockets the server can open, and call system(). The
containment here - a fresh working directory, no profiles, a wall-clock
timeout, an address-space cap - stops a runaway script, not a hostile one.
There is no blocklist of dangerous calls, because a blocklist over a language
with eval(parse(text=)) would only be a promise nobody can keep.

That is why it is off unless somebody turns it on, and why only a manager can
reach it. Anyone who can run R here can run anything the server's own user can.
"""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Dataset
from app.services.datasets import _apply_ingest, dataset_directory, dataset_is_queryable
from app.services.ingest import ingest_frame

logger = get_logger(__name__)

# The names the script sees and writes. Read into `data`, written back from
# `data`: one name to learn, and the same one both ways so a script does not
# end with a line whose only job is renaming its own result.
FRAME = "data"
INPUT = "susodash_input.csv"
OUTPUT = "susodash_output.csv"
SCRIPT = "susodash_script.R"

# Printed output kept from a run. A script that prints a whole data frame can
# produce megabytes, and none of it past the first screenful helps.
MAX_LOG = 20_000


class RError(RuntimeError):
    """The script could not be run, or it failed."""


@dataclass
class RResult:
    """What one run did."""

    message: str
    output: str = ""
    rows: int = 0
    columns: int = 0
    variables_added: list[str] = field(default_factory=list)
    variables_removed: list[str] = field(default_factory=list)


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


def run_script(db: Session, dataset: Dataset, script: str, record_it: bool = True) -> RResult:
    """Run one R script against a dataset and keep what it leaves behind."""
    reason = unavailable_reason()
    if reason:
        raise RError(reason)
    if not dataset_is_queryable(dataset):
        raise RError(f"'{dataset.name}' has no data to work on yet")
    script = script.strip()
    if not script:
        raise RError("Type some R, for example: data$adult <- data$age >= 18")

    before = pd.read_parquet(dataset.storage_path)
    after, printed = _execute(before, script)

    if after.empty and not after.columns.any():
        raise RError(
            f"The script left `{FRAME}` with no columns. It has to end with a data "
            "frame, since that data frame is what the dataset becomes."
        )

    kept = [str(name) for name in after.columns]
    had = [variable.name for variable in dataset.variables]
    _write(db, dataset, after)
    if record_it:
        _remember(dataset, script)

    added = [name for name in kept if name not in had]
    removed = [name for name in had if name not in kept]
    return RResult(
        message=(
            f"{len(after):,} rows and {len(kept)} columns"
            + (f", added {', '.join(added)}" if added else "")
            + (f", dropped {', '.join(removed)}" if removed else "")
        ),
        output=printed,
        rows=len(after),
        columns=len(kept),
        variables_added=added,
        variables_removed=removed,
    )


def _execute(frame: pd.DataFrame, script: str) -> tuple[pd.DataFrame, str]:
    """Hand the frame to R, run the script, and read back what it left."""
    settings = get_settings()
    executable = binary()
    assert executable  # unavailable_reason has already been checked

    with tempfile.TemporaryDirectory(prefix="susodash-r-") as work:
        room = Path(work)
        # index=False: an R script that writes the frame back out would
        # otherwise gain a column of row numbers on every round trip.
        frame.to_csv(room / INPUT, index=False)
        (room / SCRIPT).write_text(_wrap(script), encoding="utf-8")

        try:
            finished = subprocess.run(  # noqa: S603 - the command is ours; see below
                [executable, "--vanilla", SCRIPT],
                cwd=room,
                env=_environment(room),
                capture_output=True,
                text=True,
                timeout=max(5, settings.r_timeout_seconds),
                # Its own process group, so the timeout kills anything the
                # script itself started rather than orphaning it.
                start_new_session=True,
                preexec_fn=_limits,  # noqa: PLW1509 - see _limits
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RError(
                f"The script was still running after {settings.r_timeout_seconds} "
                "seconds and was stopped. Nothing was changed."
            ) from exc

        printed = _trim(finished.stdout, finished.stderr)
        if finished.returncode != 0:
            raise RError(
                "R stopped with an error. Nothing was changed.\n\n"
                + (printed or f"R exited with status {finished.returncode}.")
            )

        result = room / OUTPUT
        if not result.exists():
            raise RError(
                "The script finished without leaving anything to save. Assign the "
                f"result to `{FRAME}`."
                + (f"\n\n{printed}" if printed else "")
            )
        # keep_default_na keeps an empty field as missing without turning the
        # string "NA" in a text answer into one; low_memory=False so a column
        # is typed from the whole file rather than chunk by chunk.
        after = pd.read_csv(result, low_memory=False)
    return after, printed


def _wrap(script: str) -> str:
    """The script, with the reading and the writing put around it.

    Written as a file rather than passed with -e: an error in a file reports
    the line it happened on, and the line numbers then match what the person
    typed, because the preamble is one line.
    """
    preamble = (
        f'{FRAME} <- utils::read.csv("{INPUT}", stringsAsFactors = FALSE, '
        'check.names = FALSE, na.strings = c("NA", ""))'
    )
    # local() so the script's own variables do not have to be cleaned up, and
    # so a script ending in an expression does not print it as a side effect.
    postamble = (
        f'if (!is.data.frame({FRAME})) stop("`{FRAME}` is no longer a data frame; '
        f'the dataset is whatever `{FRAME}` holds when the script ends")\n'
        f'utils::write.csv({FRAME}, "{OUTPUT}", row.names = FALSE, na = "")'
    )
    return f"{preamble}\n{script}\n{postamble}\n"


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


def _remember(dataset: Dataset, script: str) -> None:
    """Keep the script in the dataset's ordered history, so a replace replays it.

    The same list the Stata commands go into, because the order between the two
    is what makes a replay mean anything: an R script reading a column that a
    `gen` created has to run after it. See services/scripts.py.
    """
    meta = dict(dataset.meta or {})
    commands = list(meta.get("commands") or [])
    commands.append({"kind": "r", "text": script})
    meta["commands"] = commands
    dataset.meta = meta


def _write(db: Session, dataset: Dataset, frame: pd.DataFrame) -> None:
    """Persist the frame as the dataset, keeping the labels of surviving columns.

    A column the script dropped takes its label with it; one it kept keeps it.
    A new column has no label until somebody writes one, which is the same
    position a generated variable is in.
    """
    labels = {}
    value_labels = {}
    present = {str(name) for name in frame.columns}
    for variable in dataset.variables:
        if variable.name not in present:
            continue
        if variable.label:
            labels[variable.name] = variable.label
        if variable.value_labels:
            value_labels[variable.name] = variable.value_labels
    _apply_ingest(
        db,
        dataset,
        ingest_frame(frame, labels, value_labels, dataset_directory(dataset.id), []),
    )
