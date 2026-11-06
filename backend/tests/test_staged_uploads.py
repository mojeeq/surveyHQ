"""A large file sent in pieces, joined, and imported as if it came whole.

Cloudflare refuses any request over 100 MB on its free plan, and a census
export is gigabytes; no setting on this server reaches past that. So the
browser sends a large file in pieces and the ordinary upload names what was
sent instead of attaching it. Pieces are shrunk to a kilobyte here so a small
export still goes in several.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest
from sqlalchemy import select

from app.models import Dataset
from app.services import staged_uploads
from tests.conftest import sign_in
from tests.test_api_analytics import _stata_bytes, _zip_bytes

PEOPLE = pd.DataFrame({"hhid": [float(i % 40) for i in range(400)], "age": [30.0] * 400})


@pytest.fixture(autouse=True)
def small_pieces(monkeypatch):
    monkeypatch.setattr(staged_uploads, "CHUNK_BYTES", 1024)


@pytest.fixture
def export() -> bytes:
    return _zip_bytes({"people.dta": _stata_bytes(PEOPLE)})


@pytest.fixture
def project(client, auth_headers, request) -> dict:
    return client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": f"St {request.node.name[:40]}"}
    ).json()


def send(client, headers, payload: bytes, filename: str = "export.zip") -> str:
    """Start, send every piece, complete; the id to import by."""
    started = client.post(
        "/api/v1/datasets/uploads",
        headers=headers,
        json={"filename": filename, "size": len(payload)},
    )
    assert started.status_code == 201, started.text
    body = started.json()
    size = body["chunk_size"]
    assert body["pieces"] > 1, "the test should span several pieces"
    for index in range(body["pieces"]):
        sent = client.put(
            f"/api/v1/datasets/uploads/{body['id']}/pieces/{index}",
            headers=headers,
            content=payload[index * size : (index + 1) * size],
        )
        assert sent.status_code == 200, sent.text
    done = client.post(f"/api/v1/datasets/uploads/{body['id']}/complete", headers=headers)
    assert done.status_code == 200, done.text
    return body["id"]


def test_a_file_sent_in_pieces_imports_as_if_it_came_whole(
    client, auth_headers, db_session, project, export
):
    upload_id = send(client, auth_headers, export)
    imported = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        data={"project_id": project["id"], "staged": f'["{upload_id}"]'},
    )
    assert imported.status_code == 201, imported.text
    db_session.expire_all()
    people = db_session.scalars(
        select(Dataset).where(Dataset.project_id == project["id"], Dataset.name == "people")
    ).one()
    assert people.row_count == 400
    assert not (staged_uploads.root() / upload_id).exists(), "the pieces are cleared away"


def test_a_piece_sent_again_replaces_the_first(client, auth_headers, export):
    started = client.post(
        "/api/v1/datasets/uploads", headers=auth_headers,
        json={"filename": "export.zip", "size": len(export)},
    ).json()
    url = f"/api/v1/datasets/uploads/{started['id']}/pieces/0"
    client.put(url, headers=auth_headers, content=b"x" * 10)
    again = client.put(url, headers=auth_headers, content=export[:1024])
    assert again.json()["received"] == 1024


def test_completing_with_a_piece_missing_names_it(client, auth_headers, export):
    started = client.post(
        "/api/v1/datasets/uploads", headers=auth_headers,
        json={"filename": "export.zip", "size": len(export)},
    ).json()
    client.put(
        f"/api/v1/datasets/uploads/{started['id']}/pieces/0",
        headers=auth_headers,
        content=export[:1024],
    )
    done = client.post(f"/api/v1/datasets/uploads/{started['id']}/complete", headers=auth_headers)
    assert done.status_code == 422
    assert "the first being piece 1" in done.json()["detail"]


def test_pieces_are_held_to_the_size_and_count_declared(client, auth_headers, export):
    started = client.post(
        "/api/v1/datasets/uploads", headers=auth_headers,
        json={"filename": "export.zip", "size": len(export)},
    ).json()
    base = f"/api/v1/datasets/uploads/{started['id']}/pieces"
    too_far = client.put(f"{base}/{started['pieces']}", headers=auth_headers, content=b"x")
    assert too_far.status_code == 422
    too_big = client.put(f"{base}/0", headers=auth_headers, content=b"x" * 2048)
    assert too_big.status_code == 422


def test_an_upload_is_its_starters_alone(client, auth_headers, project, export):
    upload_id = send(client, auth_headers, export)
    email, password = "staged-other@example.com", "staged-other-password-1"
    made = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"email": email, "full_name": "Other", "role": "manager", "password": password},
    )
    assert made.status_code in (201, 409), made.text
    other = sign_in(client, email, password)

    used = client.post(
        "/api/v1/datasets/upload", headers=other,
        data={"project_id": "", "staged": f'["{upload_id}"]'},
    )
    assert used.status_code == 422 and "No such upload" in used.json()["detail"]
    added = client.put(
        f"/api/v1/datasets/uploads/{upload_id}/pieces/0", headers=other, content=b"x"
    )
    assert added.status_code == 422
    cancelled = client.delete(f"/api/v1/datasets/uploads/{upload_id}", headers=other)
    assert cancelled.status_code == 404


def test_an_id_that_is_not_one_reaches_no_path(client, auth_headers):
    sent = client.put(
        "/api/v1/datasets/uploads/..%2F..%2Fsecrets/pieces/0", headers=auth_headers, content=b"x"
    )
    assert sent.status_code in (404, 422)
    used = client.post(
        "/api/v1/datasets/upload", headers=auth_headers,
        data={"staged": '["../../etc/passwd"]'},
    )
    assert used.status_code == 422


def test_an_unfinished_upload_cannot_be_imported(client, auth_headers, export):
    started = client.post(
        "/api/v1/datasets/uploads", headers=auth_headers,
        json={"filename": "export.zip", "size": len(export)},
    ).json()
    used = client.post(
        "/api/v1/datasets/upload", headers=auth_headers,
        data={"staged": f'["{started["id"]}"]'},
    )
    assert used.status_code == 422
    assert "has not finished uploading" in used.json()["detail"]


def test_files_and_staged_ones_together_are_refused(client, auth_headers, export):
    upload_id = send(client, auth_headers, export)
    both = client.post(
        "/api/v1/datasets/upload", headers=auth_headers,
        files={"file": ("other.zip", export, "application/zip")},
        data={"staged": f'["{upload_id}"]'},
    )
    assert both.status_code == 422


def test_the_size_limit_holds_before_a_piece_is_sent(client, auth_headers):
    huge = client.post(
        "/api/v1/datasets/uploads", headers=auth_headers,
        json={"filename": "census.zip", "size": 10**15},
    )
    assert huge.status_code == 413
    assert "the limit is" in huge.json()["detail"]
    wrong = client.post(
        "/api/v1/datasets/uploads", headers=auth_headers,
        json={"filename": "notes.docx", "size": 10},
    )
    assert wrong.status_code == 400


def test_an_upload_nobody_finished_is_cleared_after_a_day(client, auth_headers, export):
    started = client.post(
        "/api/v1/datasets/uploads", headers=auth_headers,
        json={"filename": "export.zip", "size": len(export)},
    ).json()
    directory = staged_uploads.root() / started["id"]
    assert directory.exists()
    staged_uploads.prune(now=time.time() + 60)
    assert directory.exists(), "a fresh one is left alone"
    staged_uploads.prune(now=time.time() + staged_uploads.ABANDONED_AFTER_SECONDS + 60)
    assert not directory.exists()
