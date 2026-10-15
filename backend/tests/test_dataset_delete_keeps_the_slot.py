"""Deleting a dataset must not demolish what was built on it.

Everything built on a dataset points at its id. Delete the row and the database
cascades: the charts, indicators, quality rules, target sets and alert rules go
with it, and the dashboard widgets that showed them are blanked. Then the same
export is uploaded again, and nothing reconnects, because an upload creates a
new dataset with a new id. A morning's work on a dashboard is gone, and the
only thing that happened was somebody clearing out data they were about to
replace.

So a dataset with work built on it is emptied rather than removed: the data
goes, the id stays, and the next import of that export fills it back in with
every chart still attached. That is not a new mechanism, it is the one
archiving a project already uses, which is why `empty_dataset` is shared.

A dataset nobody has built anything on is deleted outright, and an empty slot
deletes for real on the second go, so a project can still be cleared out.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest
from sqlalchemy import select

from app.models import Chart, Dataset, DatasetStatus, Widget
from tests.test_api_analytics import _stata_bytes

FRAME = pd.DataFrame(
    {
        "pid": [1.0, 2.0, 3.0, 4.0],
        "region": ["North", "South", "North", "South"],
        "wage": [100.0, 200.0, 300.0, 400.0],
    }
)


def export(frame: pd.DataFrame = FRAME) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("persons.dta", _stata_bytes(frame))
    return buf.getvalue()


def upload(client, auth_headers, project_id: str) -> str:
    sent = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", export(), "application/zip")},
        data={"project_id": project_id},
    )
    assert sent.status_code == 201, sent.text
    return sent.json()["datasets"][0]["id"]


@pytest.fixture
def project(client, auth_headers, request) -> str:
    made = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": f"Keep {request.node.name[:30]}"},
    )
    return made.json()["id"]


@pytest.fixture
def built(client, auth_headers, project) -> dict:
    """A dataset with a chart and a dashboard widget standing on it."""
    dataset_id = upload(client, auth_headers, project)
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Wage by region",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "region"}],
                    "measures": [{"agg": "sum", "variable": "wage", "alias": "total"}],
                }
            },
        },
    )
    assert chart.status_code == 201, chart.text
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Board"}
    ).json()
    widget = client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Wage by region",
            "widget_type": "chart",
            "chart_id": chart.json()["id"],
            "dataset_id": dataset_id,
        },
    )
    assert widget.status_code == 201, widget.text
    return {
        "project": project,
        "dataset_id": dataset_id,
        "chart_id": chart.json()["id"],
        "dashboard_id": board["id"],
    }


# --- The thing that was broken -----------------------------------------------


def test_deleting_keeps_the_chart_and_the_widget(built, client, auth_headers, db_session):
    gone = client.delete(f"/api/v1/datasets/{built['dataset_id']}", headers=auth_headers)
    assert gone.status_code == 200, gone.text
    db_session.expire_all()

    chart = db_session.get(Chart, built["chart_id"])
    assert chart is not None, "the chart was deleted with the dataset"
    assert chart.dataset_id == built["dataset_id"], "the chart lost its dataset"

    widget = db_session.scalars(
        select(Widget).where(Widget.chart_id == built["chart_id"])
    ).first()
    assert widget is not None, "the widget lost the chart it showed"
    assert widget.dataset_id == built["dataset_id"]


def test_the_data_really_does_go(built, client, auth_headers, db_session):
    """Emptying is not a pretend delete: the file is gone and the rows with it."""
    client.delete(f"/api/v1/datasets/{built['dataset_id']}", headers=auth_headers)
    db_session.expire_all()

    dataset = db_session.get(Dataset, built["dataset_id"])
    assert dataset is not None
    assert dataset.status == DatasetStatus.archived
    assert dataset.storage_path == ""
    assert dataset.file_size == 0


def test_uploading_the_export_again_brings_everything_back(
    built, client, auth_headers, db_session
):
    """The whole point, end to end: delete, re-upload, and the chart works."""
    client.delete(f"/api/v1/datasets/{built['dataset_id']}", headers=auth_headers)
    db_session.expire_all()

    again = upload(client, auth_headers, built["project"])
    assert again == built["dataset_id"], "the re-upload made a new dataset instead"
    db_session.expire_all()

    dataset = db_session.get(Dataset, built["dataset_id"])
    assert dataset.status == DatasetStatus.ready
    assert dataset.row_count == 4

    # And the chart draws, which is the claim that matters.
    drawn = client.post(
        f"/api/v1/dashboards/charts/{built['chart_id']}/data",
        headers=auth_headers,
        json={},
    )
    assert drawn.status_code == 200, drawn.text


def test_the_message_says_what_was_kept(built, client, auth_headers):
    said = client.delete(
        f"/api/v1/datasets/{built['dataset_id']}", headers=auth_headers
    ).json()["detail"]

    assert "emptied" in said
    assert "chart" in said
    assert "waiting for data" in said


# --- And it is still a delete ------------------------------------------------


def test_a_dataset_nobody_built_on_is_deleted_outright(
    client, auth_headers, project, db_session
):
    dataset_id = upload(client, auth_headers, project)

    said = client.delete(f"/api/v1/datasets/{dataset_id}", headers=auth_headers)
    assert said.status_code == 200
    assert "deleted" in said.json()["detail"]
    db_session.expire_all()

    assert db_session.get(Dataset, dataset_id) is None


def test_deleting_an_empty_slot_finishes_the_job(built, client, auth_headers, db_session):
    """Otherwise a project with charts on it could never be cleared out."""
    client.delete(f"/api/v1/datasets/{built['dataset_id']}", headers=auth_headers)
    db_session.expire_all()
    assert db_session.get(Dataset, built["dataset_id"]) is not None

    second = client.delete(
        f"/api/v1/datasets/{built['dataset_id']}", headers=auth_headers
    )
    assert second.status_code == 200
    assert "deleted" in second.json()["detail"]
    db_session.expire_all()

    assert db_session.get(Dataset, built["dataset_id"]) is None


def test_clearing_a_whole_project_keeps_the_slots_that_are_built_on(
    built, client, auth_headers, db_session
):
    """The way somebody actually hits this: select everything, delete."""
    cleared = client.post(
        "/api/v1/datasets/delete",
        headers=auth_headers,
        json={"project_id": built["project"]},
    )
    assert cleared.status_code == 200, cleared.text
    assert "emptied" in cleared.json()["detail"]
    db_session.expire_all()

    assert db_session.get(Dataset, built["dataset_id"]) is not None
    assert db_session.get(Chart, built["chart_id"]) is not None


# --- A plain file, not an archive --------------------------------------------


def raw_upload(client, auth_headers, project_id: str, name: str = "persons.dta") -> str:
    sent = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": (name, _stata_bytes(FRAME), "application/octet-stream")},
        data={"project_id": project_id},
    )
    assert sent.status_code == 201, sent.text
    body = sent.json()
    return (body["datasets"][0]["id"] if "datasets" in body else body["id"])


@pytest.fixture
def built_from_a_plain_file(client, auth_headers, project) -> dict:
    dataset_id = raw_upload(client, auth_headers, project)
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Wage by region",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "region"}],
                    "measures": [{"agg": "sum", "variable": "wage", "alias": "total"}],
                }
            },
        },
    )
    assert chart.status_code == 201, chart.text
    return {"project": project, "dataset_id": dataset_id, "chart_id": chart.json()["id"]}


def test_a_plain_file_fills_the_slot_it_was_deleted_from(
    built_from_a_plain_file, client, auth_headers, db_session
):
    """The archive route found its way back by member name. A lone .dta had no
    member name, so it used to make a second dataset and leave the chart on the
    empty one - which is the promise the delete message makes, broken."""
    first = built_from_a_plain_file["dataset_id"]
    client.delete(f"/api/v1/datasets/{first}", headers=auth_headers)
    db_session.expire_all()

    again = raw_upload(client, auth_headers, built_from_a_plain_file["project"])
    assert again == first, "the re-upload made a new dataset instead of filling the slot"
    db_session.expire_all()

    refilled = db_session.get(Dataset, first)
    assert refilled.status == DatasetStatus.ready
    assert refilled.row_count == 4

    drawn = client.post(
        f"/api/v1/dashboards/charts/{built_from_a_plain_file['chart_id']}/data",
        headers=auth_headers,
        json={},
    )
    assert drawn.status_code == 200, drawn.text


def test_a_plain_upload_never_lands_on_a_dataset_that_still_has_data(
    built_from_a_plain_file, client, auth_headers, db_session
):
    """Only an empty slot is filled. Replacing live data from an ordinary
    upload would be a destruction nobody asked for, and there is a replace
    endpoint for when it is meant."""
    first = built_from_a_plain_file["dataset_id"]

    second = raw_upload(client, auth_headers, built_from_a_plain_file["project"])

    assert second != first
    db_session.expire_all()
    assert db_session.get(Dataset, first).status == DatasetStatus.ready


# --- Widgets that keep their datasets in config ------------------------------


def test_a_freshness_widget_counts_as_something_built_on_it(
    client, auth_headers, project, db_session
):
    """It watches several datasets and names them in its config rather than in
    the column, so counting the column alone called this dataset unused and
    deleted it, and the widget it was the whole subject of went quiet."""
    dataset_id = upload(client, auth_headers, project)
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Freshness"}
    ).json()
    made = client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Is the data current",
            "widget_type": "freshness",
            "dataset_id": None,
            "config": {"dataset_ids": [dataset_id]},
        },
    )
    assert made.status_code == 201, made.text

    said = client.delete(f"/api/v1/datasets/{dataset_id}", headers=auth_headers)
    assert said.status_code == 200
    assert "emptied" in said.json()["detail"], said.json()
    db_session.expire_all()

    assert db_session.get(Dataset, dataset_id) is not None
