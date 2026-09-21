"""Every path that replaces a dataset has to replay what was recorded on it.

There is more than one such path - an uploaded archive, a queued archive, a
connection sync - and they were not all wired: the sync, which is how a newer
export usually arrives, dropped every generated variable while its command sat
recorded on the dataset.

So this tests the rule rather than one caller. A new way to replace a dataset
is the exact change that should fail here.

The rule has two shapes, because one path cannot use the first. A questionnaire
revised mid-fieldwork arrives as several versions - the first replaces what is
stored, the rest are appended onto it - and `after_replace` fires only on the
replacement. Replaying there would compute a generated variable over the first
version's rows and leave it blank on every later one. That path therefore
replays once the whole plan is in, and is listed below with that reason rather
than being quietly skipped.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCES = [
    Path("app/workers/tasks.py"),
    Path("app/api/v1/endpoints/datasets.py"),
]

#: Callers that replay later instead, by the function that does it for them.
DEFERRED = {
    "_import_export_archive": "run_connection_sync",
}


def _functions(tree: ast.AST) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _enclosing(tree: ast.AST, call: ast.Call) -> str:
    for name, node in _functions(tree).items():
        if any(inner is call for inner in ast.walk(node)):
            return name
    return ""


def _calls_to(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def _replays(tree: ast.AST, function: str) -> bool:
    node = _functions(tree).get(function)
    return node is not None and any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and inner.func.attr == "replay"
        for inner in ast.walk(node)
    )


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_every_archive_import_replays_recorded_commands(source: Path):
    tree = ast.parse(source.read_text())
    calls = _calls_to(tree, "load_archive_as_datasets")
    assert calls, f"{source} no longer imports archives; drop it from SOURCES"
    for call in calls:
        if "after_replace" in {kw.arg for kw in call.keywords}:
            continue
        deferred_to = DEFERRED.get(_enclosing(tree, call))
        assert deferred_to, (
            f"{source}:{call.lineno} replaces datasets without replaying the "
            f"commands recorded on them. Pass after_replace=stata.replay, or "
            f"replay afterwards and say so in DEFERRED."
        )
        assert _replays(tree, deferred_to), (
            f"{source}:{call.lineno} defers its replay to {deferred_to}(), "
            f"which no longer replays anything."
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


def test_a_sync_replays_after_every_version_is_in_and_rebuilds_after_that():
    """The deferred replay has an order of its own.

    It has to sit after the loop that imports the plan, or it sees only the
    versions imported so far; and the dependent rebuild has to sit after it, or
    the merges are built from an export the commands have not touched.
    """
    body = Path("app/workers/tasks.py").read_text()
    loop = body.index("for identity, identity_mode in plan:")
    replay = body.index("problems.extend(stata.replay(db, dataset))")
    rebuild = body.index("rebuild_dependents(db, ids)")
    counts = body.index('entry["rows"] = dataset.row_count')
    assert loop < replay, "the sync replays before it has imported every version"
    assert replay < rebuild, "the sync rebuilds dependents before it replays"
    assert replay < counts, "the sync reports row counts read before the replay"


def test_a_sync_replays_only_what_it_replaced():
    """An append leaves the generated columns in place.

    Replaying the whole history over one would apply every command a second
    time to rows that already carry it: `replace score = score + 1` adds two,
    and a recorded `gen` fails because its column exists. Only a replacement
    wipes those columns, and only a replacement earns the full replay.
    """
    body = Path("app/workers/tasks.py").read_text()
    assert '"replaced_ids": list(result.replaced_ids)' in body
    assert "replaced.extend(outcome.get(\"replaced_ids\") or [])" in body
    # The word itself is fine in the comment that explains the distinction;
    # what must not come back is a list of everything the plan touched.
    assert "touched.extend(" not in body, (
        "the sync is collecting every dataset it touched, not only the ones it "
        "replaced, so an append would be replayed over twice"
    )
