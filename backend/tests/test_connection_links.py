"""External source links must never be mistaken for authenticated API connectors."""

import pytest

KINDS = ["odk_central", "surveycto", "cspro_csweb", "google_sheets", "kobotoolbox", "sharepoint"]


@pytest.mark.parametrize("kind", KINDS)
def test_link_round_trip_and_api_boundaries(client, auth_headers, monkeypatch, kind):
    def forbidden(*args, **kwargs):
        pytest.fail("A saved link must not contact a Survey Solutions API")

    monkeypatch.setattr("app.api.v1.endpoints.connections.SurveySolutionsClient", forbidden)
    url = "https://tenant.sharepoint.com/sites/Survey/Forms/AllItems.aspx?id=%2Ffolder&view=1"
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": kind,
            "source_kind": kind,
            "base_url": url,
        },
    )
    assert created.status_code == 201, created.text
    connection = created.json()
    assert connection["source_kind"] == kind
    assert connection["base_url"] == url
    assert not connection["has_password"]
    path = f"/api/v1/connections/{connection['id']}"
    assert client.get(path, headers=auth_headers).json()["source_kind"] == kind
    checked = client.post(path + "/test", headers=auth_headers)
    assert checked.status_code == 200
    assert checked.json()["details"]["access_verified"] is False
    for route in ("/questionnaires", "/interviews"):
        assert client.get(path + route, headers=auth_headers).status_code == 400
    assert client.post(path + "/sync", headers=auth_headers, json={}).status_code == 400
    for patch in (
        {"sync_enabled": True},
        {"username": "secret"},
        {"password": "secret"},
        {"base_url": "javascript:alert(1)"},
        {"base_url": "http://example.org"},
        {"base_url": "https://user:password@example.org"},
    ):
        assert client.patch(path, headers=auth_headers, json=patch).status_code == 422
    changed = client.patch(path, headers=auth_headers, json={"name": "Updated"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Updated"
    assert client.delete(path, headers=auth_headers).status_code == 200


def test_switch_to_link_discards_old_credentials_and_schedule(client, auth_headers):
    created = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Switch",
            "base_url": "https://survey.example.org",
            "username": "api",
            "password": "secret",
            "sync_enabled": True,
            "questionnaires": ["form"],
        },
    ).json()
    changed = client.patch(
        f"/api/v1/connections/{created['id']}",
        headers=auth_headers,
        json={"source_kind": "sharepoint", "base_url": "https://tenant.sharepoint.com/sites/a"},
    )
    assert changed.status_code == 200, changed.text
    value = changed.json()
    assert not value["has_password"]
    assert not value["sync_enabled"]
    assert value["username"] == ""
    assert value["questionnaires"] == []


@pytest.mark.parametrize(
    "override",
    [
        {"base_url": "javascript:alert(1)"},
        {"base_url": "http://tenant.sharepoint.com"},
        {"base_url": "https://user:secret@tenant.sharepoint.com"},
        {"sync_enabled": True},
        {"password": "secret"},
    ],
)
def test_invalid_link_creation(client, auth_headers, override):
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Unsafe",
            "source_kind": "sharepoint",
            "base_url": "https://tenant.sharepoint.com",
            **override,
        },
    )
    assert response.status_code == 422


def test_sharepoint_long_folder_link_is_preserved(client, auth_headers):
    url = "https://tenant.sharepoint.com/sites/a/Forms/AllItems.aspx?id=" + "%20Folder" * 100
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "Long path",
            "source_kind": "sharepoint",
            "base_url": url,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["base_url"] == url
