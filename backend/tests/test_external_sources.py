from __future__ import annotations

import pandas as pd

from app.models import Job, JobStatus, JobType
from app.services.external_sources import (
    ExternalSourceClient,
    RemoteTable,
    SourceResource,
    _sdmx_json_frame,
    _tables_from_records,
)
from app.services.external_sync import run_external_connection_sync


def _connection(client, auth_headers, **overrides) -> dict:
    payload = {
        "name": "ODK fieldwork",
        "source_type": "odk",
        "base_url": "https://central.example.org",
        "workspace": "7",
        "username": "statistics@example.org",
        "password": "secret",
        **overrides,
    }
    response = client.post("/api/v1/connections", headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_connection_records_source_type_and_never_returns_secret(client, auth_headers):
    connection = _connection(client, auth_headers)
    assert connection["source_type"] == "odk"
    assert connection["source_config"] == {}
    assert connection["workspace"] == "7"
    assert connection["has_password"] is True
    assert "password" not in connection


def test_kobo_connection_accepts_a_token_without_a_username(client, auth_headers):
    connection = _connection(
        client,
        auth_headers,
        name="Kobo",
        source_type="kobo",
        base_url="https://kf.kobotoolbox.org",
        workspace="",
        username="",
        password="token-123",
    )
    assert connection["source_type"] == "kobo"
    assert connection["username"] == ""
    assert connection["has_password"] is True


def test_public_sdmx_connection_needs_no_credentials(client, auth_headers, monkeypatch):
    def fake_test(self):
        return {"ok": True, "source": "SDMX API", "resource_count": 2, "workspace": ""}

    monkeypatch.setattr(ExternalSourceClient, "test_connection", fake_test)
    connection = _connection(
        client,
        auth_headers,
        name="Official statistics",
        source_type="sdmx",
        base_url="https://stats.example.org/rest",
        workspace="",
        username="",
        password="",
        source_config={"resources": ["data/POP/.FJ...."]},
        questionnaires=["data/POP/.FJ...."],
    )
    tested = client.post(
        f"/api/v1/connections/{connection['id']}/test", headers=auth_headers
    )
    assert tested.status_code == 200
    assert tested.json()["ok"] is True
    assert "SDMX" in tested.json()["message"]


def test_generic_resource_discovery_uses_the_connection_adapter(
    client, auth_headers, monkeypatch
):
    connection = _connection(client, auth_headers)

    def fake_resources(self):
        return [
            SourceResource(
                id="hh-form",
                identity="hh-form",
                title="Household questionnaire",
                kind="form",
            )
        ]

    monkeypatch.setattr(ExternalSourceClient, "list_resources", fake_resources)
    response = client.get(
        f"/api/v1/connections/{connection['id']}/resources", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": "hh-form",
            "version": 0,
            "title": "Household questionnaire",
            "variable": "",
            "identity": "hh-form",
            "last_entry_date": None,
            "kind": "form",
            "meta": {},
        }
    ]


def test_nested_repeat_records_become_separate_linkable_tables():
    tables = _tables_from_records(
        [
            {
                "_id": 10,
                "district": "Central",
                "members": [
                    {"name": "Ana", "age": 34},
                    {"name": "Ben", "age": 7},
                ],
            }
        ],
        root_name="Household",
        source_ref="odk:1:hh",
    )
    assert [table.name for table in tables] == ["Household", "Household - members"]
    assert len(tables[0].frame) == 1
    assert len(tables[1].frame) == 2
    assert tables[1].frame["_surveyhq_parent_id"].tolist() == ["10", "10"]


def test_compact_sdmx_json_keeps_dimension_codes_labels_and_values():
    payload = {
        "dataSets": [
            {
                "series": {
                    "0:0": {
                        "observations": {
                            "0": [551832],
                            "1": [558000],
                        }
                    }
                }
            }
        ],
        "structure": {
            "dimensions": {
                "series": [
                    {
                        "id": "REF_AREA",
                        "values": [{"id": "FJ", "name": "Fiji"}],
                    },
                    {
                        "id": "INDICATOR",
                        "values": [{"id": "POP", "name": "Population"}],
                    },
                ],
                "observation": [
                    {
                        "id": "TIME_PERIOD",
                        "values": [{"id": "2017"}, {"id": "2022"}],
                    }
                ],
            }
        },
    }
    frame = _sdmx_json_frame(payload)
    assert frame["REF_AREA"].tolist() == ["FJ", "FJ"]
    assert frame["REF_AREA__label"].tolist() == ["Fiji", "Fiji"]
    assert frame["TIME_PERIOD"].tolist() == ["2017", "2022"]
    assert frame["OBS_VALUE"].tolist() == [551832, 558000]


def test_external_sync_creates_roster_datasets_and_refreshes_them_in_place(
    client, auth_headers, db_session, monkeypatch
):
    connection = _connection(
        client,
        auth_headers,
        questionnaires=["hh-form"],
    )

    def fake_resources(self):
        return [SourceResource(id="hh-form", identity="hh-form", title="Household")]

    frames = [
        pd.DataFrame({"id": [1, 2], "district": ["A", "B"]}),
        pd.DataFrame({"parent_id": [1, 1, 2], "age": [42, 12, 29]}),
    ]

    def fake_pull(self, resource_id):
        assert resource_id == "hh-form"
        return [
            RemoteTable("Household", "odk:7:hh-form:Submissions", frames[0]),
            RemoteTable("Household - members", "odk:7:hh-form:members", frames[1]),
        ]

    monkeypatch.setattr(ExternalSourceClient, "list_resources", fake_resources)
    monkeypatch.setattr(ExternalSourceClient, "pull", fake_pull)

    job = Job(
        job_type=JobType.sync,
        status=JobStatus.queued,
        title="ODK import",
        params={
            "connection_id": connection["id"],
            "questionnaires": ["hh-form"],
            "mode": "replace",
        },
    )
    db_session.add(job)
    db_session.commit()
    first = run_external_connection_sync(job.id)
    assert first["errors"] == []
    assert len(first["datasets"]) == 2

    datasets = client.get("/api/v1/datasets?limit=200", headers=auth_headers).json()["items"]
    ours = [row for row in datasets if row.get("connection_id") == connection["id"]]
    assert {row["source"] for row in ours} == {"odk"}
    assert {row["row_count"] for row in ours} == {2, 3}
    ids = {row["source_ref"]: row["id"] for row in ours}

    frames[0] = pd.DataFrame({"id": [1, 2, 3], "district": ["A", "B", "C"]})
    second_job = Job(
        job_type=JobType.sync,
        status=JobStatus.queued,
        title="ODK refresh",
        params={
            "connection_id": connection["id"],
            "questionnaires": ["hh-form"],
            "mode": "replace",
        },
    )
    db_session.add(second_job)
    db_session.commit()
    second = run_external_connection_sync(second_job.id)
    assert second["errors"] == []

    refreshed = client.get("/api/v1/datasets?limit=200", headers=auth_headers).json()["items"]
    refreshed_ours = [row for row in refreshed if row.get("connection_id") == connection["id"]]
    assert {row["source_ref"]: row["id"] for row in refreshed_ours} == ids
    household = next(row for row in refreshed_ours if row["source_ref"].endswith("Submissions"))
    assert household["row_count"] == 3
