"""A connection that is a folder rather than a server.

Creating an API user on a Survey Solutions server is an administrator's
privilege, and the answer is sometimes no. The office is not stuck: somebody
downloads the export by hand, or has the server push it to a cloud drive, and
the file lands in a folder on this machine. From there on it is the import a
server connection runs - the same unpacking, the same one dataset per roster
level, the same replacement in place that keeps the charts built on it.

These cover the whole path: what the form will accept, what the test button
reports, what a run imports, and the two things a folder gets wrong that a
server cannot - the same file offered twice, and a file still being copied in.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.core.config import settings
from app.models import Connection, Dataset, FolderImport, Job, SourceKind, SyncRun
from tests.test_api_analytics import _stata_bytes

BASE = "/api/v1/connections"


@pytest.fixture(autouse=True)
def _no_broker(monkeypatch):
    """Queueing is somebody else's test. Here the task is run in place."""
    from app.workers.tasks import run_folder_import

    monkeypatch.setattr(
        run_folder_import, "delay", lambda *args: SimpleNamespace(id="queued-test")
    )


@pytest.fixture
def level(request) -> str:
    """A roster level name this test alone uses.

    One database serves the whole suite, and an import replaces the dataset
    already holding a member's name - so two tests both importing "interview"
    would be reading each other's rows.
    """
    return f"interview_{abs(hash(request.node.name)) % 100000}"


@pytest.fixture
def incoming(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "incoming"
    root.mkdir()
    monkeypatch.setattr(settings, "import_roots", str(root))
    monkeypatch.setattr(settings, "import_settle_seconds", 0)
    return root


def export_zip(**frames: pd.DataFrame) -> bytes:
    """An export as a survey server writes one: a file per roster level."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        for name, frame in frames.items():
            handle.writestr(f"{name}.dta", _stata_bytes(frame))
    return buffer.getvalue()


def interviews(count: int = 3, status: str = "done") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(count)],
            "region": ["North", "South"] * (count // 2) + ["North"] * (count % 2),
            "status": [status] * count,
        }
    )


def drop(folder: Path, name: str, body: bytes, seconds_ago: int = 3600) -> Path:
    path = folder / name
    path.write_bytes(body)
    when = dt.datetime.now(dt.UTC).timestamp() - seconds_ago
    os.utime(path, (when, when))
    return path


def make_connection(client, auth_headers, folder: Path, **extra) -> dict:
    response = client.post(
        BASE,
        headers=auth_headers,
        json={
            "name": "Staged exports",
            "source_kind": "folder",
            "folder_path": str(folder),
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def run_import(client, auth_headers, db_session, connection_id: str, mode: str = "replace"):
    """Queue the import and run it here, as the worker would."""
    from app.workers.tasks import run_folder_import

    response = client.post(
        f"{BASE}/{connection_id}/sync", headers=auth_headers, json={"mode": mode}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    outcome = run_folder_import(job_id)
    db_session.expire_all()
    return job_id, outcome


# --- Setting one up ----------------------------------------------------------


def test_a_folder_connection_needs_no_server_or_credentials(client, auth_headers, incoming):
    connection = make_connection(client, auth_headers, incoming)

    assert connection["source_kind"] == "folder"
    assert connection["folder_path"] == str(incoming)
    assert connection["base_url"] == ""


def test_a_folder_outside_what_the_server_allows_is_refused(client, auth_headers, tmp_path):
    other = tmp_path / "somewhere-else"
    other.mkdir()

    response = client.post(
        BASE,
        headers=auth_headers,
        json={"name": "Nope", "source_kind": "folder", "folder_path": str(other)},
    )

    assert response.status_code == 400
    assert "outside the folders" in response.text


def test_a_server_connection_still_needs_its_url(client, auth_headers):
    response = client.post(BASE, headers=auth_headers, json={"name": "No URL"})

    assert response.status_code == 422
    assert "needs the server URL" in response.text


def test_a_folder_connection_needs_its_folder(client, auth_headers):
    response = client.post(
        BASE, headers=auth_headers, json={"name": "No folder", "source_kind": "folder"}
    )

    assert response.status_code == 422
    assert "needs the folder to read" in response.text


# --- What the test button says ----------------------------------------------


def test_testing_an_empty_folder_says_it_is_empty(client, auth_headers, incoming):
    connection = make_connection(client, auth_headers, incoming)

    answer = client.post(f"{BASE}/{connection['id']}/test", headers=auth_headers).json()

    assert answer["ok"] is True
    assert "empty" in answer["message"]


def test_testing_counts_what_is_waiting(client, auth_headers, incoming):
    drop(incoming, "round-one.zip", export_zip(interview=interviews()))
    drop(incoming, "round-two.zip", export_zip(interview=interviews(4)))
    connection = make_connection(client, auth_headers, incoming)

    answer = client.post(f"{BASE}/{connection['id']}/test", headers=auth_headers).json()

    assert answer["ok"] is True
    assert answer["details"]["files"] == 2
    assert answer["details"]["new"] == 2
    assert "2 not imported yet" in answer["message"]


def test_testing_a_folder_that_has_gone_says_so(client, auth_headers, incoming):
    connection = make_connection(client, auth_headers, incoming)
    incoming.rmdir()

    answer = client.post(f"{BASE}/{connection['id']}/test", headers=auth_headers).json()

    assert answer["ok"] is False
    assert "does not exist" in answer["message"]


# --- Importing ---------------------------------------------------------------


def owned(db_session, model, connection_id):
    return db_session.query(model).filter(model.connection_id == connection_id)


def test_an_export_in_the_folder_becomes_datasets(
    client, auth_headers, db_session, incoming, level
):
    """One dataset per roster level, exactly as a server import makes."""
    drop(
        incoming,
        "survey.zip",
        export_zip(**{level: interviews(4), f"{level}_member": interviews(6)}),
    )
    connection = make_connection(client, auth_headers, incoming)

    run_import(client, auth_headers, db_session, connection["id"])

    names = {one.name for one in owned(db_session, Dataset, connection["id"]).all()}
    assert names == {level, f"{level}_member"}


def test_a_second_run_leaves_a_file_it_has_read_alone(
    client, auth_headers, db_session, incoming, level
):
    """Otherwise every scheduled run re-imports the whole folder."""
    drop(incoming, "survey.zip", export_zip(**{level: interviews(4)}))
    connection = make_connection(client, auth_headers, incoming)
    run_import(client, auth_headers, db_session, connection["id"])

    _, outcome = run_import(client, auth_headers, db_session, connection["id"])

    assert outcome["imported"] == 0
    assert owned(db_session, FolderImport, connection["id"]).count() == 1


def test_tomorrows_export_under_the_same_name_is_imported(
    client, auth_headers, db_session, incoming, level
):
    """A nightly export is called the same thing every night. What makes it
    new is that it reads differently."""
    drop(incoming, "nightly.zip", export_zip(**{level: interviews(4)}))
    connection = make_connection(client, auth_headers, incoming)
    run_import(client, auth_headers, db_session, connection["id"])

    drop(incoming, "nightly.zip", export_zip(**{level: interviews(8)}))
    _, outcome = run_import(client, auth_headers, db_session, connection["id"])

    assert outcome["imported"] == 1
    dataset = owned(db_session, Dataset, connection["id"]).one()
    # Replaced in place: the same dataset, holding the newer rows.
    assert dataset.row_count == 8


def test_a_file_still_being_copied_in_is_left_until_next_time(
    client, auth_headers, db_session, incoming, monkeypatch, level
):
    """A 40 MB export has its final name long before it is whole."""
    monkeypatch.setattr(settings, "import_settle_seconds", 60)
    drop(incoming, "arriving.zip", export_zip(**{level: interviews(4)}), seconds_ago=2)
    connection = make_connection(client, auth_headers, incoming)

    job_id, outcome = run_import(client, auth_headers, db_session, connection["id"])

    assert outcome["imported"] == 0
    job = db_session.get(Job, job_id)
    assert job.result["still_arriving"] == 1
    # Nothing recorded, so it is read the next time round rather than skipped
    # for good.
    assert owned(db_session, FolderImport, connection["id"]).count() == 0


def test_a_file_that_cannot_be_read_fails_once_and_is_not_retried_forever(
    client, auth_headers, db_session, incoming
):
    drop(incoming, "broken.zip", b"this is not a zip at all")
    connection = make_connection(client, auth_headers, incoming)

    run_import(client, auth_headers, db_session, connection["id"])

    run = owned(db_session, SyncRun, connection["id"]).one()
    assert run.status.value == "failed"
    assert owned(db_session, FolderImport, connection["id"]).count() == 1


def test_the_operators_own_file_is_never_deleted_or_moved(
    client, auth_headers, db_session, incoming, level
):
    """The folder is theirs. The archive pruning that keeps five exports per
    connection must not reach into it, so a run of this kind keeps no archive
    path at all."""
    staged = drop(incoming, "survey.zip", export_zip(**{level: interviews(4)}))
    connection = make_connection(client, auth_headers, incoming)

    run_import(client, auth_headers, db_session, connection["id"])

    assert staged.exists()
    assert owned(db_session, SyncRun, connection["id"]).one().archive_path == ""


def test_a_plain_data_file_is_imported_too(
    client, auth_headers, db_session, incoming, level
):
    """Not everything arrives as an export. A .dta somebody saved out is a
    dataset as much as an archive is."""
    drop(incoming, f"{level}.dta", _stata_bytes(interviews(5)))
    connection = make_connection(client, auth_headers, incoming)

    run_import(client, auth_headers, db_session, connection["id"])

    dataset = owned(db_session, Dataset, connection["id"]).one()
    assert dataset.name == level
    assert dataset.row_count == 5


def test_the_run_history_names_the_file(
    client, auth_headers, db_session, incoming, level
):
    drop(incoming, "round-one.zip", export_zip(**{level: interviews(4)}))
    connection = make_connection(client, auth_headers, incoming)

    run_import(client, auth_headers, db_session, connection["id"])

    run = owned(db_session, SyncRun, connection["id"]).one()
    assert run.questionnaire == "round-one.zip"
    assert "round-one.zip" in run.message


# --- Scheduling --------------------------------------------------------------


def test_a_folder_connection_is_due_without_choosing_questionnaires(
    client, auth_headers, db_session, incoming, level
):
    """A server connection with nothing ticked has nothing to ask for. A
    folder connection does not choose: what is in the folder is what there is."""
    from app.workers.tasks import schedule_due_syncs

    drop(incoming, "survey.zip", export_zip(**{level: interviews(4)}))
    connection = make_connection(
        client, auth_headers, incoming, sync_enabled=True, sync_interval_minutes=5
    )
    db_session.expire_all()
    # Scheduling looks at every connection in the database, and this one test
    # does not own all of them. What it claims is about its own connection:
    # that it came due, and came due once.
    before = {found for (found,) in db_session.query(Job.id)}

    queued = schedule_due_syncs()

    assert queued["queued"] >= 1
    db_session.expire_all()
    mine = [
        job
        for job in db_session.query(Job)
        if job.id not in before
        and (job.params or {}).get("connection_id") == connection["id"]
    ]
    assert len(mine) == 1
    assert mine[0].params["source_kind"] == SourceKind.folder.value


def test_a_server_connection_with_nothing_ticked_is_still_skipped(
    client, auth_headers, db_session, incoming
):
    from app.workers.tasks import schedule_due_syncs

    connection = Connection(
        name="Server with nothing ticked",
        base_url="https://survey.example.org",
        username="api",
        password_encrypted="x",
        sync_enabled=True,
        sync_interval_minutes=5,
        questionnaires=[],
    )
    db_session.add(connection)
    db_session.commit()

    schedule_due_syncs()

    # Other tests leave connections of their own behind, so the question is
    # whether anything was queued for this one.
    db_session.expire_all()
    queued = [
        job
        for job in db_session.query(Job).all()
        if (job.params or {}).get("connection_id") == connection.id
    ]
    assert queued == []


def test_a_run_where_every_file_failed_is_a_failed_job(
    client, auth_headers, db_session, incoming
):
    """Marked succeeded, an import that read nothing is invisible in the job
    list - which is where somebody looks when the dashboard has not moved."""
    drop(incoming, "broken.zip", b"not a zip")
    connection = make_connection(client, auth_headers, incoming)

    job_id, _ = run_import(client, auth_headers, db_session, connection["id"])

    job = db_session.get(Job, job_id)
    assert job.status.value == "failed"
    assert job.error


def test_a_run_where_one_of_two_files_failed_still_counts_as_done(
    client, auth_headers, db_session, incoming, level
):
    """One unreadable file among several is a failed run, not a failed import:
    the others arrived, and the job list should not say otherwise."""
    drop(incoming, "broken.zip", b"not a zip")
    drop(incoming, "good.zip", export_zip(**{level: interviews(4)}))
    connection = make_connection(client, auth_headers, incoming)

    job_id, _ = run_import(client, auth_headers, db_session, connection["id"])

    job = db_session.get(Job, job_id)
    assert job.status.value == "success"
    assert job.result["imported"] == 1
    assert len(job.result["errors"]) == 1


def test_changing_a_connection_from_a_server_to_a_folder_takes(
    client, auth_headers, db_session, incoming
):
    """The form offers the choice when editing, so a save that reported
    success while the connection went on behaving as a server would be a lie
    nobody could see."""
    made = client.post(
        BASE,
        headers=auth_headers,
        json={"name": "Was a server", "base_url": "https://survey.example.org"},
    ).json()

    changed = client.patch(
        f"{BASE}/{made['id']}",
        headers=auth_headers,
        json={"source_kind": "folder", "folder_path": str(incoming)},
    )

    assert changed.status_code == 200, changed.text
    assert changed.json()["source_kind"] == "folder"
    assert changed.json()["folder_path"] == str(incoming)


def test_becoming_a_folder_connection_without_a_readable_folder_is_refused(
    client, auth_headers, tmp_path
):
    made = client.post(
        BASE,
        headers=auth_headers,
        json={"name": "Was a server too", "base_url": "https://survey.example.org"},
    ).json()

    refused = client.patch(
        f"{BASE}/{made['id']}",
        headers=auth_headers,
        json={"source_kind": "folder", "folder_path": str(tmp_path / "elsewhere")},
    )

    assert refused.status_code == 400
    assert "outside the folders" in refused.text


def test_the_settings_a_folder_connection_reads_reach_the_containers():
    """Compose substitutes .env into this file and nothing else, so a setting
    the file does not name never reaches the container - and uncommenting it
    in .env would change nothing at all."""
    yaml = pytest.importorskip("yaml")

    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    )
    for name in ("api", "worker"):
        env = compose["services"][name]["environment"]
        assert "IMPORT_ROOTS" in env, name
        assert "IMPORT_SETTLE_SECONDS" in env, name


def test_the_worker_can_see_the_folder_the_api_offers():
    """The API lists the folder; the worker reads it.

    Mounted into one container and not the other, a folder connection tests
    green and every import after it fails with "does not exist" - which looks
    like the operator typed the path wrong, and is the compose file's fault.
    """
    yaml = pytest.importorskip("yaml")

    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    )
    services = compose["services"]
    for name in ("api", "worker"):
        mounts = " ".join(str(one) for one in services[name].get("volumes") or [])
        assert "/incoming" in mounts, (
            f"the {name} container cannot see the staging folder"
        )
