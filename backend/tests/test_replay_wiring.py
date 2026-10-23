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

#: Callers that replay later instead, by the functions that do it for them.
#:
#: More than one may: the same archive import serves a server connection and a
#: folder connection, and each replays once it has imported everything it is
#: going to. Naming only one of them would leave the other free to stop.
DEFERRED = {
    "_import_export_archive": ("run_connection_sync", "run_folder_import"),
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
    """Replays itself, or hands the replay to the pipeline and says to do it."""
    node = _functions(tree).get(function)
    if node is None:
        return False
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        if isinstance(inner.func, ast.Attribute) and inner.func.attr == "replay":
            return True
        if isinstance(inner.func, ast.Name) and inner.func.id == "after_import":
            for keyword in inner.keywords:
                if (
                    keyword.arg == "replay"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    return True
    return False


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
        for later in deferred_to:
            assert _replays(tree, later), (
                f"{source}:{call.lineno} defers its replay to {later}(), "
                f"which no longer replays anything."
            )


#: Every way data arrives, by the function that receives it. Each has to hand
#: what it wrote to the pipeline, or the merges, scripts and dashboards built
#: on that data stay where they were - which is how a sync came to rebuild
#: merges and never run a script, and an append to rebuild nothing at all.
ARRIVALS = [
    (Path("app/workers/tasks.py"), "run_connection_sync"),
    (Path("app/workers/tasks.py"), "run_folder_import"),
    (Path("app/workers/tasks.py"), "run_upload_import"),
    (Path("app/api/v1/endpoints/datasets.py"), "upload_dataset"),
    (Path("app/services/import_review.py"), "accept"),
    (Path("app/cli.py"), "import_files"),
]


@pytest.mark.parametrize("source,function", ARRIVALS, ids=lambda one: str(one))
def test_every_way_data_arrives_goes_through_the_pipeline(source: Path, function: str):
    tree = ast.parse(source.read_text())
    node = _functions(tree).get(function)
    assert node is not None, f"{source} has no {function}(); update ARRIVALS"
    assert any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "after_import"
        for inner in ast.walk(node)
    ), f"{function}() in {source} brings data in without calling after_import"


@pytest.mark.parametrize("source,function", ARRIVALS, ids=lambda one: str(one))
def test_nothing_rebuilds_merges_beside_the_pipeline(source: Path, function: str):
    """A second copy of the order is how the copies drifted apart."""
    node = _functions(ast.parse(source.read_text()))[function]
    names = {
        inner.func.id
        for inner in ast.walk(node)
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
    }
    assert not names & {"rebuild_dependents", "rebuild_merges"}, (
        f"{function}() rebuilds merges itself; leave that to after_import"
    )


def test_the_pipeline_replays_then_merges_then_scripts_then_dashboards():
    """Order, not merely presence.

    A merge standing on a generated variable cannot be rebuilt until the
    variable is back; a script reading a merged dataset has to wait for the
    merge; and the dashboards are named from what all of that wrote.
    """
    body = Path("app/services/pipeline.py").read_text()
    start = body.index("def after_import(")
    inside = body[start : body.index("\ndef ", start + 1)]
    replay = inside.index("stata.replay(db, dataset)")
    merges = inside.index("rebuild_merges(db, changed)")
    scripts = inside.index("project_script.rerun_for(db, standing)")
    boards = inside.index("_dashboards_on(db, affected)")
    assert replay < merges < scripts < boards


def test_publishing_a_reviewed_import_replays_before_it_counts():
    """The row counts in the job summary are read from the datasets - so a
    `drop if` that has not run yet is reported as the file's rows."""
    body = Path("app/services/import_review.py").read_text()
    pipeline = body.index("after_import(db, changed=ids, replaced=ids, replay=True")
    counts = body.index('"rows": sum(d.row_count for d in published)')
    assert pipeline < counts, "the row counts are read before the replay"


def test_a_sync_replays_after_every_version_is_in_and_counts_after_that():
    """The deferred replay has an order of its own.

    It has to sit after the loop that imports the plan, or it sees only the
    versions imported so far; and the row counts have to be read after it.
    """
    body = Path("app/workers/tasks.py").read_text()
    sync = body[body.index("def run_connection_sync(") : body.index("def run_folder_import(")]
    loop = sync.index("for number, (identity, identity_mode) in enumerate(plan, start=1):")
    pipeline = sync.index("aftermath = after_import(")
    counts = sync.index('entry["rows"] = dataset.row_count')
    assert loop < pipeline, "the sync replays before it has imported every version"
    assert pipeline < counts, "the sync reports row counts read before the replay"


def test_a_sync_replays_only_what_it_replaced():
    """An append leaves the generated columns in place.

    Replaying the whole history over one would apply every command a second
    time to rows that already carry it: `replace score = score + 1` adds two,
    and a recorded `gen` fails because its column exists. Only a replacement
    wipes those columns, and only a replacement earns the full replay - while
    everything the plan wrote, appends included, is what the merges follow.
    """
    body = Path("app/workers/tasks.py").read_text()
    assert '"replaced_ids": list(result.replaced_ids)' in body
    assert "replaced.extend(outcome.get(\"replaced_ids\") or [])" in body
    assert "changed=changed," in body and "replaced=replaced," in body
    assert "touched.extend(" not in body


def test_a_folder_import_goes_through_the_pipeline_in_the_same_order_a_sync_does():
    """The folder path is the sync with the download taken out, and it owes
    the same order: the pipeline after every file is in, then the counts."""
    body = Path("app/workers/tasks.py").read_text()
    folder = body.index("def run_folder_import(")
    nextdef = body.index("def _import_export_archive(", folder)
    inside = body[folder:nextdef]

    loop = inside.index("for number, found in enumerate(pending, start=1):")
    pipeline = inside.index("aftermath = after_import(")
    counts = inside.index('entry["rows"] = dataset.row_count')
    assert loop < pipeline < counts
