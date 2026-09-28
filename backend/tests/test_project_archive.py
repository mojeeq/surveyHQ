"""Archiving a project: the data goes, everything built on it stays.

Deleting was the only way to stop a project costing disk, and it took the
dashboards, indicators, quality rules and script with it. None of those is
large; the microdata is. So the two are separated here, and what this file pins
is the half that is easy to lose by accident - that everything except the rows
is still there afterwards, and that nothing which needs the rows pretends to
work.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.models import Dataset, DatasetStatus, ProjectStatus, ShareLink
from tests.test_api_analytics import _stata_bytes, _zip_bytes

PEOPLE = pd.DataFrame(
    {
        "hhid": [1.0, 2.0, 3.0],
        "province": ["Shefa", "Sanma", "Tafea"],
        "age": [40.0, 9.0, 33.0],
    }
)


def _project(client, auth_headers, name: str) -> dict:
    made = client.post("/api/v1/projects", headers=auth_headers, json={"name": name}).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "round.zip",
                _zip_bytes({"ar_people.dta": _stata_bytes(PEOPLE)}),
                "application/zip",
            )
        },
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    return {"id": made["id"], "dataset_id": uploaded.json()["datasets"][0]["id"]}


def _dashboard(client, auth_headers, project: dict) -> dict:
    made = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": "Fieldwork", "project_id": project["id"]},
    )
    assert made.status_code == 201, made.text
    return made.json()


def archive(client, auth_headers, project: dict):
    return client.post(f"/api/v1/projects/{project['id']}/archive", headers=auth_headers)


# --- what goes ---------------------------------------------------------------


def test_the_survey_data_is_removed_from_disk(client, auth_headers, db_session):
    """The whole point, so it is read off the file system and not the API.

    `storage_path` is deliberately not in a dataset response - it is a server
    path and no business of a browser - so asking the API for it gives None, and
    a test that then skipped its own assertion would pass while archiving
    deleted nothing at all.
    """
    project = _project(client, auth_headers, "Archive removes data")
    dataset = db_session.get(Dataset, project["dataset_id"])
    parquet = Path(dataset.storage_path)
    assert parquet.exists(), "nothing was written, so there is nothing to test"

    response = archive(client, auth_headers, project)
    assert response.status_code == 200, response.text
    assert not parquet.exists(), "the data file is still on disk"
    assert not parquet.parent.exists(), "the dataset's directory is still there"

    db_session.expire_all()
    after = db_session.get(Dataset, project["dataset_id"])
    assert after.storage_path == "", "still pointing at a file that is gone"
    assert after.file_size == 0


def test_the_message_says_how_much_disk_came_back(client, auth_headers):
    """The reason somebody is doing this, so it has to be in the answer."""
    project = _project(client, auth_headers, "Archive reports size")
    body = archive(client, auth_headers, project).json()
    assert "1 dataset(s)" in body["detail"]
    assert "freed" in body["detail"]


def test_the_size_can_be_asked_for_before_committing_to_it(client, auth_headers):
    project = _project(client, auth_headers, "Archive measures first")
    told = client.get(
        f"/api/v1/projects/{project['id']}/archive", headers=auth_headers
    ).json()
    assert told["datasets"] == 1
    assert told["bytes"] > 0
    assert told["archived"] is False


def test_the_retained_versions_are_forgotten_with_their_files(
    client, auth_headers, db_session
):
    """They were files in the directory that has just gone.

    Left in the dataset's meta the list would describe a rollback that cannot
    happen, and grow a little every time the export was replaced before someone
    archived it.
    """
    project = _project(client, auth_headers, "Archive forgets versions")
    # A second import retains the first as a version, which is what puts
    # something in the list to be left behind.
    client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "round.zip",
                _zip_bytes({"ar_people.dta": _stata_bytes(PEOPLE)}),
                "application/zip",
            )
        },
        data={"project_id": project["id"], "mode": "replace"},
    )
    db_session.expire_all()
    before = db_session.get(Dataset, project["dataset_id"])
    assert (before.meta or {}).get("retained_versions"), "nothing was retained to forget"

    archive(client, auth_headers, project)
    db_session.expire_all()
    after = db_session.get(Dataset, project["dataset_id"])
    assert "retained_versions" not in (after.meta or {})


# --- what stays --------------------------------------------------------------


def test_the_dataset_keeps_its_name_variables_and_counts(client, auth_headers):
    """The description of the data is not the data, and is what makes an
    archived project still worth opening."""
    project = _project(client, auth_headers, "Archive keeps metadata")
    archive(client, auth_headers, project)

    after = client.get(
        f"/api/v1/datasets/{project['dataset_id']}", headers=auth_headers
    ).json()
    assert after["name"] == "ar_people"
    assert after["row_count"] == 3
    assert {v["name"] for v in after["variables"]} >= {"hhid", "province", "age"}
    assert after["status"] == "archived"


def test_the_dashboard_and_its_widgets_survive(client, auth_headers):
    project = _project(client, auth_headers, "Archive keeps dashboards")
    dashboard = _dashboard(client, auth_headers, project)
    archive(client, auth_headers, project)

    after = client.get(f"/api/v1/dashboards/{dashboard['id']}", headers=auth_headers)
    assert after.status_code == 200, after.text
    assert after.json()["name"] == "Fieldwork"


def test_the_project_and_its_script_survive(client, auth_headers):
    project = _project(client, auth_headers, "Archive keeps script")
    client.put(
        f"/api/v1/projects/{project['id']}/script",
        headers=auth_headers,
        json={"text": "use ar_people\ncollapse (mean) age, by(province)\nsave as ages"},
    )
    archive(client, auth_headers, project)

    kept = client.get(
        f"/api/v1/projects/{project['id']}/script", headers=auth_headers
    ).json()
    assert "collapse (mean) age" in kept["text"]


def test_the_project_says_it_is_archived_and_when(client, auth_headers):
    project = _project(client, auth_headers, "Archive is stated")
    archive(client, auth_headers, project)
    after = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers).json()
    assert after["status"] == "archived"
    assert after["archived_at"]


# --- what stops working, and says so ----------------------------------------


def test_importing_into_an_archived_project_is_refused(client, auth_headers):
    """Half of it holding rows and the project still saying it holds none is
    worse than a refusal with a reason."""
    project = _project(client, auth_headers, "Archive refuses import")
    archive(client, auth_headers, project)

    refused = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "round.zip",
                _zip_bytes({"ar_people.dta": _stata_bytes(PEOPLE)}),
                "application/zip",
            )
        },
        data={"project_id": project["id"]},
    )
    assert refused.status_code == 422, refused.status_code
    assert "archived" in refused.json()["detail"]
    assert "Unarchive it first" in refused.json()["detail"]


def test_running_the_script_of_an_archived_project_is_refused(client, auth_headers):
    project = _project(client, auth_headers, "Archive refuses script")
    client.put(
        f"/api/v1/projects/{project['id']}/script",
        headers=auth_headers,
        json={"text": "use ar_people\nsave as copy"},
    )
    archive(client, auth_headers, project)

    refused = client.post(
        f"/api/v1/projects/{project['id']}/script/run", headers=auth_headers, json={}
    )
    assert refused.status_code == 422, refused.status_code
    assert "archived" in refused.json()["detail"]


def test_archiving_twice_is_refused_rather_than_repeated(client, auth_headers):
    project = _project(client, auth_headers, "Archive once")
    archive(client, auth_headers, project)
    again = archive(client, auth_headers, project)
    assert again.status_code == 422
    assert "already archived" in again.json()["detail"]


# --- share links -------------------------------------------------------------


def test_an_open_share_link_is_closed_by_archiving(client, auth_headers, db_session):
    """A live link showing blank charts reads as a broken platform to whoever it
    was sent to."""
    project = _project(client, auth_headers, "Archive closes links")
    dashboard = _dashboard(client, auth_headers, project)
    made = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/share-links",
        headers=auth_headers,
        json={"name": "For the ministry"},
    )
    assert made.status_code in (200, 201), made.text
    token = made.json()["token"]

    archive(client, auth_headers, project)
    assert client.get(f"/api/v1/public/dashboards/{token}").status_code >= 400

    db_session.expire_all()
    link = db_session.scalars(select(ShareLink).where(ShareLink.token == token)).first()
    assert link is not None, "the link was deleted rather than closed"
    assert link.is_active is False
    assert link.closed_by_archive is True


def test_unarchiving_reopens_the_links_archiving_closed(client, auth_headers, db_session):
    project = _project(client, auth_headers, "Unarchive reopens")
    dashboard = _dashboard(client, auth_headers, project)
    token = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/share-links",
        headers=auth_headers,
        json={"name": "For the ministry"},
    ).json()["token"]

    archive(client, auth_headers, project)
    back = client.post(
        f"/api/v1/projects/{project['id']}/unarchive", headers=auth_headers
    )
    assert back.status_code == 200, back.text
    assert "reopened" in back.json()["detail"]

    db_session.expire_all()
    link = db_session.scalars(select(ShareLink).where(ShareLink.token == token)).first()
    assert link.is_active is True
    assert link.closed_by_archive is False


def test_a_link_somebody_closed_on_purpose_is_not_reopened(
    client, auth_headers, db_session
):
    """Which is what the mark on the link is for. Unarchiving should not undo a
    decision somebody made for their own reasons."""
    project = _project(client, auth_headers, "Unarchive respects closed")
    dashboard = _dashboard(client, auth_headers, project)
    made = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/share-links",
        headers=auth_headers,
        json={"name": "Donor, report filed"},
    ).json()
    client.patch(
        f"/api/v1/dashboards/{dashboard['id']}/share-links/{made['id']}",
        headers=auth_headers,
        json={"is_active": False},
    )

    archive(client, auth_headers, project)
    client.post(f"/api/v1/projects/{project['id']}/unarchive", headers=auth_headers)

    db_session.expire_all()
    link = db_session.scalars(
        select(ShareLink).where(ShareLink.token == made["token"])
    ).first()
    assert link.is_active is False, "a link closed on purpose was reopened"


# --- coming back -------------------------------------------------------------


def test_unarchiving_lets_the_export_be_imported_again(client, auth_headers, db_session):
    """The way the data returns: the datasets kept their names, so a replacement
    import lands back in them and the dashboards pointed there start working."""
    project = _project(client, auth_headers, "Unarchive then import")
    archive(client, auth_headers, project)
    client.post(f"/api/v1/projects/{project['id']}/unarchive", headers=auth_headers)

    again = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "round.zip",
                _zip_bytes({"ar_people.dta": _stata_bytes(PEOPLE)}),
                "application/zip",
            )
        },
        data={"project_id": project["id"], "mode": "replace"},
    )
    assert again.status_code == 201, again.text

    db_session.expire_all()
    restored = db_session.scalars(
        select(Dataset).where(
            Dataset.project_id == project["id"], Dataset.name == "ar_people"
        )
    ).all()
    assert len(restored) == 1, "the import made a second dataset instead of refilling"
    assert restored[0].status == DatasetStatus.ready
    assert restored[0].row_count == 3
    assert Path(restored[0].storage_path).exists()


def test_unarchiving_something_that_is_not_archived_is_refused(client, auth_headers):
    project = _project(client, auth_headers, "Unarchive nothing")
    refused = client.post(
        f"/api/v1/projects/{project['id']}/unarchive", headers=auth_headers
    )
    assert refused.status_code == 422
    assert "not archived" in refused.json()["detail"]


def test_the_project_is_active_again_after_unarchiving(client, auth_headers, db_session):
    project = _project(client, auth_headers, "Unarchive status")
    archive(client, auth_headers, project)
    client.post(f"/api/v1/projects/{project['id']}/unarchive", headers=auth_headers)
    after = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers).json()
    assert after["status"] == ProjectStatus.active.value
    assert after["archived_at"] is None
