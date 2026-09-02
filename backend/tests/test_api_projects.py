"""Projects, and the access rules that hang off them.

The point of a project is not the grouping - it is that a user can be given
one project and nothing else. So most of what is worth testing here is what a
user *cannot* see, which no amount of exercising the happy path would catch.
"""

from __future__ import annotations

import pytest

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD  # noqa: F401


def _headers(client, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def project(client, auth_headers) -> dict:
    response = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Round 1 fieldwork", "description": "Feb 2026"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def restricted_user(client, auth_headers) -> tuple[dict, dict[str, str]]:
    """An analyst confined to whatever projects they are given.

    The database outlives a single test, so this resets an existing user to a
    known state rather than assuming it is the first to create one. Otherwise
    each test would inherit whatever the previous one left behind.
    """
    email = "restricted@example.com"
    password = "restricted-password-123"
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": email,
            "full_name": "Restricted Analyst",
            "role": "analyst",
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
            json={"role": "analyst", "restricted_to_projects": True, "password": password},
        )
        # Memberships from an earlier test would otherwise grant access here
        for project in client.get("/api/v1/projects", headers=auth_headers).json():
            client.delete(
                f"/api/v1/projects/{project['id']}/members/{user['id']}", headers=auth_headers
            )
    return user, _headers(client, email, password)


def test_creating_a_project_makes_the_creator_a_member(client, auth_headers, project):
    """Otherwise a manager would lose sight of the project the moment they made it."""
    detail = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers).json()
    assert [m["email"] for m in detail["members"]] == [ADMIN_EMAIL]
    assert detail["members"][0]["role"] == "manager"


def test_a_restricted_user_sees_no_projects_until_added(
    client, auth_headers, project, restricted_user
):
    _, headers = restricted_user
    assert client.get("/api/v1/projects", headers=headers).json() == []

    client.put(
        f"/api/v1/projects/{project['id']}/members",
        headers=auth_headers,
        json={"user_id": restricted_user[0]["id"], "role": "analyst"},
    )
    visible = client.get("/api/v1/projects", headers=headers).json()
    assert [p["id"] for p in visible] == [project["id"]]


def test_a_restricted_user_cannot_see_the_shared_area(
    client, auth_headers, dataset_id, restricted_user
):
    """The dataset is unassigned, so every ordinary user sees it - but not this one."""
    _, headers = restricted_user
    assert dataset_id in [
        d["id"] for d in client.get("/api/v1/datasets", headers=auth_headers).json()["items"]
    ]
    assert client.get("/api/v1/datasets", headers=headers).json()["items"] == []


def test_a_dataset_in_a_project_is_invisible_to_non_members(
    client, auth_headers, dataset_id, project, restricted_user
):
    member, headers = restricted_user
    client.put(
        f"/api/v1/projects/{project['id']}/members",
        headers=auth_headers,
        json={"user_id": member["id"], "role": "analyst"},
    )
    # A second project the user is not a member of
    other = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Someone else's work"}
    ).json()
    assert (
        client.put(
            f"/api/v1/projects/assign/dataset/{dataset_id}",
            headers=auth_headers,
            json={"project_id": other["id"]},
        ).status_code
        == 200
    )

    assert client.get("/api/v1/datasets", headers=headers).json()["items"] == []
    # Reported as missing rather than forbidden, so the response cannot be used
    # to discover that another project holds it.
    assert client.get(f"/api/v1/datasets/{dataset_id}", headers=headers).status_code == 404


def test_a_hidden_dataset_cannot_be_queried_either(
    client, auth_headers, dataset_id, project, restricted_user
):
    """Listing is not the only way in; the query endpoints take an id directly."""
    member, headers = restricted_user
    client.put(
        f"/api/v1/projects/{project['id']}/members",
        headers=auth_headers,
        json={"user_id": member["id"], "role": "analyst"},
    )
    other = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Off limits"}
    ).json()
    client.put(
        f"/api/v1/projects/assign/dataset/{dataset_id}",
        headers=auth_headers,
        json={"project_id": other["id"]},
    )

    for path, body in (
        ("/api/v1/analytics/query", {"dataset_id": dataset_id, "spec": {}}),
        (f"/api/v1/analytics/datasets/{dataset_id}/crosstab",
         {"row_variable": "region", "column_variable": "sex"}),
    ):
        assert client.post(path, headers=headers, json=body).status_code == 404, path
    assert (
        client.get(f"/api/v1/datasets/{dataset_id}/preview", headers=headers).status_code == 404
    )


def test_membership_cannot_exceed_the_users_own_role(
    client, auth_headers, project, restricted_user
):
    """Making a viewer a project manager must not turn them into an editor."""
    member, _ = restricted_user
    client.patch(f"/api/v1/users/{member['id']}", headers=auth_headers, json={"role": "viewer"})
    headers = _headers(client, "restricted@example.com", "restricted-password-123")
    client.put(
        f"/api/v1/projects/{project['id']}/members",
        headers=auth_headers,
        json={"user_id": member["id"], "role": "manager"},
    )

    response = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers=headers,
        json={"description": "changed"},
    )
    assert response.status_code == 403, response.text

    # Restore, so the shared session fixtures are unaffected
    client.patch(f"/api/v1/users/{member['id']}", headers=auth_headers, json={"role": "analyst"})


def test_admin_is_never_confined_to_projects(client, auth_headers, dataset_id, project):
    client.put(
        f"/api/v1/projects/assign/dataset/{dataset_id}",
        headers=auth_headers,
        json={"project_id": project["id"]},
    )
    items = client.get("/api/v1/datasets", headers=auth_headers).json()["items"]
    assert dataset_id in [d["id"] for d in items]
    # Put it back in the shared area for the tests that follow
    client.put(
        f"/api/v1/projects/assign/dataset/{dataset_id}",
        headers=auth_headers,
        json={"project_id": None},
    )


def test_project_is_not_an_admin_role(client, auth_headers, project, restricted_user):
    member, _ = restricted_user
    response = client.put(
        f"/api/v1/projects/{project['id']}/members",
        headers=auth_headers,
        json={"user_id": member["id"], "role": "admin"},
    )
    assert response.status_code == 422
    assert "global role" in response.text


def test_deleting_a_project_releases_its_data_rather_than_destroying_it(
    client, auth_headers, dataset_id, project
):
    """ON DELETE SET NULL does not exist on an upgraded database, so this is explicit."""
    client.put(
        f"/api/v1/projects/assign/dataset/{dataset_id}",
        headers=auth_headers,
        json={"project_id": project["id"]},
    )
    assert client.delete(f"/api/v1/projects/{project['id']}", headers=auth_headers).status_code == 200

    dataset = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers)
    assert dataset.status_code == 200
    assert dataset.json()["project_id"] is None


def test_dashboards_are_scoped_the_same_way(client, auth_headers, project, restricted_user):
    member, headers = restricted_user
    dashboard = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": "Project dashboard", "project_id": project["id"]},
    )
    assert dashboard.status_code == 201, dashboard.text
    dashboard_id = dashboard.json()["id"]

    assert client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers).status_code == 404

    client.put(
        f"/api/v1/projects/{project['id']}/members",
        headers=auth_headers,
        json={"user_id": member["id"], "role": "viewer"},
    )
    assert client.get(f"/api/v1/dashboards/{dashboard_id}", headers=headers).status_code == 200


def test_an_unrestricted_user_still_sees_everything_unassigned(client, auth_headers, dataset_id):
    """The upgrade path: before projects existed, every user saw every dataset."""
    email = "ordinary@example.com"
    password = "ordinary-password-123"
    client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"email": email, "role": "analyst", "password": password},
    )
    headers = _headers(client, email, password)
    items = client.get("/api/v1/datasets", headers=headers).json()["items"]
    assert dataset_id in [d["id"] for d in items]
