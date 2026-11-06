"""Several scripts in one project.

A project had one script, which is not how anybody works: the roster is
cleaned in one do-file, the household file built in a second, the tables made
in a third. Put in one box, a fix to the tables meant re-running the cleaning,
and the three could not be read, run or ordered apart.

So a script is known by its own id and called by a name the project has not
used. What ran before still holds per script: what its last run read and
wrote, what it may rebuild, and where it sits in the order - which now has to
be worked out between two scripts of the same project as much as between
projects.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from app.models import Dataset, ProjectScript
from tests.test_project_script_rerun import (  # noqa: F401 - a fixture
    SCRIPT,
    project,
    upload_again,
)

BASE = "/api/v1/scripts"


def start(client, auth_headers, project, name="", text=""):  # noqa: F811
    response = client.post(
        BASE,
        headers=auth_headers,
        json={"project_id": project["id"], "name": name, "text": text},
    )
    assert response.status_code == 201, response.text
    return response.json()


def run(client, auth_headers, script_id, text=None):
    return client.post(f"{BASE}/{script_id}/run", headers=auth_headers, json={"text": text})


def built(db_session, project, name):  # noqa: F811
    db_session.expire_all()
    found = db_session.scalars(
        select(Dataset).where(Dataset.project_id == project["id"], Dataset.name == name)
    ).first()
    assert found is not None, f"nothing built '{name}'"
    return pd.read_parquet(found.storage_path)


def in_overview(client, auth_headers, project):  # noqa: F811
    places = client.get(BASE, headers=auth_headers).json()["places"]
    return [place for place in places if place["project_id"] == project["id"]]


# --- starting, naming -------------------------------------------------------


def test_a_project_holds_two_scripts_each_run_on_its_own(
    client, auth_headers, project, db_session  # noqa: F811
):
    totals = start(client, auth_headers, project, "Totals", SCRIPT)
    counts = start(
        client,
        auth_headers,
        project,
        "Counts",
        "use households\ncollapse (count) hhid, by(province)\nsave as counts",
    )
    assert totals["id"] != counts["id"]

    assert run(client, auth_headers, totals["id"]).status_code == 200
    # Only the one asked for ran.
    db_session.expire_all()
    assert db_session.get(ProjectScript, counts["id"]).last_run_at is None
    assert run(client, auth_headers, counts["id"]).status_code == 200

    assert len(built(db_session, project, "totals")) == 3
    assert len(built(db_session, project, "counts")) == 3
    listed = {place["name"]: place for place in in_overview(client, auth_headers, project)}
    assert set(listed) == {"Totals", "Counts"}
    assert listed["Totals"]["writes"] == ["totals"]
    assert listed["Counts"]["writes"] == ["counts"]


def test_a_script_with_no_name_is_called_what_the_project_has_not_used(
    client, auth_headers, project  # noqa: F811
):
    first = start(client, auth_headers, project)
    second = start(client, auth_headers, project)
    assert (first["name"], second["name"]) == ("Main script", "Main script 2")


def test_a_name_the_project_already_has_is_refused_in_any_case(
    client, auth_headers, project  # noqa: F811
):
    start(client, auth_headers, project, "Clean roster")
    again = client.post(
        BASE,
        headers=auth_headers,
        json={"project_id": project["id"], "name": "  clean   ROSTER "},
    )
    assert again.status_code == 422
    assert "already has a script called" in again.json()["detail"]


def test_a_script_can_be_renamed_but_not_onto_another(
    client, auth_headers, project  # noqa: F811
):
    keep = start(client, auth_headers, project, "Tables")
    other = start(client, auth_headers, project, "Draft")

    renamed = client.patch(
        f"{BASE}/{other['id']}", headers=auth_headers, json={"name": "Household file"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Household file"

    clash = client.patch(
        f"{BASE}/{other['id']}", headers=auth_headers, json={"name": "tables"}
    )
    assert clash.status_code == 422
    # Its own name, in another case, is not a clash with itself.
    same = client.patch(f"{BASE}/{keep['id']}", headers=auth_headers, json={"name": "TABLES"})
    assert same.status_code == 200, same.text
    blank = client.patch(f"{BASE}/{keep['id']}", headers=auth_headers, json={"name": "  "})
    assert blank.status_code == 422


def test_saving_text_leaves_the_name_alone(client, auth_headers, project):  # noqa: F811
    made = start(client, auth_headers, project, "Tables")
    saved = client.patch(
        f"{BASE}/{made['id']}", headers=auth_headers, json={"text": "use households"}
    ).json()
    assert (saved["name"], saved["text"]) == ("Tables", "use households")
    assert saved["project_id"] == project["id"] and saved["project_name"]


def test_deleting_one_script_leaves_the_other_and_every_dataset(
    client, auth_headers, project, db_session  # noqa: F811
):
    totals = start(client, auth_headers, project, "Totals", SCRIPT)
    other = start(client, auth_headers, project, "Other", "use households")
    run(client, auth_headers, totals["id"])

    gone = client.delete(f"{BASE}/{totals['id']}", headers=auth_headers)
    assert gone.status_code == 200, gone.text
    assert "'Totals' deleted" in gone.json()["detail"]

    assert client.get(f"{BASE}/{totals['id']}", headers=auth_headers).status_code == 404
    assert client.get(f"{BASE}/{other['id']}", headers=auth_headers).status_code == 200
    assert len(built(db_session, project, "totals")) == 3


def test_a_second_script_does_not_take_over_what_the_first_built(
    client, auth_headers, project  # noqa: F811
):
    """What a script may rebuild is what it built, not what its project did.

    Two scripts saving to one name would each overwrite the other on every
    import, and which won would depend on which ran last. `replace` still
    says so when that is what is meant.
    """
    first = start(client, auth_headers, project, "Totals", SCRIPT)
    assert run(client, auth_headers, first["id"]).status_code == 200
    second = start(client, auth_headers, project, "Also totals", SCRIPT)

    refused = run(client, auth_headers, second["id"])
    assert refused.status_code == 422
    assert "was not built by this script" in refused.json()["detail"]
    # And the first still rebuilds its own.
    assert run(client, auth_headers, first["id"]).status_code == 200


# --- the order between them --------------------------------------------------


def test_a_script_reading_another_in_its_project_waits_for_it(
    client, auth_headers, project  # noqa: F811
):
    wages = start(
        client, auth_headers, project, "Wages", "use households\nkeep hhid wage\nsave as wages"
    )
    run(client, auth_headers, wages["id"])
    copy = start(client, auth_headers, project, "Copy", "use wages\nsave as wages_copy")
    run(client, auth_headers, copy["id"])

    listed = {place["name"]: place for place in in_overview(client, auth_headers, project)}
    assert listed["Copy"]["step"] == listed["Wages"]["step"] + 1
    assert listed["Copy"]["waits_for"] == [listed["Wages"]["label"]]


def test_a_new_export_runs_a_projects_scripts_in_the_order_they_need(
    client, auth_headers, project, db_session  # noqa: F811
):
    """Both read the export, so both are ready in the same round, and one also
    reads what the other writes. Run the wrong way round, the second rebuilds
    on the first one's output from before the import and is then counted as
    done.

    Set up so that every order but the right one would get it wrong: the
    reader is called first alphabetically and was started first.
    """
    copy = start(
        client,
        auth_headers,
        project,
        "Copy",
        "use households\nkeep hhid\nsave as ids\nuse wages\nsave as wages_copy",
    )
    wages = start(
        client, auth_headers, project, "Wages", "use households\nkeep hhid wage\nsave as wages"
    )
    assert run(client, auth_headers, wages["id"]).status_code == 200
    assert run(client, auth_headers, copy["id"]).status_code == 200
    assert len(built(db_session, project, "wages_copy")) == 3

    body = upload_again(client, auth_headers, project)

    assert len(built(db_session, project, "wages")) == 4
    assert len(built(db_session, project, "wages_copy")) == 4, "ran before what it reads"
    assert any("wages_copy" in line for line in body.get("warnings", [])), body


def test_a_script_left_unsaved_is_named_in_the_upload_by_its_name(
    client, auth_headers, project, db_session  # noqa: F811
):
    made = start(client, auth_headers, project, "Roster checks")
    assert run(client, auth_headers, made["id"], SCRIPT).status_code == 200
    db_session.expire_all()
    db_session.get(ProjectScript, made["id"]).text = ""
    db_session.commit()

    body = upload_again(client, auth_headers, project)
    assert any(
        "'Roster checks' in" in line and "was never saved" in line
        for line in body.get("warnings", [])
    ), body.get("warnings")


# --- the endpoints from when there was one ----------------------------------


def test_the_project_script_endpoints_mean_the_oldest_script(
    client, auth_headers, project  # noqa: F811
):
    first = start(client, auth_headers, project, "First", "use households")
    start(client, auth_headers, project, "Second", "use households\ncount")

    read = client.get(f"/api/v1/projects/{project['id']}/script", headers=auth_headers).json()
    assert (read["id"], read["name"]) == (first["id"], "First")

    client.put(
        f"/api/v1/projects/{project['id']}/script",
        headers=auth_headers,
        json={"text": SCRIPT},
    )
    again = client.get(f"{BASE}/{first['id']}", headers=auth_headers).json()
    assert again["text"] == SCRIPT


def test_reading_a_project_with_no_script_does_not_make_one(
    client, auth_headers, project, db_session  # noqa: F811
):
    """Opening a page used to leave a row behind on every project somebody
    looked at, and every row is a script now."""
    read = client.get(f"/api/v1/projects/{project['id']}/script", headers=auth_headers)
    assert read.status_code == 200, read.text
    assert read.json()["text"] == "" and read.json()["id"] == ""
    db_session.expire_all()
    assert not db_session.scalars(
        select(ProjectScript).where(ProjectScript.project_id == project["id"])
    ).all()


def test_the_project_overview_lists_every_script(client, auth_headers, project):  # noqa: F811
    one = start(client, auth_headers, project, "Clean", SCRIPT)
    start(client, auth_headers, project, "Tables")
    run(client, auth_headers, one["id"])

    body = client.get(
        f"/api/v1/projects/{project['id']}/overview", headers=auth_headers
    ).json()
    assert [script["name"] for script in body["scripts"]] == ["Clean", "Tables"]
    assert body["scripts"][0]["runs_on_import"] is True
    assert body["scripts"][1]["saved"] is False
    assert [output["name"] for output in body["outputs"]] == ["totals"]


# --- who may ----------------------------------------------------------------


def test_a_viewer_can_read_a_script_and_not_start_change_or_run_one(
    client, auth_headers, project, db_session  # noqa: F811
):
    from app.core.security import hash_password
    from app.models import ProjectMember, Role, User

    made = start(client, auth_headers, project, "Tables", SCRIPT)
    viewer = User(
        email="script-viewer@example.org",
        username="script-viewer",
        full_name="Looks Only",
        hashed_password=hash_password("Fieldwork-2026-viewer"),
        role=Role.manager,
    )
    db_session.add(viewer)
    db_session.flush()
    db_session.add(ProjectMember(project_id=project["id"], user_id=viewer.id, role=Role.viewer))
    db_session.commit()
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "script-viewer@example.org", "password": "Fieldwork-2026-viewer"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get(f"{BASE}/{made['id']}", headers=headers).status_code == 200
    assert client.post(
        BASE, headers=headers, json={"project_id": project["id"], "name": "Mine"}
    ).status_code == 403
    assert client.patch(
        f"{BASE}/{made['id']}", headers=headers, json={"name": "Renamed"}
    ).status_code == 403
    assert run(client, headers, made["id"]).status_code == 403
    assert client.delete(f"{BASE}/{made['id']}", headers=headers).status_code == 403


def test_a_script_in_a_project_somebody_cannot_see_is_not_found(client, auth_headers):
    assert client.get(f"{BASE}/no-such-script", headers=auth_headers).status_code == 404
    assert client.post(
        BASE, headers=auth_headers, json={"project_id": "no-such-project"}
    ).status_code == 404
