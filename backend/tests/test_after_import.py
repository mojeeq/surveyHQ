"""What follows new data in: merges, then scripts, then the dashboards.

The complaint this answers: a Survey Solutions sync brought in a newer export,
the datasets it replaced moved, and the merged datasets built on them did not
- nor did the dashboards reading those merges. Nothing anywhere said so.

Three faults were behind that, and each is pinned here. The paths data
arrives on each carried their own copy of what follows it, and the sync's
copy ran no scripts. An append changed nothing downstream at all. And a merge
held only the id of the relationship it was made from, so clearing and
detecting relationships again left it with no recipe, passed over in silence
by every import after.
"""

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
import respx
from sqlalchemy import select

from app.models import Dataset, DatasetRelationship, Job
from tests.test_api_analytics import _stata_bytes, _zip_bytes

HOUSEHOLDS = pd.DataFrame({"hhid": [1.0, 2.0], "province": ["Northern", "Highland"]})
PEOPLE = pd.DataFrame({"hhid": [1.0, 1.0, 2.0], "age": [40.0, 9.0, 33.0]})
MORE_PEOPLE = pd.DataFrame({"hhid": [2.0, 1.0], "age": [70.0, 20.0]})


@pytest.fixture
def project(client, auth_headers, request) -> dict:
    made = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": f"A {request.node.name[:40]}"},
    ).json()
    upload(client, auth_headers, made["id"], PEOPLE)
    return made


def upload(
    client,
    auth_headers,
    project_id: str,
    people: pd.DataFrame,
    mode: str = "replace",
    households: bool = True,
):
    files = {"people.dta": _stata_bytes(people)}
    if households:
        files["households.dta"] = _stata_bytes(HOUSEHOLDS)
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", _zip_bytes(files), "application/zip")},
        data={"project_id": project_id, "mode": mode},
    )
    assert response.status_code == 201, response.text
    return response.json()


def named(db_session, project_id: str, name: str) -> Dataset:
    db_session.expire_all()
    return db_session.scalars(
        select(Dataset).where(Dataset.project_id == project_id, Dataset.name == name)
    ).one()


def merge(client, auth_headers, db_session, project_id: str) -> Dataset:
    """People joined to their households, the way the Relationships view does it."""
    people = named(db_session, project_id, "people")
    households = named(db_session, project_id, "households")
    link = client.post(
        "/api/v1/relationships",
        headers=auth_headers,
        json={
            "left_dataset_id": people.id,
            "right_dataset_id": households.id,
            "left_variable": "hhid",
            "right_variable": "hhid",
            "cardinality": "many_to_one",
        },
    )
    assert link.status_code == 201, link.text
    made = client.post(
        "/api/v1/relationships/merge",
        headers=auth_headers,
        json={"name": "People + Households", "relationship_id": link.json()["id"]},
    )
    assert made.status_code == 201, made.text
    return named(db_session, project_id, "People + Households")


def test_a_replacement_rebuilds_the_merge_and_says_so(client, auth_headers, db_session, project):
    merged = merge(client, auth_headers, db_session, project["id"])
    assert merged.row_count == 3

    body = upload(client, auth_headers, project["id"], MORE_PEOPLE)

    assert named(db_session, project["id"], "People + Households").row_count == 2
    assert "Rebuilt from the new data: People + Households" in body["warnings"]
    stages = {stage["key"]: stage for stage in body["stages"]}
    assert list(stages) == ["commands", "merges", "scripts", "refresh", "publish"]
    assert stages["merges"]["detail"] == "1 rebuilt"


def test_an_append_rebuilds_the_merge_too(client, auth_headers, db_session, project):
    """An incremental export changes a join as surely as a replacement does,
    and used to reach no merge at all."""
    merge(client, auth_headers, db_session, project["id"])
    # Only what is new, as an incremental export has it.
    upload(client, auth_headers, project["id"], MORE_PEOPLE, mode="append", households=False)
    assert named(db_session, project["id"], "people").row_count == 5
    assert named(db_session, project["id"], "People + Households").row_count == 5


def test_a_merge_outlives_the_relationship_it_was_made_from(
    client, auth_headers, db_session, project
):
    """Clearing relationships to detect them again is an ordinary thing to do,
    and it used to leave every merge built on them with no recipe."""
    merge(client, auth_headers, db_session, project["id"])
    cleared = client.post(
        f"/api/v1/relationships/clear?project_id={project['id']}", headers=auth_headers
    )
    assert cleared.status_code == 200, cleared.text

    body = upload(client, auth_headers, project["id"], MORE_PEOPLE)

    assert named(db_session, project["id"], "People + Households").row_count == 2
    assert "Rebuilt from the new data: People + Households" in body["warnings"]


def _as_made_before_recipes(db_session, merged: Dataset) -> None:
    """What a merge made before this change carries: the relationship's id."""
    derivation = dict(merged.derivation)
    for key in list(derivation):
        if key not in ("type", "relationship_id", "how", "columns", "prefix"):
            derivation.pop(key)
    merged.derivation = derivation
    for one in db_session.scalars(select(DatasetRelationship)).all():
        db_session.delete(one)
    db_session.commit()


def test_an_older_merge_finds_its_relationship_again_by_the_names_it_was_made_from(
    client, auth_headers, db_session, project
):
    """The case on the screen that started this: relationships detected again,
    with new ids, and a merge still pointing at the old one."""
    merged = merge(client, auth_headers, db_session, project["id"])
    _as_made_before_recipes(db_session, merged)
    people = named(db_session, project["id"], "people")
    households = named(db_session, project["id"], "households")
    again = client.post(
        "/api/v1/relationships",
        headers=auth_headers,
        json={
            "left_dataset_id": households.id,
            "right_dataset_id": people.id,
            "left_variable": "hhid",
            "right_variable": "hhid",
            "cardinality": "one_to_many",
        },
    )
    assert again.status_code == 201, again.text

    upload(client, auth_headers, project["id"], MORE_PEOPLE)

    merged = named(db_session, project["id"], "People + Households")
    assert merged.row_count == 2, "drawn the other way round, the merge keeps its own sides"
    assert merged.derivation["relationship_id"] == again.json()["id"]
    assert merged.derivation["left_dataset_id"] == people.id, "the recipe is kept from now on"


def test_a_merge_that_cannot_be_rebuilt_says_why_on_the_import_and_on_itself(
    client, auth_headers, db_session, project
):
    merged = merge(client, auth_headers, db_session, project["id"])
    _as_made_before_recipes(db_session, merged)

    body = upload(client, auth_headers, project["id"], MORE_PEOPLE)

    said = [w for w in body["warnings"] if w.startswith("'People + Households' was not rebuilt")]
    assert said and "There is no relationship between them now" in said[0], body["warnings"]
    stages = {stage["key"]: stage for stage in body["stages"]}
    assert stages["merges"]["status"] == "warning"
    assert stages["merges"]["items"][0]["status"] == "stuck"

    card = client.get(f"/api/v1/datasets/{merged.id}", headers=auth_headers).json()
    assert card["meta"]["rebuild"]["status"] == "stuck"
    assert named(db_session, project["id"], "People + Households").row_count == 3, (
        "it keeps the data it had rather than being emptied"
    )

    # And the Rebuild button says the same thing rather than a bare 409.
    rebuilt = client.post(f"/api/v1/relationships/rebuild/{merged.id}", headers=auth_headers)
    assert rebuilt.status_code == 409
    assert "no relationship between them" in rebuilt.json()["detail"]


def test_a_script_that_was_only_ever_run_is_named_rather_than_skipped_silently(
    client, auth_headers, db_session, project
):
    ran = client.post(
        f"/api/v1/projects/{project['id']}/script/run",
        headers=auth_headers,
        json={"text": "use people\nkeep if age >= 18\nsave as adults"},
    )
    assert ran.status_code == 200, ran.text
    # A clean run keeps its script now; this is the state one left before
    # that, which databases still hold.
    from app.models import ProjectScript

    db_session.expire_all()
    row = db_session.scalars(
        select(ProjectScript).where(ProjectScript.project_id == project["id"])
    ).one()
    row.text = ""
    db_session.commit()

    body = upload(client, auth_headers, project["id"], MORE_PEOPLE)

    assert any("was never saved, so it was not re-run" in w for w in body["warnings"])
    scripts = {stage["key"]: stage for stage in body["stages"]}["scripts"]
    assert scripts["status"] == "warning"
    assert scripts["items"][0]["status"] == "not saved"


# --- a Survey Solutions sync, the path from the report -------------------------

BASE = "https://survey.example.org"


def _export(people: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("households.tab", HOUSEHOLDS.to_csv(sep="\t", index=False))
        bundle.writestr("people.tab", people.to_csv(sep="\t", index=False))
    return buffer.getvalue()


def _server(people: pd.DataFrame) -> None:
    respx.get(f"{BASE}/primary/api/v1/questionnaires").mock(
        return_value=httpx.Response(
            200,
            json={
                "Questionnaires": [{"QuestionnaireId": "q1", "Version": 1, "Title": "Census"}],
                "TotalCount": 1,
            },
        )
    )
    respx.post(f"{BASE}/primary/api/v2/export").mock(
        return_value=httpx.Response(200, json={"JobId": 7, "ExportStatus": "Created"})
    )
    respx.get(f"{BASE}/primary/api/v2/export/7").mock(
        return_value=httpx.Response(
            200,
            json={
                "JobId": 7,
                "ExportStatus": "Completed",
                "HasExportFile": True,
                "Progress": 100,
                "Links": {"Download": f"{BASE}/primary/api/v2/export/7/file"},
            },
        )
    )
    respx.get(f"{BASE}/primary/api/v2/export/7/file").mock(
        return_value=httpx.Response(200, content=_export(people))
    )


@respx.mock
def test_a_sync_rebuilds_the_merges_then_runs_the_scripts_and_shows_each_step(
    client, auth_headers, db_session, monkeypatch, request
):
    from app.workers.tasks import run_connection_sync

    monkeypatch.setattr(
        "app.workers.tasks.run_connection_sync.delay",
        lambda job_id: SimpleNamespace(id=f"task-{job_id}"),
    )
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": f"S {request.node.name[:40]}"}
    ).json()
    connection = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Field server",
            "base_url": BASE,
            "workspace": "primary",
            "username": "api_user",
            "password": "secret",
            "project_id": project["id"],
            "export_format": "Tabular",
        },
    ).json()

    def sync(people: pd.DataFrame) -> Job:
        _server(people)
        queued = client.post(
            f"/api/v1/connections/{connection['id']}/sync",
            headers=auth_headers,
            json={"questionnaires": ["q1$1"]},
        )
        assert queued.status_code == 202, queued.text
        run_connection_sync(queued.json()["id"])
        db_session.expire_all()
        return db_session.get(Job, queued.json()["id"])

    sync(PEOPLE)
    merge(client, auth_headers, db_session, project["id"])
    script = "use people\nkeep if age >= 18\nsave as adults"
    assert client.put(
        f"/api/v1/projects/{project['id']}/script", headers=auth_headers, json={"text": script}
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/{project['id']}/script/run", headers=auth_headers, json={}
    ).status_code == 200
    assert named(db_session, project["id"], "adults").row_count == 2

    job = sync(MORE_PEOPLE)

    assert named(db_session, project["id"], "People + Households").row_count == 2
    assert named(db_session, project["id"], "adults").row_count == 2
    assert sorted(pd.read_parquet(named(db_session, project["id"], "adults").storage_path)["age"]) == [
        20.0,
        70.0,
    ], "the script ran over the new export, not the old one"

    stages = {stage["key"]: stage for stage in job.stages}
    assert list(stages) == ["download", "commands", "merges", "scripts", "refresh", "publish"]
    assert all(stage["status"] in ("done", "skipped") for stage in job.stages), json.dumps(
        job.stages, indent=1
    )
    assert stages["merges"]["detail"] == "1 rebuilt"
    assert stages["scripts"]["items"][0]["status"] == "ran"
    assert job.progress == 100.0


def test_a_board_says_how_old_its_data_is_and_when_it_next_moves(
    client, auth_headers, db_session, project
):
    """Through the merge to the connection feeding its source: the merged
    dataset has no connection of its own, and is what the board shows."""
    import datetime as dt

    from app.models import Connection

    merged = merge(client, auth_headers, db_session, project["id"])
    people = named(db_session, project["id"], "people")
    feed = Connection(
        name="Field server",
        base_url=BASE,
        username="u",
        password_encrypted="",
        project_id=project["id"],
        sync_enabled=True,
        sync_interval_minutes=60,
        last_sync_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=15),
    )
    db_session.add(feed)
    db_session.flush()
    people.connection_id = feed.id
    db_session.commit()

    board = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": "Fresh", "project_id": project["id"]},
    ).json()
    tile = client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "Freshness", "widget_type": "freshness", "dataset_id": merged.id},
    )
    assert tile.status_code == 201, tile.text

    data = client.post(f"/api/v1/dashboards/{board['id']}/data", headers=auth_headers, json={})
    assert data.status_code == 200, data.text
    fresh = data.json()["freshness"]
    assert fresh["imported_at"] is not None
    due = dt.datetime.fromisoformat(fresh["next_import_at"])
    assert dt.timedelta(minutes=40) < due - dt.datetime.now(dt.UTC) < dt.timedelta(minutes=50)


def test_a_merge_is_written_without_passing_through_a_frame(
    client, auth_headers, db_session, project, monkeypatch
):
    """The joined table never sits in the worker's memory: at census scale
    that was where the worker was killed, and the import with it."""
    import app.services.query_engine as engine

    def refuse(sql):
        raise AssertionError("a merge built a frame")

    monkeypatch.setattr(engine, "run_frame", refuse)
    monkeypatch.setattr("app.services.relationships.run_frame", refuse)
    merged = merge(client, auth_headers, db_session, project["id"])
    assert merged.row_count == 3

    upload(client, auth_headers, project["id"], MORE_PEOPLE)
    merged = named(db_session, project["id"], "People + Households")
    assert merged.row_count == 2
    data = pd.read_parquet(merged.storage_path)
    assert sorted(data["province"]) == ["Highland", "Northern"]
    assert {v.name for v in merged.variables} >= {"hhid", "age", "province"}


def test_the_project_reads_as_its_pipeline_with_what_needs_attention_on_top(
    client, auth_headers, db_session, project
):
    """In, joined, prepared, shown, watched - and the two things on the way
    that would otherwise go unnoticed gathered first."""
    from app.models import ProjectScript

    merged = merge(client, auth_headers, db_session, project["id"])
    _as_made_before_recipes(db_session, merged)
    ran = client.post(
        f"/api/v1/projects/{project['id']}/script/run",
        headers=auth_headers,
        json={"text": "use people\nkeep if age >= 18\nsave as adults"},
    )
    assert ran.status_code == 200, ran.text
    db_session.expire_all()
    row = db_session.scalars(
        select(ProjectScript).where(ProjectScript.project_id == project["id"])
    ).one()
    row.text = ""  # the state a run left before a clean run kept its script
    db_session.commit()
    upload(client, auth_headers, project["id"], MORE_PEOPLE)

    seen = client.get(f"/api/v1/projects/{project['id']}/overview", headers=auth_headers)
    assert seen.status_code == 200, seen.text
    body = seen.json()

    assert {one["name"] for one in body["sources"]} == {"people", "households"}
    assert [one["name"] for one in body["outputs"]] == ["adults"]
    [joined] = body["merges"]
    assert joined["status"] == "stuck" and joined["message"]
    [script] = body["scripts"]
    assert not script["saved"] and script["runs_on_import"] is False
    kinds = [one["kind"] for one in body["attention"]]
    assert "merge" in kinds and "script" in kinds


def test_a_project_somebody_cannot_see_has_no_overview(client, auth_headers):
    missing = client.get("/api/v1/projects/not-a-project/overview", headers=auth_headers)
    assert missing.status_code == 404
