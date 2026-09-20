"""Every path that replaces a dataset has to replay what was recorded on it.

There is more than one such path - an uploaded archive, a queued archive, a
connection sync - and they were not all wired: the sync, which is how a newer
export usually arrives, dropped every generated variable while its command sat
recorded on the dataset.

So this tests the rule rather than one caller. A new way to replace a dataset
is the exact change that should fail here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCES = [
    Path("app/workers/tasks.py"),
    Path("app/api/v1/endpoints/datasets.py"),
]


def _calls_to(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_every_archive_import_replays_recorded_commands(source: Path):
    calls = _calls_to(ast.parse(source.read_text()), "load_archive_as_datasets")
    assert calls, f"{source} no longer imports archives; drop it from SOURCES"
    for call in calls:
        passed = {kw.arg for kw in call.keywords}
        assert "after_replace" in passed, (
            f"{source}:{call.lineno} replaces datasets without replaying the "
            f"commands recorded on them. Pass after_replace=stata.replay."
        )


def test_publishing_a_reviewed_import_replays_before_it_rebuilds():
    """Order, not merely presence.

    A merge standing on a generated variable cannot be rebuilt until the
    variable is back, and the row counts in the job summary are read from the
    datasets - so a `drop if` that has not run yet is reported as the file's
    rows rather than the dataset's.
    """
    body = Path("app/services/import_review.py").read_text()
    replay = body.index("stata.replay(db, target)")
    rebuild = body.index("rebuild_dependents(db, [d.id for d in published])")
    counts = body.index('"rows": sum(d.row_count for d in published)')
    assert replay < rebuild, "the rebuild runs before the replay"
    assert replay < counts, "the row counts are read before the replay"
