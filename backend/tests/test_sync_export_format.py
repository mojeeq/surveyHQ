"""Which format an import asks the Survey Solutions server for.

The format was a property of the connection, so every import took whatever it
was last set to and changing it for one pull changed it for the nightly one
too. That matters when a questionnaire's Stata export reads badly: the way out
is to ask the same server for the same interviews as tabular text, once,
without touching what the schedule does.

Survey Solutions produces Tabular (.tab), STATA (.dta) and SPSS (.sav). There
is no CSV and no .dat among them, which is why asking for one is refused here
rather than sent to a server that would reject it.
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

BASE = "https://survey.example.org"


@pytest.fixture
def no_broker(monkeypatch):
    """Queue nothing. Redis is not running, and waiting for it to say so is 20s."""
    monkeypatch.setattr(
        "app.workers.tasks.run_connection_sync.delay",
        lambda job_id: SimpleNamespace(id=f"task-{job_id}"),
    )


def _connection(client, auth_headers, **overrides) -> dict:
    made = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Field server",
            "base_url": BASE,
            "workspace": "primary",
            "username": "api_user",
            "password": "secret",
            **overrides,
        },
    )
    assert made.status_code == 201, made.text
    return made.json()


def test_an_import_asks_for_the_connections_format_by_default(
    client, auth_headers, db_session, no_broker
):
    from app.models import Job

    connection = _connection(
        client, auth_headers, questionnaires=["q1$2"], export_format="Tabular"
    )
    response = client.post(
        f"/api/v1/connections/{connection['id']}/sync", headers=auth_headers, json={}
    )
    assert response.status_code == 202, response.text
    assert db_session.get(Job, response.json()["id"]).params["export_format"] == "Tabular"


def test_one_import_can_ask_for_another_format(
    client, auth_headers, db_session, no_broker
):
    """And the connection goes on doing what it did for every other import."""
    from app.models import Connection, Job

    connection = _connection(client, auth_headers, questionnaires=["q1$2"])
    response = client.post(
        f"/api/v1/connections/{connection['id']}/sync",
        headers=auth_headers,
        json={"export_format": "Tabular"},
    )
    assert response.status_code == 202, response.text
    assert db_session.get(Job, response.json()["id"]).params["export_format"] == "Tabular"
    db_session.expire_all()
    assert db_session.get(Connection, connection["id"]).export_format.value == "STATA"


def test_the_format_is_settled_when_the_import_is_asked_for(
    client, auth_headers, db_session, no_broker
):
    """Not read later from a connection somebody has edited in the meantime."""
    from app.models import Job

    connection = _connection(
        client, auth_headers, questionnaires=["q1$2"], export_format="Tabular"
    )
    response = client.post(
        f"/api/v1/connections/{connection['id']}/sync", headers=auth_headers, json={}
    )
    client.patch(
        f"/api/v1/connections/{connection['id']}",
        headers=auth_headers,
        json={"export_format": "SPSS"},
    )
    assert db_session.get(Job, response.json()["id"]).params["export_format"] == "Tabular"


def test_a_format_the_server_does_not_produce_is_refused(client, auth_headers, no_broker):
    connection = _connection(client, auth_headers, questionnaires=["q1$2"])
    for asked in ("CSV", "DAT", "csv"):
        response = client.post(
            f"/api/v1/connections/{connection['id']}/sync",
            headers=auth_headers,
            json={"export_format": asked},
        )
        assert response.status_code == 422, (asked, response.text)


def _export_zip() -> bytes:
    """A tabular export: one tab separated file per roster level."""
    frame = pd.DataFrame({"interview__key": ["a", "b"], "roof": [1, 2]})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("VN_LFS.tab", frame.to_csv(sep="\t", index=False))
    return buffer.getvalue()


@respx.mock
def test_the_chosen_format_is_what_the_server_is_asked_for(
    client, auth_headers, db_session, no_broker
):
    """The whole way through: the dialog, the job, the wire, the run."""
    from app.models.connection import SyncRun, SyncStatus
    from app.workers.tasks import run_connection_sync

    connection = _connection(client, auth_headers, export_format="STATA")
    respx.get(f"{BASE}/primary/api/v1/questionnaires").mock(
        return_value=httpx.Response(
            200,
            json={
                "Questionnaires": [
                    {"QuestionnaireId": "q1", "Version": 2, "Title": "LFS"}
                ],
                "TotalCount": 1,
            },
        )
    )
    started = respx.post(f"{BASE}/primary/api/v2/export").mock(
        return_value=httpx.Response(
            200, json={"JobId": 7, "ExportStatus": "Created", "HasExportFile": False}
        )
    )
    respx.get(f"{BASE}/primary/api/v2/export/7").mock(
        return_value=httpx.Response(
            200,
            json={
                "JobId": 7,
                "ExportStatus": "Completed",
                "HasExportFile": True,
                "Links": {"Download": f"{BASE}/primary/api/v2/export/7/file"},
            },
        )
    )
    respx.get(f"{BASE}/primary/api/v2/export/7/file").mock(
        return_value=httpx.Response(200, content=_export_zip())
    )

    queued = client.post(
        f"/api/v1/connections/{connection['id']}/sync",
        headers=auth_headers,
        json={"questionnaires": ["q1$2"], "export_format": "Tabular"},
    )
    assert queued.status_code == 202, queued.text
    run_connection_sync(queued.json()["id"])

    asked = json.loads(started.calls[0].request.content)
    assert asked["ExportType"] == "Tabular"

    db_session.expire_all()
    runs = (
        db_session.query(SyncRun).filter(SyncRun.connection_id == connection["id"]).all()
    )
    # Recorded on the run, so a history of imports says which came in as what.
    assert [(run.export_format, run.status) for run in runs] == [
        ("Tabular", SyncStatus.success)
    ]
