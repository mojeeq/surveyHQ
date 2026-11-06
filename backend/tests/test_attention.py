"""What the overview lists under "Needs attention", and the counts beside it.

The overview said "Failing checks: 4" above a box reading "Nothing is
flagged right now", because the box listed alerts and nothing else. It now
lists what has gone wrong and is still wrong - failing checks, failed imports,
scripts that stopped, merges not rebuilt - each as it stands, so something
fixed since drops off by itself.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from app.models import Connection, ProjectScript, QualityResult, SyncStatus


@pytest.fixture
def dataset_id(client, auth_headers) -> str:
    frame = pd.DataFrame({"hhid": [1, 2, 3, 4], "age": [30, None, None, 41]})
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("people.csv", frame.to_csv(index=False).encode(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return (body["datasets"][0] if "datasets" in body else body)["id"]


def missing_age_rule(client, auth_headers, dataset_id: str) -> dict:
    response = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "name": "Age recorded",
            "check_type": "missing_rate",
            "threshold": 0,
            "severity": "critical",
            "config": {"variable": "age"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def attention(client, auth_headers) -> list[dict]:
    response = client.get("/api/v1/monitoring/attention", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


def failing_count(client, auth_headers) -> int:
    return client.get("/api/v1/monitoring/summary", headers=auth_headers).json()[
        "failing_quality_checks"
    ]


def test_a_failing_check_is_listed_and_counted(client, auth_headers, dataset_id):
    rule = missing_age_rule(client, auth_headers, dataset_id)
    client.post(f"/api/v1/monitoring/quality-rules/{rule['id']}/run", headers=auth_headers)

    items = attention(client, auth_headers)
    check = next(item for item in items if item["link"] == f"/quality?dataset={dataset_id}")
    assert check["title"] == "Data quality: Age recorded"
    assert check["severity"] == "critical"
    assert failing_count(client, auth_headers) >= 1


def test_a_check_whose_latest_run_passed_is_neither_listed_nor_counted(
    client, auth_headers, dataset_id, db_session
):
    rule = missing_age_rule(client, auth_headers, dataset_id)
    client.post(f"/api/v1/monitoring/quality-rules/{rule['id']}/run", headers=auth_headers)
    mine = f"/quality?dataset={dataset_id}"
    assert any(item["link"] == mine for item in attention(client, auth_headers))
    before = failing_count(client, auth_headers)

    # Fixed since: a later run passed.
    db_session.add(
        QualityResult(
            rule_id=rule["id"],
            run_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5),
            passed=True,
            message="All rows have an age.",
        )
    )
    db_session.commit()

    assert not any(item["link"] == mine for item in attention(client, auth_headers))
    # The count used to be any check with a failure among recent results.
    assert failing_count(client, auth_headers) == before - 1


def test_a_failed_import_and_a_stopped_script_are_listed(client, auth_headers, db_session):
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Attention project"}
    ).json()
    db_session.add(
        Connection(
            name="Field server",
            base_url="https://hq.example.org",
            project_id=project["id"],
            last_sync_status=SyncStatus.failed,
            last_sync_error="401 Unauthorized",
        )
    )
    db_session.add(
        ProjectScript(
            project_id=project["id"],
            name="Clean",
            text="use people",
            last_error="Line 1 (use people): This project has no dataset called 'people'",
        )
    )
    db_session.commit()

    items = attention(client, auth_headers)
    failed = next(item for item in items if item["kind"] == "import")
    assert failed["title"] == "Import from Field server failed"
    assert failed["detail"] == "401 Unauthorized"
    stopped = next(item for item in items if item["kind"] == "script")
    assert "Clean" in stopped["title"]
    # The worst first.
    assert items.index(failed) < items.index(stopped)

    # Narrowed to another project, neither is there.
    other = client.post("/api/v1/projects", headers=auth_headers, json={"name": "Elsewhere"}).json()
    scoped = client.get(
        f"/api/v1/monitoring/attention?project_id={other['id']}", headers=auth_headers
    ).json()
    assert not any(item["kind"] in ("import", "script") for item in scoped)


def test_an_indicator_with_no_threshold_is_not_judged(client, auth_headers, dataset_id):
    made = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={"name": "People", "dataset_id": dataset_id, "spec": {"agg": "count"}},
    )
    assert made.status_code == 201, made.text
    values = client.get("/api/v1/monitoring/indicators/values", headers=auth_headers).json()
    people = next(value for value in values if value["name"] == "People")
    assert people["judged"] is False
    # And not counted as on track on the overview, where it used to be.
    summary = client.get("/api/v1/monitoring/summary", headers=auth_headers).json()
    judged_ok = sum(1 for value in values if value["judged"] and value["status"] == "ok")
    assert summary["indicators_ok"] == judged_ok
