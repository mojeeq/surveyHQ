"""Importing several versions of one questionnaire in a single run.

A questionnaire revised mid-fieldwork lives on a Survey Solutions server as
v1, v2, v3 of one questionnaire, with the interviews spread across them. They
are one survey and belong in one dataset - the same thing appending three
exported zips by hand achieves.

The fault this pins down was silent. "Replace their data" applied to each
version in turn meant v2 replaced v1 and v3 replaced v2, so a run that reported
importing three versions left a dataset holding only the last one. Nothing
failed; the row count was simply lower than it should have been, which is the
kind of thing a monitoring platform must never do quietly.
"""

from __future__ import annotations

from app.workers.tasks import plan_version_imports

# Two questionnaires, three versions of the first and two of the second.
LFS = "11111111-1111-1111-1111-111111111111"
AG = "22222222-2222-2222-2222-222222222222"
VERSIONS = {
    f"{LFS}$1": 1,
    f"{LFS}$2": 2,
    f"{LFS}$3": 3,
    f"{AG}$4": 4,
    f"{AG}$5": 5,
}


def test_only_the_first_version_replaces_and_the_rest_append():
    plan = plan_version_imports(list(VERSIONS), VERSIONS, "replace")
    modes = dict(plan)
    assert modes[f"{LFS}$1"] == "replace"
    assert modes[f"{LFS}$2"] == "append"
    assert modes[f"{LFS}$3"] == "append"
    # The second questionnaire is its own dataset, so it replaces too.
    assert modes[f"{AG}$4"] == "replace"
    assert modes[f"{AG}$5"] == "append"


def test_versions_are_imported_oldest_first():
    """Order is the point: appending v1 onto v3 puts the rounds out of sequence."""
    shuffled = [f"{LFS}$3", f"{LFS}$1", f"{LFS}$2"]
    assert [identity for identity, _ in plan_version_imports(shuffled, VERSIONS, "replace")] == [
        f"{LFS}$1",
        f"{LFS}$2",
        f"{LFS}$3",
    ]


def test_each_questionnaire_is_kept_together():
    """Interleaved input still imports one questionnaire's versions in a run."""
    interleaved = [f"{AG}$5", f"{LFS}$2", f"{AG}$4", f"{LFS}$1"]
    order = [i for i, _ in plan_version_imports(interleaved, VERSIONS, "replace")]
    assert order.index(f"{LFS}$1") < order.index(f"{LFS}$2")
    assert order.index(f"{AG}$4") < order.index(f"{AG}$5")


def test_an_append_run_appends_everything():
    """Nothing is promoted to replace: append means append, for every version."""
    plan = plan_version_imports(list(VERSIONS), VERSIONS, "append")
    assert {mode for _, mode in plan} == {"append"}


def test_one_version_behaves_exactly_as_before():
    """The ordinary case - a single questionnaire, one version - is untouched."""
    assert plan_version_imports([f"{LFS}$3"], VERSIONS, "replace") == [(f"{LFS}$3", "replace")]


def test_a_version_the_catalogue_does_not_know_is_still_imported():
    """A questionnaire that vanished from the server between listing and import.

    It must not be dropped from the plan: silently importing four of five
    selected versions is the same class of fault as the one above.
    """
    identities = [f"{LFS}$1", f"{LFS}$9"]
    plan = plan_version_imports(identities, VERSIONS, "replace")
    assert [identity for identity, _ in plan] == [f"{LFS}$9", f"{LFS}$1"]
    assert len(plan) == 2


def test_nothing_selected_is_an_empty_plan():
    assert plan_version_imports([], VERSIONS, "replace") == []
