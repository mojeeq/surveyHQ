"""Finding the person to add to a project.

Adding a member used to mean typing an exact username. That worked while
anybody could sign themselves up and had chosen one. With self-service sign-up
off - the default - an administrator creates every account, the username is
derived from the email address, and it is shown nowhere in the interface: not
to the administrator who created it, not to the person it belongs to, not to
the project manager being asked to type it. So the box asked for something
nobody could look up, and the only route to a shared project was closed.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from tests.conftest import sign_in


@pytest.fixture(autouse=True)
def signup_closed():
    """The shipped default, which is the arrangement this module is about."""
    settings.signup_enabled = False
    yield
    settings.signup_enabled = False


@pytest.fixture
def colleague(client, auth_headers) -> dict:
    """Someone an administrator created, who therefore never chose a username."""
    email = "mary.tabi@example.com"
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": email,
            "full_name": "Mary Tabi",
            "role": "analyst",
            "password": "colleague-password-123",
        },
    )
    if created.status_code == 201:
        return created.json()
    assert created.status_code == 409, created.text
    page = client.get("/api/v1/users", headers=auth_headers, params={"search": email})
    return next(u for u in page.json()["items"] if u["email"] == email)


def _directory(client, headers, **params):
    return client.get("/api/v1/users/directory", headers=headers, params=params)


def test_the_directory_lists_people_by_name_and_address(client, auth_headers, colleague):
    listed = _directory(client, auth_headers)
    assert listed.status_code == 200, listed.text
    entry = next(p for p in listed.json() if p["id"] == colleague["id"])
    assert entry["full_name"] == "Mary Tabi"
    assert entry["email"] == "mary.tabi@example.com"


def test_a_manager_who_is_not_an_administrator_can_read_it(
    client, auth_headers, colleague
):
    """The whole point. /users is admin-only, so this was the closed door.

    A project manager is the person who adds members, and a project manager is
    not necessarily an administrator - the role on a project is its own thing.
    """
    email = "manager@example.com"
    password = "manager-password-123"
    made = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": email,
            "full_name": "Project Manager",
            "role": "manager",
            "password": password,
        },
    )
    assert made.status_code in (201, 409), made.text
    if made.status_code == 409:
        # The database outlives one test, so put the account back to the state
        # this test signs in with rather than inheriting the last run's.
        page = client.get("/api/v1/users", headers=auth_headers, params={"search": email})
        existing = next(u for u in page.json()["items"] if u["email"] == email)
        client.patch(
            f"/api/v1/users/{existing['id']}",
            headers=auth_headers,
            json={"role": "manager", "is_active": True, "password": password},
        )
    headers = sign_in(client, email, password)

    # Admin-only, and this is what made the username undiscoverable.
    assert client.get("/api/v1/users", headers=headers).status_code == 403

    listed = _directory(client, headers)
    assert listed.status_code == 200, listed.text
    assert colleague["id"] in [p["id"] for p in listed.json()]


def test_the_directory_is_searchable(client, auth_headers, colleague):
    assert colleague["id"] in [p["id"] for p in _directory(client, auth_headers, search="tabi").json()]
    assert colleague["id"] not in [
        p["id"] for p in _directory(client, auth_headers, search="nobody-by-that-name").json()
    ]


def test_a_deactivated_account_is_not_offered(client, auth_headers, colleague):
    client.patch(
        f"/api/v1/users/{colleague['id']}", headers=auth_headers, json={"is_active": False}
    )
    try:
        assert colleague["id"] not in [p["id"] for p in _directory(client, auth_headers).json()]
    finally:
        client.patch(
            f"/api/v1/users/{colleague['id']}", headers=auth_headers, json={"is_active": True}
        )


def test_it_closes_where_people_create_their_own_accounts(client, auth_headers):
    """Then the accounts are no longer all somebody's colleagues.

    A self-service account is a manager, and a manager can create a project and
    so reach this route. Handing it the installation's user list would turn
    adding a member into enumerating everyone who ever signed up.
    """
    settings.signup_enabled = True
    refused = _directory(client, auth_headers)
    assert refused.status_code == 403, refused.text
    assert "exact" in refused.json()["detail"]


def test_signing_out_closes_it_too(client):
    assert client.get("/api/v1/users/directory").status_code in (401, 403)


def test_the_person_chosen_can_be_added_as_a_member(client, auth_headers, colleague):
    """End to end: the id the directory hands back is the id membership takes."""
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Directory round trip"}
    ).json()
    entry = next(
        p for p in _directory(client, auth_headers).json() if p["id"] == colleague["id"]
    )
    added = client.put(
        f"/api/v1/projects/{project['id']}/members",
        headers=auth_headers,
        json={"user_id": entry["id"], "role": "analyst"},
    )
    assert added.status_code == 200, added.text
    assert added.json()["email"] == "mary.tabi@example.com"
