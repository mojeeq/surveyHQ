"""Submitting a script to the sandboxed runner, and reading back what it made.

PROTOTYPE. Nothing in the API or the worker calls this yet. It exists so the
protocol can be read and argued with before anything depends on it, and so the
round trip that matters - a dataset out to R and back with its labels intact -
can be tested.

The channel is a directory, because the runner can reach nothing else. It holds
no secrets, joins a network with no route off the host, and sees one job at a
time; a queue would mean giving it Redis, and Redis is a thing it could then
read. A directory both sides can see is the narrowest channel that works.

The handshake is two marker files:

    <job>/script.R          what to run
    <job>/in/data.parquet   the dataset, as the platform already stores it
    <job>/in/labels.json    variable and value labels, which Parquet has no
                            standard place for
    <job>/READY             written last: the promise that the rest is complete
    ---
    <job>/out/data.parquet  what the script left in `data`
    <job>/out/labels.json   the labels read back off it
    <job>/result.json       ok, error, rows, columns, seconds
    <job>/log.txt           whatever the script printed
    <job>/DONE              written last, for the same reason

Each side writes its marker last and neither reads before seeing the other's,
so neither can act on a half-written job.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

# How long to wait for the runner before giving up on it. Longer than the
# runner's own limit, so a script that overruns is reported by the runner -
# which knows why - rather than by this, which would only know that nothing
# came back.
DEFAULT_WAIT_SECONDS = 360.0


class SandboxError(RuntimeError):
    """The job could not be run, or did not come back."""


@dataclass
class SandboxResult:
    ok: bool
    error: str = ""
    rows: int = 0
    columns: int = 0
    seconds: float = 0.0
    log: str = ""
    #: Where the script's output landed, when it produced any.
    data_path: Path | None = None
    variable_labels: dict[str, str] = field(default_factory=dict)
    value_labels: dict[str, dict[str, str]] = field(default_factory=dict)


def submit(
    work_root: Path,
    *,
    script: str,
    data_path: Path,
    variable_labels: dict[str, str] | None = None,
    value_labels: dict[str, dict[str, str]] | None = None,
) -> Path:
    """Write a job out and mark it ready. Returns the job directory."""
    job = Path(work_root) / uuid4().hex
    (job / "in").mkdir(parents=True)

    # Copied rather than linked: the runner must not be able to reach back
    # through the file to the dataset the platform is still serving.
    shutil.copyfile(data_path, job / "in" / "data.parquet")
    (job / "in" / "labels.json").write_text(
        json.dumps(
            {
                "variable_labels": variable_labels or {},
                "value_labels": value_labels or {},
            }
        )
    )
    (job / "script.R").write_text(script)

    # Last, and only now.
    (job / "READY").touch()
    return job


def collect(job: Path, *, wait: float = DEFAULT_WAIT_SECONDS, poll: float = 0.25) -> SandboxResult:
    """Wait for a job to finish and read what it left."""
    job = Path(job)
    deadline = time.monotonic() + wait
    while not (job / "DONE").exists():
        if time.monotonic() > deadline:
            raise SandboxError(
                "The script runner did not answer. Check that it is running: "
                "docker compose --profile sandbox ps runner-r"
            )
        time.sleep(poll)

    log = ""
    log_file = job / "log.txt"
    if log_file.exists():
        log = log_file.read_text(errors="replace")

    try:
        reported = json.loads((job / "result.json").read_text())
    except (OSError, ValueError) as exc:
        raise SandboxError(f"The runner left no readable result: {exc}") from exc

    # The runner writes its JSON through jsonlite, which wraps scalars in
    # one-element arrays unless told not to. It is told not to, but a value
    # that arrives wrapped anyway should not crash the read.
    def one(value: object, fallback: object) -> object:
        if isinstance(value, list):
            return value[0] if value else fallback
        return fallback if value is None else value

    ok = bool(one(reported.get("ok"), False))
    result = SandboxResult(
        ok=ok,
        error=str(one(reported.get("error"), "") or ""),
        rows=int(one(reported.get("rows"), 0) or 0),
        columns=int(one(reported.get("columns"), 0) or 0),
        seconds=float(one(reported.get("seconds"), 0.0) or 0.0),
        log=log,
    )
    if not ok:
        return result

    produced = job / "out" / "data.parquet"
    if not produced.exists():
        result.ok = False
        result.error = "The script finished but wrote no data."
        return result
    result.data_path = produced

    labels_file = job / "out" / "labels.json"
    if labels_file.exists():
        try:
            labels = json.loads(labels_file.read_text())
        except ValueError:
            labels = {}
        result.variable_labels = {
            str(k): str(one(v, "")) for k, v in (labels.get("variable_labels") or {}).items()
        }
        result.value_labels = {
            str(k): {str(code): str(one(text, "")) for code, text in (pairs or {}).items()}
            for k, pairs in (labels.get("value_labels") or {}).items()
        }
    return result


def discard(job: Path) -> None:
    """Remove a finished job. Its input is a copy of confidential microdata."""
    shutil.rmtree(job, ignore_errors=True)
