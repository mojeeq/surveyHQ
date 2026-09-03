"""The Survey Solutions connection: where its imports land, and what it keeps.

A sync used to download an export, keep the first data file in it and throw the
rest away, into the shared area whatever project the survey belonged to. These
cover the two halves of the fix: a connection names a project, and the export
zip is kept where it can be fetched back.
"""

from __future__ import annotations

import zipfile


def _connection(client, auth_headers, **overrides) -> dict:
    payload = {
        "name": "Field server",
        "base_url": "https://survey.example.org",
        "workspace": "primary",
        "username": "api_user",
        "password": "secret",
        **overrides,
    }
    response = client.post("/api/v1/connections", headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_connection_remembers_which_project_its_imports_belong_to(client, auth_headers):
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Labour force 2026"}
    ).json()

    connection = _connection(client, auth_headers, project_id=project["id"])
    assert connection["project_id"] == project["id"]

    again = client.get(f"/api/v1/connections/{connection['id']}", headers=auth_headers).json()
    assert again["project_id"] == project["id"]


def test_a_connection_can_be_moved_to_another_project(client, auth_headers):
    first = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Round one"}
    ).json()
    second = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Round two"}
    ).json()

    connection = _connection(client, auth_headers, project_id=first["id"])
    moved = client.patch(
        f"/api/v1/connections/{connection['id']}",
        headers=auth_headers,
        json={"project_id": second["id"]},
    )
    assert moved.status_code == 200
    assert moved.json()["project_id"] == second["id"]

    # And back to the shared area
    released = client.patch(
        f"/api/v1/connections/{connection['id']}", headers=auth_headers, json={"project_id": None}
    )
    assert released.json()["project_id"] is None


def test_the_password_never_comes_back_out(client, auth_headers):
    connection = _connection(client, auth_headers)
    assert "password" not in connection
    assert connection["has_password"] is True


def test_an_exported_archive_can_be_downloaded_again(client, auth_headers, tmp_path, db_session):
    """The zip is the only record of what the server actually sent."""
    from app.db.base import utcnow
    from app.models import SyncRun, SyncStatus

    connection = _connection(client, auth_headers)

    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("household.dta", b"data")

    run = SyncRun(
        connection_id=connection["id"],
        questionnaire="Labour Force Survey",
        status=SyncStatus.success,
        started_at=utcnow(),
        archive_path=str(archive),
    )
    db_session.add(run)
    db_session.commit()

    listed = client.get(
        f"/api/v1/connections/{connection['id']}/runs", headers=auth_headers
    ).json()
    assert listed[0]["has_archive"] is True

    downloaded = client.get(
        f"/api/v1/connections/{connection['id']}/runs/{run.id}/archive", headers=auth_headers
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    assert downloaded.content == archive.read_bytes()
    assert "labour-force-survey" in downloaded.headers["content-disposition"]


def test_a_run_whose_archive_was_pruned_does_not_offer_a_download(
    client, auth_headers, tmp_path, db_session
):
    """Archives are pruned, and offering a download that 404s is worse."""
    from app.db.base import utcnow
    from app.models import SyncRun, SyncStatus

    connection = _connection(client, auth_headers)
    run = SyncRun(
        connection_id=connection["id"],
        questionnaire="Gone",
        status=SyncStatus.success,
        started_at=utcnow(),
        archive_path=str(tmp_path / "never-written.zip"),
    )
    db_session.add(run)
    db_session.commit()

    listed = client.get(
        f"/api/v1/connections/{connection['id']}/runs", headers=auth_headers
    ).json()
    assert listed[0]["has_archive"] is False

    missing = client.get(
        f"/api/v1/connections/{connection['id']}/runs/{run.id}/archive", headers=auth_headers
    )
    assert missing.status_code == 404
    assert "no longer on the server" in missing.json()["detail"]


def test_an_archive_cannot_be_fetched_through_another_connection(
    client, auth_headers, tmp_path, db_session
):
    from app.db.base import utcnow
    from app.models import SyncRun, SyncStatus

    mine = _connection(client, auth_headers)
    theirs = _connection(client, auth_headers, name="Another server")

    archive = tmp_path / "theirs.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("household.dta", b"data")
    run = SyncRun(
        connection_id=theirs["id"],
        questionnaire="Theirs",
        status=SyncStatus.success,
        started_at=utcnow(),
        archive_path=str(archive),
    )
    db_session.add(run)
    db_session.commit()

    response = client.get(
        f"/api/v1/connections/{mine['id']}/runs/{run.id}/archive", headers=auth_headers
    )
    assert response.status_code == 404
