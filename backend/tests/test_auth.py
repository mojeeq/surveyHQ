"""Authentication, authorisation and API keys."""

from __future__ import annotations


def test_login_returns_token(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "test-password-123"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_login_rejects_wrong_password(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong"}
    )
    assert response.status_code == 401
    # The message must not reveal whether the account exists
    assert response.json()["detail"] == "Incorrect email or password"


def test_login_rejects_unknown_account_identically(client):
    response = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_protected_endpoint_requires_authentication(client):
    assert client.get("/api/v1/datasets").status_code == 401


def test_api_key_authenticates(client, auth_headers):
    created = client.post(
        "/api/v1/auth/api-keys", headers=auth_headers, json={"name": "tests"}
    )
    assert created.status_code == 201
    key = created.json()["key"]

    response = client.get("/api/v1/datasets", headers={"X-API-Key": key})
    assert response.status_code == 200

    revoked = client.delete(
        f"/api/v1/auth/api-keys/{created.json()['id']}", headers=auth_headers
    )
    assert revoked.status_code == 200
    assert client.get("/api/v1/datasets", headers={"X-API-Key": key}).status_code == 401


def test_viewer_cannot_upload(client, auth_headers):
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "viewer@example.com",
            "full_name": "Viewer",
            "role": "viewer",
            "password": "viewer-password-1",
        },
    )
    assert created.status_code == 201
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@example.com", "password": "viewer-password-1"},
    ).json()["access_token"]

    response = client.post(
        "/api/v1/datasets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert response.status_code == 403
