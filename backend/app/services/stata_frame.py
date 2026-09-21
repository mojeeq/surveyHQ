"""The data a project's script has in memory while it runs.

The command engine used to work on a dataset directly: every `generate` read
the dataset's Parquet, built the new shape and wrote it straight back. That is
fine for one file and wrong for a project, where the whole point is to read
several, put them together and write out something new. It also gave `use`
nothing to mean, and `collapse` nowhere to go: reducing a person-level file to
one row per province, in place, would destroy the file.

So a script works the way a do-file does. `use` loads a copy of a dataset into
memory; the commands change the copy; and nothing on disk moves until a `save`
says so. A script that loads, collapses and saves under a new name leaves what
it read exactly as it found it.

"In memory" is a Parquet file in a scratch directory rather than a frame held
in the process. That is deliberate: every command in the engine is built as
SQL over `read_parquet(...)`, and giving them a path instead of a dataset let
all of them carry over unchanged. It also means a script over a file too large
to hold in memory still runs, since DuckDB reads what it needs.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from app.models import Dataset
from app.services.ingest import ingest_frame
from app.services.query_engine import DatasetContext, VariableInfo


class FrameError(ValueError):
    """Something was asked of the data in memory that cannot be done to it."""


@dataclass
class Frame:
    """One dataset's worth of data, loaded and being worked on.

    `origin` is the dataset it was loaded from, which is what a bare `save`
    writes back over. It is cleared by anything that makes the data no longer
    that dataset - a collapse, an append, a merge - because saving a
    one-row-per-province table over the person-level file it came from is
    never what somebody meant, and a script that means it can say so with
    `save as`.
    """

    name: str
    path: Path
    variables: dict[str, VariableInfo]
    labels: dict[str, str] = field(default_factory=dict)
    value_labels: dict[str, dict[str, str]] = field(default_factory=dict)
    # Label sets `label define` has built, by name. They belong to the run
    # rather than to any dataset: a set is defined so that `label values` can
    # apply it, and what is saved is the applied labels, not the set.
    label_books: dict[str, dict[str, str]] = field(default_factory=dict)
    origin: str | None = None
    rows: int = 0

    @property
    def context(self) -> DatasetContext:
        """What the expression translator needs, pointed at the working copy."""
        return DatasetContext(
            dataset_id=self.origin or "",
            parquet_path=str(self.path),
            variables=self.variables,
        )

    def has(self, name: str) -> bool:
        return name in self.variables

    def info(self, name: str) -> VariableInfo:
        found = self.variables.get(name.strip())
        if found is None:
            raise FrameError(f"'{name}' is not a variable in the data in memory")
        return found

    def label_of(self, name: str) -> str:
        return self.labels.get(name, "")


class Workspace:
    """The scratch directory one script run works in.

    A run gets its own, and it goes when the run ends, whether the script
    finished or stopped on an error. Nothing a failed script wrote is left
    behind to be mistaken for data later.
    """

    def __init__(self) -> None:
        self._dir: Path | None = None
        self._next = 0

    def __enter__(self) -> Workspace:
        self._dir = Path(tempfile.mkdtemp(prefix="surveyhq-script-"))
        return self

    def __exit__(self, *_: Any) -> None:
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None

    @property
    def directory(self) -> Path:
        if self._dir is None:
            raise FrameError("the script workspace is not open")
        return self._dir

    def step(self) -> Path:
        """A fresh directory for the next state of the data.

        Each write goes to a new one rather than over the last. DuckDB reads
        lazily, so a command that builds its new shape from the file it is
        about to replace would be reading a file being written underneath it.
        """
        self._next += 1
        made = self.directory / f"step-{self._next:04d}"
        made.mkdir(parents=True, exist_ok=True)
        return made


def load(workspace: Workspace, dataset: Dataset) -> Frame:
    """Copy a dataset into the workspace, ready to be worked on."""
    if not dataset.storage_path:
        raise FrameError(f"'{dataset.name}' has no data to work on yet")
    source = Path(dataset.storage_path)
    if not source.exists():
        raise FrameError(f"'{dataset.name}' has no data to work on yet")

    into = workspace.step() / "data.parquet"
    shutil.copyfile(source, into)

    labels: dict[str, str] = {}
    value_labels: dict[str, dict[str, str]] = {}
    for variable in dataset.variables:
        if variable.label:
            labels[variable.name] = variable.label
        if variable.value_labels:
            value_labels[variable.name] = variable.value_labels

    return Frame(
        name=dataset.name,
        path=into,
        variables=DatasetContext.from_model(dataset).variables,
        labels=labels,
        value_labels=value_labels,
        origin=dataset.id,
        rows=dataset.row_count or 0,
    )


def write(
    workspace: Workspace,
    frame: Frame,
    data: pd.DataFrame,
    renamed: dict[str, str] | None = None,
) -> None:
    """Put the new shape of the data back into the workspace.

    The variable metadata is rebuilt from what was actually written rather than
    edited alongside it, so a command that drops a column cannot leave its
    label behind to reappear on a later `save`.
    """
    renamed = renamed or {}
    labels = {renamed.get(name, name): text for name, text in frame.labels.items()}
    values = {renamed.get(name, name): pairs for name, pairs in frame.value_labels.items()}

    result = ingest_frame(data, labels, values, workspace.step(), [])

    frame.path = Path(result.parquet_path)
    frame.rows = result.row_count
    frame.variables = {
        meta.name: VariableInfo(
            name=meta.name,
            label=meta.label or "",
            var_type=getattr(meta.var_type, "value", str(meta.var_type)),
            value_labels=meta.value_labels or {},
            missing_tags=list(meta.missing_tags or []),
            storage_type=str(getattr(meta, "storage_type", "") or ""),
        )
        for meta in result.variables
    }
    kept = set(frame.variables)
    frame.labels = {name: text for name, text in labels.items() if name in kept}
    frame.value_labels = {name: pairs for name, pairs in values.items() if name in kept}
