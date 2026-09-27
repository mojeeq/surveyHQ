"""The project's script as a recipe, not a one-off.

A survey is exported again every night and a dataset the script read is
replaced underneath it. What the script built then holds last week's join and
nothing on a dashboard says so - which is the same bug merged datasets had
before they learned to rebuild, and it is worth as much to close here.

What decides whether a script re-runs is what its last run actually read,
recorded as it read it. A script nobody has run reads nothing and stays where
it is: running somebody's draft for the first time in the middle of their
nightly import is not a thing to do unasked.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import select

from app.models import Dataset, ProjectScript
from tests.test_api_analytics import _stata_bytes, _zip_bytes

FIRST = pd.DataFrame(
    {"hhid": [1.0, 2.0, 3.0], "province": ["Shefa", "Sanma", "Tafea"], "wage": [10.0, 20.0, 30.0]}
)
# The same export, run again, with a fourth household and a changed wage.
SECOND = pd.DataFrame(
    {
        "hhid": [1.0, 2.0, 3.0, 4.0],
        "province": ["Shefa", "Sanma", "Tafea", "Torba"],
        "wage": [10.0, 20.0, 30.0, 40.0],
    }
)

SCRIPT = "use households\ncollapse (sum) wage, by(province)\nsave as totals"


def archive(frame: pd.DataFrame) -> bytes:
    return _zip_bytes({"households.dta": _stata_bytes(frame)})


@pytest.fixture
def project(client, auth_headers, request) -> dict:
    made = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": f"P {request.node.name[:34]}"},
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", archive(FIRST), "application/zip")},
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    return {"id": made["id"]}


def put_script(client, auth_headers, project, text=SCRIPT):
    response = client.put(
        f"/api/v1/projects/{project['id']}/script",
        headers=auth_headers,
        json={"text": text},
    )
    assert response.status_code == 200, response.text
    return response.json()


def run_script(client, auth_headers, project, text=None):
    return client.post(
        f"/api/v1/projects/{project['id']}/script/run",
        headers=auth_headers,
        json={"text": text},
    )


def upload_again(client, auth_headers, project, frame=SECOND):
    """The same archive again, which replaces the datasets it matches."""
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", archive(frame), "application/zip")},
        data={"project_id": project["id"], "mode": "replace"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def totals(db_session, project) -> pd.DataFrame:
    found = (
        db_session.execute(
            select(Dataset).where(
                Dataset.project_id == project["id"], Dataset.name == "totals"
            )
        )
        .scalars()
        .first()
    )
    assert found is not None, "the script never built 'totals'"
    return pd.read_parquet(found.storage_path)


# --- keeping and running ----------------------------------------------------


def test_a_script_is_kept_without_being_run(client, auth_headers, project, db_session):
    """Half-written at the end of the day should survive being closed."""
    put_script(client, auth_headers, project, "use households\n* more tomorrow")
    read = client.get(
        f"/api/v1/projects/{project['id']}/script", headers=auth_headers
    ).json()
    assert read["text"] == "use households\n* more tomorrow"
    assert read["last_run_at"] is None


def test_running_reports_each_line_and_what_it_saved(client, auth_headers, project):
    put_script(client, auth_headers, project)
    body = run_script(client, auth_headers, project).json()
    assert [step["command"] for step in body["log"]] == [
        "use households",
        "collapse (sum) wage, by(province)",
        "save as totals",
    ]
    assert [entry["name"] for entry in body["saved"]] == ["totals"]
    assert body["saved"][0]["created"] is True


def test_a_failing_line_says_which_and_keeps_what_ran(client, auth_headers, project):
    put_script(
        client,
        auth_headers,
        project,
        "use households\nsave as copy\ngen x = nosuchthing\nsave as never",
    )
    failed = run_script(client, auth_headers, project)
    assert failed.status_code == 422
    assert "Line 3" in failed.json()["detail"]
    assert failed.headers.get("X-Script-Line") == "3"

    # What ran, ran: line 2 saved and stays saved.
    listed = client.get(
        f"/api/v1/datasets?project_id={project['id']}", headers=auth_headers
    ).json()
    names = {row["name"] for row in listed["items"]}
    assert "copy" in names
    assert "never" not in names


def test_running_something_other_than_what_is_stored(client, auth_headers, project):
    """The editor tries a script before it is kept."""
    put_script(client, auth_headers, project, "* nothing yet")
    body = run_script(client, auth_headers, project, text=SCRIPT).json()
    assert [entry["name"] for entry in body["saved"]] == ["totals"]
    kept = client.get(
        f"/api/v1/projects/{project['id']}/script", headers=auth_headers
    ).json()
    assert kept["text"] == "* nothing yet"


def test_what_the_last_run_touched_is_reported_by_name(client, auth_headers, project):
    put_script(client, auth_headers, project)
    run_script(client, auth_headers, project)
    read = client.get(
        f"/api/v1/projects/{project['id']}/script", headers=auth_headers
    ).json()
    assert read["reads"] == ["households"]
    assert read["writes"] == ["totals"]
    assert read["last_error"] == ""


# --- what a script may write over -------------------------------------------


def test_running_the_same_script_twice_rebuilds_what_it_built(
    client, auth_headers, project, db_session
):
    """A recipe run twice rebuilds its own output rather than refusing.

    Without this the feature could only ever be used once: the second run
    stops at `save as totals` because the first run made a 'totals'.
    """
    put_script(client, auth_headers, project)
    run_script(client, auth_headers, project)
    second = run_script(client, auth_headers, project)
    assert second.status_code == 200, second.text
    assert second.json()["saved"][0]["created"] is False

    db_session.expire_all()
    built = db_session.execute(
        select(Dataset).where(
            Dataset.project_id == project["id"], Dataset.name == "totals"
        )
    ).scalars().all()
    assert len(built) == 1, "the second run made a second dataset"


def test_a_dataset_the_script_did_not_build_is_not_taken_over(
    client, auth_headers, project
):
    """Rebuilding its own output is one thing; adopting somebody else's is not."""
    put_script(client, auth_headers, project, "use households\nsave as households")
    refused = run_script(client, auth_headers, project)
    assert refused.status_code == 422
    assert "was not built by this script" in refused.json()["detail"]


def test_replace_takes_it_over_when_the_line_says_so(client, auth_headers, project):
    put_script(
        client,
        auth_headers,
        project,
        "use households\ncollapse (sum) wage, by(province)\nsave as households, replace",
    )
    taken = run_script(client, auth_headers, project)
    assert taken.status_code == 200, taken.text
    assert taken.json()["saved"][0]["created"] is False


# --- re-running when the data changes ---------------------------------------


def test_a_newer_export_re_runs_the_script_that_read_it(
    client, auth_headers, project, db_session
):
    """The bug this closes: 'totals' holding last week's numbers, silently."""
    put_script(client, auth_headers, project)
    run_script(client, auth_headers, project)
    db_session.expire_all()
    assert sorted(totals(db_session, project)["province"]) == ["Sanma", "Shefa", "Tafea"]

    upload_again(client, auth_headers, project)
    db_session.expire_all()

    after = totals(db_session, project)
    assert sorted(after["province"]) == ["Sanma", "Shefa", "Tafea", "Torba"]
    assert after[after["province"] == "Torba"]["wage"].tolist() == [40.0]


def test_the_upload_says_what_the_script_rebuilt(client, auth_headers, project):
    put_script(client, auth_headers, project)
    run_script(client, auth_headers, project)
    body = upload_again(client, auth_headers, project)
    assert any(
        "Rebuilt by the project's script" in warning and "totals" in warning
        for warning in body.get("warnings", [])
    ), body.get("warnings")


def test_a_script_nobody_has_run_is_left_alone(
    client, auth_headers, project, db_session
):
    """A draft is not run for the first time inside somebody's nightly import."""
    put_script(client, auth_headers, project)
    upload_again(client, auth_headers, project)
    db_session.expire_all()
    built = (
        db_session.execute(
            select(Dataset).where(
                Dataset.project_id == project["id"], Dataset.name == "totals"
            )
        )
        .scalars()
        .first()
    )
    assert built is None


def test_a_script_that_reads_something_else_is_not_re_run(
    client, auth_headers, project, db_session
):
    """Only the scripts standing on what was replaced."""
    other = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Elsewhere"}
    ).json()
    client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("other.zip", _zip_bytes({"other.dta": _stata_bytes(FIRST)}), "application/zip")},
        data={"project_id": other["id"]},
    )
    client.put(
        f"/api/v1/projects/{other['id']}/script",
        headers=auth_headers,
        json={"text": "use other\ncollapse (sum) wage, by(province)\nsave as elsewhere"},
    )
    client.post(
        f"/api/v1/projects/{other['id']}/script/run", headers=auth_headers, json={}
    )
    db_session.expire_all()
    before = (
        db_session.execute(
            select(Dataset).where(Dataset.name == "elsewhere")
        )
        .scalars()
        .first()
    )
    stamp = before.updated_at

    put_script(client, auth_headers, project)
    run_script(client, auth_headers, project)
    upload_again(client, auth_headers, project)
    db_session.expire_all()

    after = db_session.execute(
        select(Dataset).where(Dataset.name == "elsewhere")
    ).scalars().first()
    assert after.updated_at == stamp, "the other project's script ran too"


def test_a_re_run_that_fails_is_a_note_rather_than_a_failed_upload(
    client, auth_headers, project, db_session
):
    """The import has already happened. A script that no longer applies is a
    note beside the data, not a 500 on somebody's upload."""
    put_script(
        client,
        auth_headers,
        project,
        "use households\nkeep hhid province wage\ncollapse (sum) wage, by(province)\nsave as totals",
    )
    run_script(client, auth_headers, project)

    # The new export does not have `wage` at all, so the script cannot run.
    thinner = pd.DataFrame({"hhid": [1.0, 2.0], "province": ["Shefa", "Sanma"]})
    body = upload_again(client, auth_headers, project, thinner)

    assert any(
        "could not be re-run" in warning for warning in body.get("warnings", [])
    ), body.get("warnings")

    db_session.expire_all()
    script = db_session.scalars(
        select(ProjectScript).where(ProjectScript.project_id == project["id"])
    ).first()
    assert script.last_error, "the failure was not recorded against the script"


def test_the_script_runs_after_the_merges_it_stands_on(
    client, auth_headers, project, db_session
):
    """A script reading a merged dataset must not build on last week's join."""
    # Nothing here builds a merge, so this pins the ordering rather than the
    # arithmetic: the re-run is handed the ids the rebuild returned as well as
    # the ones that were replaced.
    import inspect

    from app.api.v1.endpoints import datasets as endpoint

    source = inspect.getsource(endpoint.upload_dataset)
    rebuild_at = source.index("rebuild_dependents(db, replaced)")
    rerun_at = source.index("project_script.rerun_for(")
    assert rebuild_at < rerun_at, "the script re-runs before the merges rebuild"
    assert "replaced + rebuilt" in source, (
        "the re-run is not told about the datasets the rebuild changed"
    )
