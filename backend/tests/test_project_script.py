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


# --- a run leaves its text behind -------------------------------------------
#
# Running and saving are separate on purpose: a script is tried before it is
# kept, so a run that fails does not have to be undone by hand. The cost was
# that a script run and never saved left nothing behind but the fact that it
# ran - the editor opened blank, and the commands that built the data were
# gone. They are kept now, beside the saved text rather than instead of it.


def _script_as_seen(client, headers, project_id) -> dict:
    answered = client.get(f"/api/v1/projects/{project_id}/script", headers=headers)
    assert answered.status_code == 200, answered.text
    return answered.json()


def test_a_run_that_was_never_saved_is_still_there_afterwards(
    client, auth_headers, db_session, project
):
    """The fault this exists for: the editor opened on nothing."""
    from app.services import project_script

    project_script.run(db_session, project["id"], "use members\ngen adult = age >= 18")
    db_session.commit()

    seen = _script_as_seen(client, auth_headers, project["id"])
    assert seen["text"] == "", "nothing was saved, and running must not save"
    assert seen["unsaved_run"] == "use members\ngen adult = age >= 18"


def test_a_run_of_the_saved_script_is_not_reported_as_unsaved(
    client, auth_headers, db_session, project
):
    """Otherwise every project that works the ordinary way carries a notice
    offering to restore what is already in front of it."""
    from app.services import project_script

    kept = client.put(
        f"/api/v1/projects/{project['id']}/script",
        headers=auth_headers,
        json={"text": "use members"},
    )
    assert kept.status_code == 200, kept.text
    db_session.expire_all()
    project_script.run(db_session, project["id"])
    db_session.commit()

    seen = _script_as_seen(client, auth_headers, project["id"])
    assert seen["text"] == "use members"
    assert seen["unsaved_run"] == ""


def test_a_run_that_failed_is_kept_too(client, auth_headers, db_session, project):
    """That is the one you most want back. The editor would otherwise open
    blank on the script that had just gone wrong."""
    from app.services import project_script

    with pytest.raises((ScriptError, CommandError)):
        project_script.run(
            db_session, project["id"], "use members\ngen adult = nonsense(age)"
        )
    db_session.commit()

    seen = _script_as_seen(client, auth_headers, project["id"])
    assert seen["text"] == ""
    assert "nonsense" in seen["unsaved_run"]


def test_saving_what_was_recovered_ends_the_notice(
    client, auth_headers, db_session, project
):
    """Save keeps it, and the two agree from then on."""
    from app.services import project_script

    project_script.run(db_session, project["id"], "use members")
    db_session.commit()
    recovered = _script_as_seen(client, auth_headers, project["id"])["unsaved_run"]

    kept = client.put(
        f"/api/v1/projects/{project['id']}/script",
        headers=auth_headers,
        json={"text": recovered},
    )
    assert kept.status_code == 200, kept.text

    seen = _script_as_seen(client, auth_headers, project["id"])
    assert seen["text"] == "use members"
    assert seen["unsaved_run"] == ""


# --- deleting a script ------------------------------------------------------
#
# Clearing the box and saving was the nearest thing and is not the same: the
# row stays, with what the last run read, wrote and ran still on it, so the
# project keeps its place on the Scripts page and the editor offers the old
# run back. There was no way to say "this script should not exist".


def test_deleting_a_script_leaves_the_data_it_built(
    client, auth_headers, db_session, project
):
    """A script is a recipe. Deleting the recipe does not unmake the dinner."""
    from app.services import project_script

    project_script.run(
        db_session, project["id"], 'use members\ngen adult = age >= 18\nsave as "adults"'
    )
    db_session.commit()
    built = dataset_named(db_session, project, "adults")
    assert built is not None, "the script has to have built something to prove this"
    rows = built.row_count

    gone = client.delete(
        f"/api/v1/projects/{project['id']}/script", headers=auth_headers
    )
    assert gone.status_code == 200, gone.text

    db_session.expire_all()
    after = dataset_named(db_session, project, "adults")
    assert after is not None, "deleting the script must not delete what it wrote"
    assert after.row_count == rows


def test_a_deleted_script_takes_its_last_run_with_it(
    client, auth_headers, db_session, project
):
    """Including the text the editor would otherwise offer back, which is the
    difference between deleting it and clearing the box."""
    from app.services import project_script

    project_script.run(db_session, project["id"], "use members")
    db_session.commit()
    assert _script_as_seen(client, auth_headers, project["id"])["unsaved_run"]

    client.delete(f"/api/v1/projects/{project['id']}/script", headers=auth_headers)

    seen = _script_as_seen(client, auth_headers, project["id"])
    assert seen["text"] == ""
    assert seen["unsaved_run"] == ""
    assert seen["reads"] == []
    assert seen["writes"] == []
    assert seen["last_run_at"] is None


def test_a_deleted_script_drops_off_the_overview(
    client, auth_headers, db_session, project
):
    """Which is what somebody deleting it is asking for."""
    from app.services import project_script

    project_script.run(db_session, project["id"], "use members")
    db_session.commit()

    def listed() -> bool:
        places = client.get("/api/v1/scripts", headers=auth_headers).json()["places"]
        return any(place["project_id"] == project["id"] for place in places)

    assert listed(), "it has run, so it belongs on the page until it is deleted"
    client.delete(f"/api/v1/projects/{project['id']}/script", headers=auth_headers)
    assert not listed()


def test_deleting_a_script_that_is_not_there_is_not_an_error(
    client, auth_headers, project
):
    """A row is made the first time anybody opens the tab, so its absence is
    ordinary, and "already gone" is the state being asked for."""
    first = client.delete(
        f"/api/v1/projects/{project['id']}/script", headers=auth_headers
    )
    second = client.delete(
        f"/api/v1/projects/{project['id']}/script", headers=auth_headers
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text


def test_deleting_a_script_needs_the_manager_role_over_the_project(
    client, auth_headers, db_session, project
):
    """The same as writing it. Seeing a project has never been grounds for
    throwing away the recipe its data is built from."""
    from app.core.security import hash_password
    from app.models import ProjectMember, Role, User

    onlooker = User(
        email="onlooker@example.org",
        username="onlooker",
        full_name="An Onlooker",
        hashed_password=hash_password("Fieldwork-2026-look"),
        role=Role.manager,
    )
    db_session.add(onlooker)
    db_session.flush()
    db_session.add(
        ProjectMember(
            project_id=project["id"], user_id=onlooker.id, role=Role.viewer
        )
    )
    db_session.commit()

    token = client.post(
        "/api/v1/auth/login",
        json={"email": "onlooker@example.org", "password": "Fieldwork-2026-look"},
    ).json()["access_token"]
    refused = client.delete(
        f"/api/v1/projects/{project['id']}/script",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert refused.status_code in (403, 404), refused.text


def test_a_run_that_never_started_still_keeps_what_was_typed(
    client, auth_headers, project
):
    """A script with no command in it stops before anything runs, and the
    endpoint used to unwind that - throwing away the draft by the act of
    trying it, so the editor opened blank on what had just been lost."""
    refused = client.post(
        f"/api/v1/projects/{project['id']}/script/run",
        headers=auth_headers,
        json={"text": "* a draft I typed, all comments so far\n* second line"},
    )
    assert refused.status_code == 422, refused.text

    seen = _script_as_seen(client, auth_headers, project["id"])
    assert "all comments so far" in seen["unsaved_run"]


def test_a_box_of_spaces_is_not_a_script(client, auth_headers, db_session, project):
    """Saved whitespace counts as empty for whether it is saved, so it has to
    count as empty for what is counted too. It did not, so a card read "Run
    without being saved" over a run of three commands."""
    from app.services import project_script

    kept = client.put(
        f"/api/v1/projects/{project['id']}/script",
        headers=auth_headers,
        json={"text": "   \n  \n"},
    )
    assert kept.status_code == 200, kept.text
    db_session.expire_all()
    project_script.run(db_session, project["id"], "use members\ngen a = 1\ngen b = 2")
    db_session.commit()

    mine = next(
        place
        for place in client.get("/api/v1/scripts", headers=auth_headers).json()["places"]
        if place["project_id"] == project["id"]
    )
    assert mine["saved"] is False
    assert mine["lines"] == 3, "the run is what a reader is looking at"

    # And the editor is offered it, rather than the spaces.
    seen = _script_as_seen(client, auth_headers, project["id"])
    assert "gen b = 2" in seen["unsaved_run"]


def test_a_run_behind_a_saved_script_is_offered_not_lost(
    client, auth_headers, db_session, project
):
    """Saved A, ran B without saving. Both are real and they are different
    things - one kept, one tried - so both have to be reachable. B was
    recorded and then unreachable, which is a worse answer than not
    recording it."""
    from app.services import project_script

    client.put(
        f"/api/v1/projects/{project['id']}/script",
        headers=auth_headers,
        json={"text": "use members"},
    )
    db_session.expire_all()
    project_script.run(db_session, project["id"], "use members\ngen tried = 1")
    db_session.commit()

    seen = _script_as_seen(client, auth_headers, project["id"])
    assert seen["text"] == "use members", "the saved script is still the script"
    assert "gen tried = 1" in seen["unsaved_run"], "and the run is still there"


def test_a_run_that_never_started_keeps_the_last_real_run_s_dependencies(
    client, auth_headers, db_session, project
):
    """Trying a half-written draft must not unhook the script from its data.

    `reads` and `writes` are what the last run actually touched, and they are
    how a newer export finds the scripts standing on it and how a script keeps
    the right to rewrite its own output. A script with no command in it never
    ran, so it touched nothing - and recording that as "touched nothing" threw
    away the real run's record, leaving the outputs stale with nothing to say
    so.
    """
    from sqlalchemy import select

    from app.models import ProjectScript
    from app.services import project_script

    project_script.run(
        db_session, project["id"], 'use members\ngen adult = age >= 18\nsave as "adults"'
    )
    db_session.commit()
    script = db_session.scalar(
        select(ProjectScript).where(ProjectScript.project_id == project["id"])
    )
    reads, writes, ran_at = list(script.reads), list(script.writes), script.last_run_at
    assert reads and writes, "the first run has to have touched something"

    refused = client.post(
        f"/api/v1/projects/{project['id']}/script/run",
        headers=auth_headers,
        json={"text": "* half written, nothing to run yet"},
    )
    assert refused.status_code == 422, refused.text

    db_session.expire_all()
    after = db_session.scalar(
        select(ProjectScript).where(ProjectScript.project_id == project["id"])
    )
    assert list(after.reads) == reads, "the scripts standing on this data are found by reads"
    assert list(after.writes) == writes, "and `save as` keeps its own output by writes"
    assert after.last_run_at == ran_at, "nothing ran, so nothing is a newer run"
    # And the draft is still kept, which is what the commit was for.
    assert "half written" in after.last_run_text
