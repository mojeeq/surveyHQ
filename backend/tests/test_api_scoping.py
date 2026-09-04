"""What a restricted user cannot reach through a resource's own id.

Filtering a listing is the easy half. Every route below takes an id directly,
so each one is a way past the listing if it does not check for itself - which
is exactly how connections, alert rules and alerts were reachable across
projects while the listings looked correct.
"""

from __future__ import annotations

import pytest

from tests.test_api_projects import _headers


@pytest.fixture
def home_project(client, auth_headers) -> dict:
    """The one project the restricted manager belongs to."""
    response = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Their own round", "description": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def other_project(client, auth_headers) -> dict:
    """A project the restricted user is not a member of."""
    response = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Somebody else's round", "description": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def restricted_manager(client, auth_headers) -> tuple[dict, dict[str, str]]:
    """A manager confined to the projects they are given.

    A manager rather than an analyst on purpose: the role gate answers 403
    before any scope check runs, so an analyst would pass these tests without
    the scoping existing at all.
    """
    email = "restricted-manager@example.com"
    password = "restricted-manager-123"
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": email,
            "full_name": "Restricted Manager",
            "role": "manager",
            "password": password,
            "restricted_to_projects": True,
        },
    )
    if created.status_code == 201:
        user = created.json()
    else:
        assert created.status_code == 409, created.text
        page = client.get("/api/v1/users", headers=auth_headers, params={"search": email})
        user = next(u for u in page.json()["items"] if u["email"] == email)
        client.patch(
            f"/api/v1/users/{user['id']}",
            headers=auth_headers,
            json={"role": "manager", "restricted_to_projects": True, "password": password},
        )
        for existing in client.get("/api/v1/projects", headers=auth_headers).json():
            client.delete(
                f"/api/v1/projects/{existing['id']}/members/{user['id']}",
                headers=auth_headers,
            )
    return user, _headers(client, email, password)


@pytest.fixture
def member_headers(client, auth_headers, home_project, restricted_manager) -> dict[str, str]:
    """The restricted manager, a member of one project and nothing else."""
    user, headers = restricted_manager
    added = client.put(
        f"/api/v1/projects/{home_project['id']}/members",
        headers=auth_headers,
        json={"user_id": user["id"], "role": "manager"},
    )
    assert added.status_code == 200, added.text
    return headers


# --- connections -----------------------------------------------------------


@pytest.fixture
def foreign_connection(client, auth_headers, other_project) -> dict:
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Their server",
            "base_url": "https://demo.mysurvey.solutions",
            "workspace": "primary",
            "username": "api_user",
            "password": "secret-password",
            "project_id": other_project["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_connection_in_another_project_is_not_listed(
    client, member_headers, foreign_connection
):
    listed = client.get("/api/v1/connections", headers=member_headers).json()
    assert foreign_connection["id"] not in [c["id"] for c in listed]


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", ""),
        ("get", "/questionnaires"),
        ("get", "/interviews"),
        ("get", "/runs"),
        ("post", "/test"),
        ("post", "/sync"),
        ("patch", ""),
        ("delete", ""),
    ],
)
def test_a_connection_in_another_project_is_not_reachable_by_id(
    client, member_headers, foreign_connection, method, path
):
    """Not 403: a response that distinguished the two would confirm it exists."""
    url = f"/api/v1/connections/{foreign_connection['id']}{path}"
    kwargs = {"json": {}} if method in {"post", "patch"} else {}
    response = getattr(client, method)(url, headers=member_headers, **kwargs)
    assert response.status_code == 404, f"{method} {url} -> {response.status_code}"


def test_a_connection_cannot_be_created_into_another_project(
    client, member_headers, other_project
):
    response = client.post(
        "/api/v1/connections",
        headers=member_headers,
        json={
            "name": "Sneaking in",
            "base_url": "https://demo.mysurvey.solutions",
            "workspace": "primary",
            "username": "api_user",
            "password": "secret-password",
            "project_id": other_project["id"],
        },
    )
    assert response.status_code == 404, response.text


# --- alert rules and alerts ------------------------------------------------


@pytest.fixture
def foreign_indicator(client, auth_headers, other_project, dataset_id) -> dict:
    """An indicator on a dataset inside a project the caller cannot reach."""
    moved = client.put(
        f"/api/v1/projects/assign/dataset/{dataset_id}",
        headers=auth_headers,
        json={"project_id": other_project["id"]},
    )
    assert moved.status_code == 200, moved.text
    response = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Their interviews",
            "dataset_id": dataset_id,
            "spec": {
                "dimensions": [],
                "measures": [{"agg": "count", "alias": "value"}],
                "limit": 1,
            },
        },
    )
    assert response.status_code == 201, response.text
    indicator = response.json()
    yield indicator
    client.delete(f"/api/v1/monitoring/indicators/{indicator['id']}", headers=auth_headers)
    client.put(
        f"/api/v1/projects/assign/dataset/{dataset_id}",
        headers=auth_headers,
        json={"project_id": None},
    )


@pytest.fixture
def foreign_alert_rule(client, auth_headers, foreign_indicator) -> dict:
    response = client.post(
        "/api/v1/monitoring/alert-rules",
        headers=auth_headers,
        json={
            "name": "Their rule",
            "indicator_id": foreign_indicator["id"],
            "condition": {"operator": "gt", "value": 0},
            "severity": "warning",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("method,path", [("patch", ""), ("delete", ""), ("post", "/test")])
def test_an_alert_rule_on_another_project_is_not_reachable_by_id(
    client, member_headers, foreign_alert_rule, method, path
):
    url = f"/api/v1/monitoring/alert-rules/{foreign_alert_rule['id']}{path}"
    kwargs = {"json": {"name": "Renamed by somebody else"}} if method == "patch" else {}
    response = getattr(client, method)(url, headers=member_headers, **kwargs)
    assert response.status_code == 404, f"{method} {url} -> {response.status_code}"


def test_an_alert_rule_cannot_be_moved_onto_an_unreachable_indicator(
    client, member_headers, auth_headers, foreign_indicator
):
    mine = client.post(
        "/api/v1/monitoring/alert-rules",
        headers=member_headers,
        json={
            "name": "My rule",
            "condition": {"operator": "lt", "value": 5},
            "severity": "warning",
        },
    )
    assert mine.status_code == 201, mine.text
    response = client.patch(
        f"/api/v1/monitoring/alert-rules/{mine.json()['id']}",
        headers=member_headers,
        json={"indicator_id": foreign_indicator["id"]},
    )
    assert response.status_code == 404, response.text
    client.delete(f"/api/v1/monitoring/alert-rules/{mine.json()['id']}", headers=auth_headers)


def test_an_alert_raised_by_another_project_cannot_be_acknowledged(
    client, auth_headers, member_headers, foreign_alert_rule
):
    triggered = client.post(
        f"/api/v1/monitoring/alert-rules/{foreign_alert_rule['id']}/test", headers=auth_headers
    )
    assert triggered.status_code == 200, triggered.text
    alerts = client.get(
        "/api/v1/monitoring/alerts", headers=auth_headers, params={"limit": 50}
    ).json()
    mine = [a for a in alerts if a["rule_id"] == foreign_alert_rule["id"]]
    assert mine, "the rule should have raised an alert to try reaching"
    alert_id = mine[0]["id"]
    assert (
        client.post(
            f"/api/v1/monitoring/alerts/{alert_id}/acknowledge", headers=member_headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/monitoring/alerts/{alert_id}/resolve", headers=member_headers
        ).status_code
        == 404
    )
