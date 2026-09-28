"""What a command's write has to leave behind.

The commands no longer hand a frame to be written; they hand the query that
describes their result and DuckDB writes it. That is worth a great deal - a
command over a census file went from 14 seconds and 400 MB of heap to a quarter
of a second and none - and it moves three things that were previously somebody
else's job:

  the row order, which used to survive because pandas kept it;
  the variable list, which used to come from profiling a frame;
  and the tagged-missing companion columns, which the profiler that reads a
  Parquet file leaves out because a variable picker should not show them.

Each of those is pinned here, because each of them is silent when it breaks: a
reordered file, a lost companion or a stale label all read as data.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.services import ingest
from app.services.query_engine import VariableInfo
from app.services.stata_frame import Frame, Workspace, row_count, variables_of, write

PEOPLE = pd.DataFrame(
    {
        "hhid": [3.0, 1.0, 2.0, 1.0],
        "province": ["Tafea", "Shefa", "Sanma", "Shefa"],
        "wage": [30.0, 10.0, 20.0, None],
        # What ingest writes beside a variable that had Stata's .a and .b: which
        # kind of missing each blank was.
        "wage__mv": [None, None, None, ".a"],
    }
)


@pytest.fixture
def stored(tmp_path) -> Path:
    path = tmp_path / "data.parquet"
    PEOPLE.to_parquet(path, index=False)
    return path


@pytest.fixture
def frame(stored) -> Frame:
    return Frame(
        name="people",
        path=stored,
        variables={
            name: VariableInfo(name=name) for name in PEOPLE.columns
        },
        labels={"wage": "Weekly wage", "province": "Province"},
        rows=len(PEOPLE),
    )


# Both profilers, because they do not agree by themselves: the batched one keeps
# the companion columns and the per-column one drops them, and in an installation
# with the performance runtime off it is the second that runs. A test against
# whichever happens to be installed would pass while the other quietly lost data.
PROFILERS = ("build_metadata_from_parquet", "build_metadata_per_column")


@pytest.fixture(params=PROFILERS)
def profiler(request, monkeypatch):
    """Run the test body once per way of describing a Parquet file."""
    chosen = getattr(ingest, request.param, None)
    if chosen is None:
        pytest.skip(f"{request.param} is not installed in this process")
    monkeypatch.setattr(ingest, "build_metadata_from_parquet", chosen)
    return request.param


def test_the_companion_column_is_described_along_with_the_variable(stored, profiler):
    """The per-column profiler leaves the companions out.

    Right for a variable picker, and wrong here: a command lists the variables
    it is keeping, so a companion missing from that list is a companion dropped
    from the data - and the variable it belongs to no longer knows which of its
    blanks were .a and which were plain.
    """
    described = {meta.name for meta in variables_of(stored, {}, {})}
    assert "wage__mv" in described
    assert described == set(PEOPLE.columns)


def test_the_companion_is_marked_hidden_rather_than_offered(stored, profiler):
    hidden = {meta.name: meta.is_hidden for meta in variables_of(stored, {}, {})}
    assert hidden["wage__mv"] is True
    assert hidden["wage"] is False


def test_a_write_keeps_the_rows_in_the_order_the_query_gave_them(frame):
    """A window function is free to return rows grouped.

    Which silently reorders the data under everything that reads it by
    position, so the query says what the order is and the write has to keep it.
    Worth pinning at this level because the write is a COPY now, and DuckDB is
    configured to reorder freely where nothing has asked for an order.
    """
    source = frame.path
    with Workspace() as work:
        write(work, frame, f'SELECT * FROM read_parquet(\'{source}\') ORDER BY "hhid"')
        after = pd.read_parquet(frame.path)
    assert after["hhid"].tolist() == [1.0, 1.0, 2.0, 3.0]


def test_a_write_counts_the_rows_it_wrote(frame):
    source = frame.path
    with Workspace() as work:
        write(work, frame, f"SELECT * FROM read_parquet('{source}') WHERE hhid = 1")
        assert row_count(frame.path) == 2
    assert frame.rows == 2


def test_a_dropped_column_takes_its_label_with_it(frame):
    """Rebuilt from what was written, not edited alongside it.

    Otherwise the label of a column a command dropped is still on the frame,
    and reappears on the next save attached to nothing.
    """
    with Workspace() as work:
        write(work, frame, f'SELECT "hhid", "province" FROM read_parquet(\'{frame.path}\')')
    assert set(frame.variables) == {"hhid", "province"}
    assert frame.labels == {"province": "Province"}


def test_a_rename_carries_the_label_to_the_new_name(frame):
    with Workspace() as work:
        write(
            work,
            frame,
            f'SELECT "hhid", "wage" AS "pay" FROM read_parquet(\'{frame.path}\')',
            renamed={"wage": "pay"},
        )
    assert frame.labels == {"pay": "Weekly wage"}
    assert "wage" not in frame.variables
