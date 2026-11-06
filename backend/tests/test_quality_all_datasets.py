"""Data quality opens on every check at once, not one dataset at a time.

The page used to open on whichever dataset came first, so a failing check on
any other dataset was out of sight until someone went through them one by one.
It now lists every check across every dataset, each with its latest result -
in one query for those results, however many checks there are.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import event

from app.db.session import engine
from app.models import QualityResult


def upload(client, auth_headers, name: str, project_id: str | None = None) -> str:
    frame = pd.DataFrame({"hhid": [1, 2, 3], "age": [30, None, 41]})
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        data={"project_id": project_id} if project_id else {},
        files={"file": (f"{name}.csv", frame.to_csv(index=False).encode(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return (body["datasets"][0] if "datasets" in body else body)["id"]


def age_check(client, auth_headers, dataset_id: str, name: str) -> dict:
    response = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "name": name,
            "check_type": "missing_rate",
            "threshold": 0,
            "severity": "warning",
            "config": {"variable": "age"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_every_check_is_listed_with_its_latest_result(client, auth_headers, db_session):
    first = upload(client, auth_headers, "first")
    second = upload(client, auth_headers, "second")
    one = age_check(client, auth_headers, first, "Age on first")
    two = age_check(client, auth_headers, second, "Age on second")
    # Creating a check runs it: both fail, one missing age in each.

    # The second is fixed since: a later run passed.
    db_session.add(
        QualityResult(
            rule_id=two["id"],
            run_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5),
            passed=True,
            message="All rows have an age.",
        )
    )
    db_session.commit()

    response = client.get("/api/v1/monitoring/quality-rules", headers=auth_headers)
    assert response.status_code == 200, response.text
    by_id = {rule["id"]: rule for rule in response.json()}
    assert by_id[one["id"]]["latest_result"]["passed"] is False
    assert by_id[two["id"]]["latest_result"]["passed"] is True
    assert by_id[two["id"]]["latest_result"]["message"] == "All rows have an age."

    # One dataset's, as before.
    only = client.get(
        f"/api/v1/monitoring/quality-rules?dataset_id={first}", headers=auth_headers
    ).json()
    assert [rule["id"] for rule in only] == [one["id"]]


def test_a_check_never_run_has_no_result(client, auth_headers, db_session):
    dataset = upload(client, auth_headers, "unrun")
    rule = age_check(client, auth_headers, dataset, "Never run")
    db_session.query(QualityResult).filter(QualityResult.rule_id == rule["id"]).delete()
    db_session.commit()

    listed = client.get(
        f"/api/v1/monitoring/quality-rules?dataset_id={dataset}", headers=auth_headers
    ).json()
    assert listed[0]["latest_result"] is None


def test_the_latest_results_are_one_query_however_many_checks(client, auth_headers):
    dataset = upload(client, auth_headers, "many")
    for number in range(6):
        age_check(client, auth_headers, dataset, f"Check {number}")

    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        if "quality_results" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = client.get(
            f"/api/v1/monitoring/quality-rules?dataset_id={dataset}", headers=auth_headers
        )
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert response.status_code == 200
    assert len(response.json()) == 6
    assert len(statements) == 1


def test_narrowed_to_a_project_only_its_checks_are_listed(client, auth_headers):
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Checks project"}
    ).json()
    inside = upload(client, auth_headers, "inside", project["id"])
    outside = upload(client, auth_headers, "outside")
    mine = age_check(client, auth_headers, inside, "Inside")
    other = age_check(client, auth_headers, outside, "Outside")

    listed = client.get(
        f"/api/v1/monitoring/quality-rules?project_id={project['id']}", headers=auth_headers
    ).json()
    ids = {rule["id"] for rule in listed}
    assert mine["id"] in ids
    assert other["id"] not in ids
