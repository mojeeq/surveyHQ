"""A project's do-file: reading datasets, and writing new ones.

The command engine used to work on one dataset in place, which is fine for
tidying a file and no use at all for the thing a project is for - reading
several files, putting them together and writing out something new.

What holds this together is Stata's own rule, and it is the rule worth pinning
here: `use` loads a copy, the commands change the copy, and nothing on disk
moves until a `save` says so. A script that loads, edits and forgets to save
leaves the project exactly as it found it. That is the difference between a
script you can re-run and one you can only run once.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import select

from app.models import Dataset
from app.services import stata
from app.services.stata import CommandError, ScriptError
from tests.test_api_analytics import _stata_bytes, _zip_bytes

MEMBERS = pd.DataFrame(
    {
        "interview__key": [f"k{i}" for i in range(6)],
        "hhid": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
        "age": [17.0, 25.0, 40.0, 63.0, 12.0, 30.0],
        "wage": [0.0, 200.0, 300.0, 400.0, 0.0, 600.0],
    }
)


@pytest.fixture
def project(client, auth_headers, request, db_session) -> dict:
    """A project holding one uploaded dataset, ready for a script."""
    name = request.node.name[:36]
    made = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": f"P {name}"}
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "members.zip",
                _zip_bytes({"members.dta": _stata_bytes(MEMBERS)}),
                "application/zip",
            )
        },
    ).json()
    dataset_id = uploaded["datasets"][0]["id"]
    moved = client.put(
        f"/api/v1/projects/assign/dataset/{dataset_id}",
        headers=auth_headers,
        json={"project_id": made["id"]},
    )
    assert moved.status_code == 200, moved.text
    named = client.patch(
        f"/api/v1/datasets/{dataset_id}", headers=auth_headers, json={"name": "members"}
    )
    assert named.status_code < 300, named.text
    return {"id": made["id"], "dataset_id": dataset_id}


def script(db_session, project: dict, text: str):
    outcome = stata.run_project_script(db_session, project["id"], text)
    db_session.flush()
    return outcome


def dataset_named(db_session, project: dict, name: str) -> Dataset | None:
    return (
        db_session.execute(
            select(Dataset).where(
                Dataset.project_id == project["id"], Dataset.name == name
            )
        )
        .scalars()
        .first()
    )


def columns_of(dataset: Dataset) -> set[str]:
    return {variable.name for variable in dataset.variables}


# --- nothing moves until a save --------------------------------------------


def test_work_without_a_save_changes_nothing(db_session, project):
    """The rule the whole thing rests on."""
    outcome = script(
        db_session,
        project,
        "use members\ngen adult = age >= 18\ndrop if age < 18",
    )
    assert outcome.saved == []

    source = db_session.get(Dataset, project["dataset_id"])
    assert "adult" not in columns_of(source), "the script wrote to the file it read"
    assert source.row_count == 6, "the script dropped rows from the file it read"


def test_save_as_makes_a_new_dataset_and_leaves_the_original(db_session, project):
    outcome = script(
        db_session,
        project,
        "use members\ngen adult = age >= 18\nsave as adults",
    )
    assert [(entry.name, entry.created) for entry in outcome.saved] == [("adults", True)]

    made = dataset_named(db_session, project, "adults")
    assert made is not None
    assert "adult" in columns_of(made)
    assert made.row_count == 6

    source = db_session.get(Dataset, project["dataset_id"])
    assert "adult" not in columns_of(source)


def test_a_new_dataset_lands_in_the_same_project(db_session, project):
    script(db_session, project, "use members\nsave as copy")
    made = dataset_named(db_session, project, "copy")
    assert made is not None and made.project_id == project["id"]


def test_save_replace_writes_back_over_what_was_loaded(db_session, project):
    script(db_session, project, "use members\ngen adult = age >= 18\nsave, replace")
    source = db_session.get(Dataset, project["dataset_id"])
    assert "adult" in columns_of(source)


def test_a_bare_save_refuses_rather_than_overwriting(db_session, project):
    """Stata's rule, and the one that stops a script eating the file it read."""
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use members\ngen adult = age >= 18\nsave")
    assert "replace" in str(raised.value)

    source = db_session.get(Dataset, project["dataset_id"])
    assert "adult" not in columns_of(source)


def test_save_as_will_not_quietly_take_a_name_already_in_use(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use members\nsave as members")
    assert "already exists" in str(raised.value)


# --- what the script can reach ---------------------------------------------


def test_use_names_a_dataset_of_this_project(db_session, project):
    outcome = script(db_session, project, "use members")
    assert "6 row(s)" in outcome.results[0].message


def test_use_does_not_mind_the_case_it_is_typed_in(db_session, project):
    assert script(db_session, project, "use MEMBERS").results


def test_a_dataset_the_project_does_not_have_says_so(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use wages")
    assert "no dataset called 'wages'" in str(raised.value)


def test_a_dataset_in_another_project_is_not_reachable(
    db_session, project, client, auth_headers
):
    """A project's script reads the project's own data and nothing else."""
    other = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Somewhere else"}
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "secret.zip",
                _zip_bytes({"secret.dta": _stata_bytes(MEMBERS)}),
                "application/zip",
            )
        },
    ).json()
    elsewhere = uploaded["datasets"][0]["id"]
    client.put(
        f"/api/v1/projects/assign/dataset/{elsewhere}",
        headers=auth_headers,
        json={"project_id": other["id"]},
    )
    client.patch(
        f"/api/v1/datasets/{elsewhere}", headers=auth_headers, json={"name": "secret"}
    )
    db_session.expire_all()

    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use secret")
    assert "no dataset called 'secret'" in str(raised.value)


def test_a_command_before_any_use_says_what_is_missing(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "gen adult = age >= 18")
    assert "no data in memory" in str(raised.value).lower()


# --- running it more than once ---------------------------------------------


def test_a_second_use_starts_again_rather_than_adding_to_the_first(db_session, project):
    """Each `use` opens a section, so a script reads as a list of them."""
    script(
        db_session,
        project,
        "use members\ngen adult = age >= 18\nsave as adults\n"
        "use members\ngen earner = wage > 0\nsave as earners",
    )
    earners = dataset_named(db_session, project, "earners")
    assert earners is not None
    assert "earner" in columns_of(earners)
    assert "adult" not in columns_of(earners), "the second section kept the first's work"


def test_the_same_script_twice_is_refused_rather_than_duplicating(db_session, project):
    """Not silently making adults, adults (1), adults (2)."""
    text = "use members\ngen adult = age >= 18\nsave as adults"
    script(db_session, project, text)
    with pytest.raises(ScriptError):
        script(db_session, project, text)
    made = (
        db_session.execute(
            select(Dataset).where(
                Dataset.project_id == project["id"], Dataset.name == "adults"
            )
        )
        .scalars()
        .all()
    )
    assert len(made) == 1


def test_saving_again_after_more_work_writes_over_what_was_just_made(
    db_session, project
):
    script(
        db_session,
        project,
        "use members\nsave as adults\ngen adult = age >= 18\nsave, replace",
    )
    made = dataset_named(db_session, project, "adults")
    assert made is not None and "adult" in columns_of(made)


# --- a script that stops partway -------------------------------------------


def test_a_failure_leaves_the_saves_before_it_and_nothing_after(db_session, project):
    """What ran stays run, which is what Stata does and what makes it debuggable."""
    with pytest.raises(ScriptError) as raised:
        script(
            db_session,
            project,
            "use members\nsave as first\ngen adult = ages >= 18\nsave as second",
        )
    assert raised.value.line_number == 3

    assert dataset_named(db_session, project, "first") is not None
    assert dataset_named(db_session, project, "second") is None


def test_an_empty_script_says_there_is_nothing_to_run(db_session, project):
    with pytest.raises(CommandError):
        script(db_session, project, "   \n * only a comment\n")


# --- what a command must not quietly drop -----------------------------------


def test_a_tagged_missing_survives_every_command_that_touches_the_data(
    db_session, project
):
    """A .a is not the same blank as a plain one, and only a companion says so.

    Ingest writes the tags into a column beside the variable, hidden from the
    interface. Every command rebuilds the data by listing the variables it is
    keeping, so a companion missing from that list is a companion dropped -
    after which `wage` still has its blanks and nothing left saying which of
    them the field worker marked "refused".
    """
    from app.models import Variable, VariableType

    source = db_session.get(Dataset, project["dataset_id"])
    stored = pd.read_parquet(source.storage_path)
    stored["wage__mv"] = [None, None, ".a", None, None, ".b"]
    stored.to_parquet(source.storage_path, index=False)
    db_session.add(
        Variable(
            dataset_id=source.id,
            name="wage__mv",
            var_type=VariableType.text,
            position=len(stored.columns) - 1,
            is_hidden=True,
        )
    )
    db_session.flush()

    script(
        db_session,
        project,
        "use members\ngen adult = age >= 18\ndrop if age < 12\nsave as adults",
    )
    made = dataset_named(db_session, project, "adults")
    assert made is not None
    assert "wage__mv" in columns_of(made), "the tags were dropped on the way through"
    assert sorted(
        tag for tag in pd.read_parquet(made.storage_path)["wage__mv"] if tag
    ) == [".a", ".b"]
