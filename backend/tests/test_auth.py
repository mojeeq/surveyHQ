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


def test_an_assigned_password_is_flagged_until_the_user_changes_it(client, auth_headers):
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "password-change-required@example.com",
            "role": "viewer",
            "password": "assigned-password-123",
        },
    )
    assert created.status_code == 201, created.text

    token = client.post(
        "/api/v1/auth/login",
        json={"email": "password-change-required@example.com", "password": "assigned-password-123"},
    ).json()["access_token"]
    user_headers = {"Authorization": " ".join(("Bearer", token))}

    assert client.get("/api/v1/auth/me", headers=user_headers).json()["must_change_password"] is True

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=user_headers,
        json={
            "current_password": "assigned-password-123",
            "new_password": "owner-password-456",
        },
    )
    assert changed.status_code == 200, changed.text
    assert client.get("/api/v1/auth/me", headers=user_headers).json()["must_change_password"] is False

def test_an_admin_created_account_must_also_set_its_own(client, auth_headers):
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "newcomer@example.com",
            "role": "viewer",
            "password": "assigned-password-123",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["must_change_password"] is True


def test_must_change_password_blocks_other_authenticated_endpoints(client, auth_headers):
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "mustchange@example.com",
            "role": "viewer",
            "password": "temporary-password-123",
        },
    )
    assert created.status_code == 201, created.text

    token = client.post(
        "/api/v1/auth/login",
        json={"email": "mustchange@example.com", "password": "temporary-password-123"},
    ).json()["access_token"]
    user_headers = {"Authorization": " ".join(("Bearer", token))}

    blocked = client.get("/api/v1/datasets", headers=user_headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "You must change your password before accessing this endpoint"

    assert client.get("/api/v1/auth/me", headers=user_headers).status_code == 200

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=user_headers,
        json={
            "current_password": "temporary-password-123",
            "new_password": "new-personal-password-456",
        },
    )
    assert changed.status_code == 200, changed.text
    assert client.get("/api/v1/datasets", headers=user_headers).status_code == 200


def test_a_preference_follows_the_account_and_not_the_browser(client, auth_headers):
    """Saved against the user, so a different browser sees the same answer."""
    fresh = client.get("/api/v1/auth/me", headers=auth_headers)
    assert fresh.status_code == 200, fresh.text
    # Never set is null rather than a guess, so the client can tell "they chose
    # open" from "they have not chosen" and apply its own default to the second.
    assert fresh.json()["preferences"]["sidebar_pinned"] is None

    saved = client.patch(
        "/api/v1/auth/me/preferences",
        headers=auth_headers,
        json={"sidebar_pinned": False},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["preferences"]["sidebar_pinned"] is False

    # A second request carrying no cookie or local storage of its own: this is
    # the whole point of the change.
    again = client.get("/api/v1/auth/me", headers=auth_headers)
    assert again.json()["preferences"]["sidebar_pinned"] is False

    client.patch(
        "/api/v1/auth/me/preferences", headers=auth_headers, json={"sidebar_pinned": True}
    )
    assert (
        client.get("/api/v1/auth/me", headers=auth_headers).json()["preferences"][
            "sidebar_pinned"
        ]
        is True
    )


def test_preferences_ignore_anything_not_a_known_setting(client, auth_headers):
    """The column is written from a request body, so it takes only what it knows."""
    response = client.patch(
        "/api/v1/auth/me/preferences",
        headers=auth_headers,
        json={"sidebar_pinned": False, "junk": "x" * 10_000, "is_admin": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["preferences"] == {"sidebar_pinned": False}

    # And nothing was smuggled onto the account itself.
    me = client.get("/api/v1/auth/me", headers=auth_headers).json()
    assert "junk" not in me["preferences"]
    assert me["role"] == "admin"


def test_a_partial_update_leaves_other_preferences_alone(client, auth_headers, db_session):
    """Two settings, one changed: the shell saves them one at a time."""
    from app.models import User

    user = db_session.query(User).filter(User.email == "admin@example.com").one()
    user.preferences = {"sidebar_pinned": True, "kept_by_an_older_build": "yes"}
    db_session.commit()

    client.patch(
        "/api/v1/auth/me/preferences", headers=auth_headers, json={"sidebar_pinned": False}
    )
    db_session.expire_all()
    after = db_session.query(User).filter(User.email == "admin@example.com").one()
    assert after.preferences["sidebar_pinned"] is False
    # Unknown keys already in the column are left where they are rather than
    # swept away: a rollback to the build that wrote them should find them.
    assert after.preferences["kept_by_an_older_build"] == "yes"

    user.preferences = {}
    db_session.commit()


def test_an_empty_preferences_body_changes_nothing(client, auth_headers):
    """Sending no fields must not clear the ones already stored.

    With one setting this looks academic, because a body naming it and a body
    naming nothing differ only in whether the field is set. It stops being
    academic the moment a second setting exists: dumping the model without
    exclude_unset would write null over every preference the caller did not
    mention, so each save would undo the others. Pinned here, so the mistake
    is caught before the second setting arrives rather than after.
    """
    client.patch(
        "/api/v1/auth/me/preferences", headers=auth_headers, json={"sidebar_pinned": True}
    )
    empty = client.patch("/api/v1/auth/me/preferences", headers=auth_headers, json={})
    assert empty.status_code == 200, empty.text
    assert empty.json()["preferences"]["sidebar_pinned"] is True


def test_preferences_need_a_signed_in_caller(client):
    assert client.patch(
        "/api/v1/auth/me/preferences", json={"sidebar_pinned": False}
    ).status_code == 401
