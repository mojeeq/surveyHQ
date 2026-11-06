"""A password-protected export, which used to come back as a server error.

Statistics offices send exports locked, because they hold interviews with named
people in them. Such a file reached the extractor, zipfile raised its own
RuntimeError, and nothing caught it: `IngestError` is what every import path
knows how to report, and this was not one. The upload answered 500 and the
worker logged a traceback, for a file that merely wanted its password typed.

A wrong password is the same story twice over. zipfile says "Bad password" when
the check byte catches it, and roughly one time in 256 that byte passes by
chance, the bytes reach the decompressor and zlib rejects them instead. Both
escaped.

AES is told apart on purpose. Python's zipfile cannot read it with any
password, so reporting "the password did not open it" would send somebody off
to check a password that was right all along.
"""

from __future__ import annotations

import subprocess
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from app.services.archives import extract_members
from app.services.ingest import IngestError
from tests.test_api_analytics import _stata_bytes

FRAME = pd.DataFrame({"pid": [1.0, 2.0], "region": ["North", "South"]})
PASSWORD = "fieldwork-2026"


@pytest.fixture(scope="module")
def locked(tmp_path_factory) -> Path:
    """A real locked archive, made by zip rather than by hand."""
    if subprocess.run(["which", "zip"], capture_output=True).returncode != 0:
        pytest.skip("the zip command is not available here")
    folder = tmp_path_factory.mktemp("locked")
    (folder / "persons.dta").write_bytes(_stata_bytes(FRAME))
    archive = folder / "export.zip"
    made = subprocess.run(
        ["zip", "-q", "-P", PASSWORD, archive.name, "persons.dta"],
        cwd=folder,
        capture_output=True,
    )
    assert made.returncode == 0, made.stderr
    return archive


def unpack(archive: Path, password: str | None = None):
    return extract_members(archive, Path(tempfile.mkdtemp()), password)


def test_a_locked_archive_says_so_rather_than_failing(locked):
    with pytest.raises(IngestError) as raised:
        unpack(locked)

    said = str(raised.value)
    assert "password protected" in said
    assert "export.zip" in said


def test_the_right_password_opens_it(locked):
    members = unpack(locked, PASSWORD)

    assert [one.name for one in members] == ["persons.dta"]
    assert members[0].path.exists()


def test_a_wrong_password_says_which_thing_went_wrong(locked):
    with pytest.raises(IngestError) as raised:
        unpack(locked, "not-the-password")

    assert "did not open" in str(raised.value)


def test_an_unlocked_archive_is_unaffected(tmp_path):
    """The password path must not change anything for the ordinary case."""
    archive = tmp_path / "plain.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("persons.dta", _stata_bytes(FRAME))

    assert [one.name for one in unpack(archive)] == ["persons.dta"]
    # A password nobody needed is simply ignored.
    assert [one.name for one in unpack(archive, "unnecessary")] == ["persons.dta"]


def test_aes_is_told_apart_from_a_wrong_password(tmp_path, monkeypatch):
    """zipfile cannot read AES with any password, so saying "wrong password"
    would send somebody to check one that was right.

    A genuine AES archive needs a library this platform does not carry, so the
    member is marked the way a real one is - encrypted, compression method 99 -
    at the point the code looks at it.
    """
    from app.services import archives

    archive = tmp_path / "aes.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("persons.dta", _stata_bytes(FRAME))

    def as_aes(opened):
        marked = []
        for info in opened.infolist():
            info.flag_bits |= 0x1
            info.compress_type = archives.AES_COMPRESSION
            marked.append(info)
        return marked

    monkeypatch.setattr(archives, "_safe_members", as_aes)

    with pytest.raises(IngestError) as raised:
        extract_members(archive, Path(tempfile.mkdtemp()))

    said = str(raised.value)
    assert "AES" in said
    # And it does not send them off to check a password.
    assert "did not open" not in said


def test_a_locked_member_without_aes_asks_for_the_password(tmp_path, monkeypatch):
    """The other half of the same branch: ordinary zip encryption is openable,
    so it asks rather than refusing outright."""
    from app.services import archives

    archive = tmp_path / "legacy.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("persons.dta", _stata_bytes(FRAME))

    def as_locked(opened):
        marked = []
        for info in opened.infolist():
            info.flag_bits |= 0x1
            marked.append(info)
        return marked

    monkeypatch.setattr(archives, "_safe_members", as_locked)

    with pytest.raises(IngestError) as raised:
        extract_members(archive, Path(tempfile.mkdtemp()))

    assert "password protected" in str(raised.value)


# --- Through the upload, which is where somebody meets it --------------------


def test_the_upload_reports_a_locked_archive_rather_than_failing(
    locked, client, auth_headers
):
    sent = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", locked.read_bytes(), "application/zip")},
    )

    assert sent.status_code == 422, sent.status_code
    assert "password protected" in sent.json()["detail"]


def test_the_upload_takes_the_password(locked, client, auth_headers):
    sent = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", locked.read_bytes(), "application/zip")},
        data={"password": PASSWORD},
    )

    assert sent.status_code == 201, sent.text
    body = sent.json()
    names = [one["name"] for one in body["datasets"]]
    assert "persons" in names
