"""Self-service accounts, private workspaces and username project sharing."""

from __future__ import annotations


def _signup(
    client,
    username: str,
    email: str,
    password: str = "personal-password-123",
) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "username": username,
            "email": email,
            "full_name": username.replace("-", " ").title(),
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return me.json(), headers


def test_signup_creates_a_private_project_manager_and_username_login(client):
    user, headers = _signup(client, "workspace-owner", "workspace-owner@example.com")

    assert user["username"] == "workspace-owner"
    assert user["role"] == "manager"
    assert user["restricted_to_projects"] is True
    assert user["must_change_password"] is False
    assert client.get("/api/v1/projects", headers=headers).json() == []

    login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "WORKSPACE-OWNER", "password": "personal-password-123"},
    )
    assert login.status_code == 200, login.text


def test_signup_normalizes_handles_and_rejects_duplicate_identity(client):
    first, _ = _signup(client, "Mixed.Handle", "mixed-handle@example.com")
    assert first["username"] == "mixed.handle"

    duplicate_username = client.post(
        "/api/v1/auth/signup",
        json={
            "username": "MIXED.HANDLE",
            "email": "another-mixed@example.com",
            "password": "personal-password-123",
        },
    )
    assert duplicate_username.status_code == 409
    assert duplicate_username.json()["detail"] == "That username is already taken"

    duplicate_email = client.post(
        "/api/v1/auth/signup",
        json={
            "username": "another-handle",
            "email": "mixed-handle@example.com",
            "password": "personal-password-123",
        },
    )
    assert duplicate_email.status_code == 409
    assert "email" in duplicate_email.json()["detail"].lower()


def test_each_signup_user_only_sees_projects_shared_with_them(client):
    alice, alice_headers = _signup(client, "alice-workspace", "alice-workspace@example.com")
    bob, bob_headers = _signup(client, "bob-workspace", "bob-workspace@example.com")

    alice_project = client.post(
        "/api/v1/projects",
        headers=alice_headers,
        json={"name": "Alice private survey"},
    )
    bob_project = client.post(
        "/api/v1/projects",
        headers=bob_headers,
        json={"name": "Bob private census"},
    )
    assert alice_project.status_code == 201, alice_project.text
    assert bob_project.status_code == 201, bob_project.text

    alice_visible = client.get("/api/v1/projects", headers=alice_headers).json()
    bob_visible = client.get("/api/v1/projects", headers=bob_headers).json()
    assert [project["id"] for project in alice_visible] == [alice_project.json()["id"]]
    assert [project["id"] for project in bob_visible] == [bob_project.json()["id"]]

    # A project manager can resolve an exact username without administrator
    # access or a global user directory, then share the project using the
    # existing membership endpoint.
    lookup = client.get("/api/v1/users/lookup/bob-workspace", headers=alice_headers)
    assert lookup.status_code == 200, lookup.text
    assert lookup.json() == {
        "id": bob["id"],
        "username": "bob-workspace",
        "full_name": "Bob Workspace",
    }
    assert "email" not in lookup.json()

    added = client.put(
        f"/api/v1/projects/{alice_project.json()['id']}/members",
        headers=alice_headers,
        json={"user_id": lookup.json()["id"], "role": "analyst"},
    )
    assert added.status_code == 200, added.text

    bob_visible = client.get("/api/v1/projects", headers=bob_headers).json()
    assert {project["id"] for project in bob_visible} == {
        bob_project.json()["id"],
        alice_project.json()["id"],
    }
    shared = next(
        project for project in bob_visible if project["id"] == alice_project.json()["id"]
    )
    assert shared["your_role"] == "analyst"

    # Sharing is one-way. Alice still cannot see Bob's project.
    alice_visible = client.get("/api/v1/projects", headers=alice_headers).json()
    assert {project["id"] for project in alice_visible} == {alice_project.json()["id"]}
    assert alice["id"] != bob["id"]


def test_username_lookup_is_exact_authenticated_and_does_not_list_people(client):
    _, owner_headers = _signup(client, "lookup-owner", "lookup-owner@example.com")
    _signup(client, "lookup-target", "lookup-target@example.com")

    assert client.get("/api/v1/users/lookup/lookup-target").status_code == 401
    assert (
        client.get("/api/v1/users/lookup/does-not-exist", headers=owner_headers).status_code
        == 404
    )
    # Ordinary users still cannot enumerate the installation's accounts.
    assert client.get("/api/v1/users", headers=owner_headers).status_code == 403
