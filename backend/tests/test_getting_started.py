"""The getting-started list on the Overview of a new install.

An install nobody has set up showed noughts in every box and nothing saying
where to begin. The list says what to do first and ticks each step once the
thing it asks for exists, so a workspace set up before the list existed reads
as done and never shows it.
"""

from __future__ import annotations

import uuid

import pandas as pd

from tests.conftest import sign_in

KEYS = ["project", "data", "quality", "indicator", "dashboard", "team"]


def person(client, auth_headers, role: str, *, restricted: bool = False) -> dict[str, str]:
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    password = "getting-started-123"
    made = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": email,
            "full_name": f"A {role}",
            "role": role,
            "password": password,
            "restricted_to_projects": restricted,
        },
    )
    assert made.status_code == 201, made.text
    return sign_in(client, email, password)


def steps(client, headers) -> list[dict]:
    response = client.get("/api/v1/monitoring/getting-started", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_each_step_is_ticked_once_what_it_asks_for_exists(client, auth_headers):
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Getting started"}
    ).json()
    frame = pd.DataFrame({"hhid": [1, 2, 3], "age": [30, None, 41]})
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        data={"project_id": project["id"]},
        files={"file": ("start.csv", frame.to_csv(index=False).encode(), "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    dataset = (body["datasets"][0] if "datasets" in body else body)["id"]
    client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "dataset_id": dataset,
            "name": "Age recorded",
            "check_type": "missing_rate",
            "threshold": 0,
            "severity": "warning",
            "config": {"variable": "age"},
        },
    )
    client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={"name": "Households", "dataset_id": dataset, "spec": {"agg": "count"}},
    )
    client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": "First board", "project_id": project["id"]},
    )
    person(client, auth_headers, "viewer")

    listed = steps(client, auth_headers)
    # In the order they are worth doing, an administrator's with the team last.
    assert [step["key"] for step in listed] == KEYS
    assert all(step["done"] for step in listed), listed


def test_only_those_who_can_do_the_steps_are_given_them(client, auth_headers):
    assert steps(client, person(client, auth_headers, "analyst")) == []
    assert steps(client, person(client, auth_headers, "viewer")) == []


def test_a_manager_is_not_asked_to_invite_anybody(client, auth_headers):
    keys = [step["key"] for step in steps(client, person(client, auth_headers, "manager"))]
    assert keys == KEYS[:-1]


def test_steps_are_counted_within_what_the_person_can_see(client, auth_headers):
    # Confined to projects and a member of none: the install has data, but none
    # of it is theirs, so for them nothing has been done yet.
    headers = person(client, auth_headers, "manager", restricted=True)
    assert not any(step["done"] for step in steps(client, headers))


def test_putting_the_list_away_is_remembered_against_the_account(client, auth_headers):
    headers = person(client, auth_headers, "manager")
    assert client.get("/api/v1/auth/me", headers=headers).json()["preferences"][
        "getting_started_hidden"
    ] is None
    changed = client.patch(
        "/api/v1/auth/me/preferences", headers=headers, json={"getting_started_hidden": True}
    )
    assert changed.status_code == 200, changed.text
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["preferences"]["getting_started_hidden"] is True
    # The other preference is left as it was.
    assert me["preferences"]["sidebar_pinned"] is None
