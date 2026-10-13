"""A folder read as a source of data, and the fence around it.

A folder connection names a directory on the server and imports what appears
in it. Two things have to be right or it is a liability rather than a feature.

The fence: anyone who may add a connection could otherwise name any directory
the container can reach - /etc, the storage the platform keeps its own data
in, another project's archives - and have its contents imported into a dataset
they can read. So the folder has to sit inside a configured root, measured by
where the path actually lands rather than by how it is spelled.

The wait: a forty megabyte export copied in over a network link exists, under
its final name, long before it is whole. Reading it at that moment imports
half a survey, which is worse than importing none.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from app.core.config import settings
from app.services import file_source


@pytest.fixture
def incoming(tmp_path, monkeypatch) -> Path:
    """A staging folder this server is configured to read."""
    root = tmp_path / "incoming"
    root.mkdir()
    monkeypatch.setattr(settings, "import_roots", str(root))
    monkeypatch.setattr(settings, "import_settle_seconds", 60)
    return root


def aged(path: Path, seconds: int) -> Path:
    """The same file, last written `seconds` ago."""
    when = dt.datetime.now(dt.UTC).timestamp() - seconds
    os.utime(path, (when, when))
    return path


# --- The fence ---------------------------------------------------------------


def test_a_folder_inside_the_root_is_read(incoming):
    assert file_source.resolve(str(incoming)) == incoming.resolve()


def test_a_folder_under_the_root_is_read(incoming):
    """A connection per round of fieldwork is a folder per round."""
    inner = incoming / "round-2"
    inner.mkdir()

    assert file_source.resolve(str(inner)) == inner.resolve()


def test_somewhere_else_entirely_is_refused(incoming, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()

    with pytest.raises(file_source.FolderError) as raised:
        file_source.resolve(str(other))

    assert "outside the folders this server will import from" in str(raised.value)


def test_climbing_out_with_dots_is_refused(incoming):
    """Judged by where it lands, not by how it is written."""
    with pytest.raises(file_source.FolderError):
        file_source.resolve(f"{incoming}/../../etc")


def test_a_symlink_pointing_out_is_refused(incoming, tmp_path):
    """The link is inside the root; what it points at is not, and that is what
    would be read."""
    outside = tmp_path / "secrets"
    outside.mkdir()
    (outside / "passwd.csv").write_text("a,b\n1,2\n")
    link = incoming / "shortcut"
    link.symlink_to(outside)

    with pytest.raises(file_source.FolderError):
        file_source.resolve(str(link))


def test_a_folder_that_is_not_there_says_so(incoming):
    with pytest.raises(file_source.FolderError) as raised:
        file_source.resolve(str(incoming / "nope"))

    assert "does not exist" in str(raised.value)


def test_a_file_is_not_a_folder(incoming):
    one = incoming / "export.zip"
    one.write_bytes(b"PK")

    with pytest.raises(file_source.FolderError) as raised:
        file_source.resolve(str(one))

    assert "is a file, not a folder" in str(raised.value)


def test_nothing_is_readable_where_no_root_is_configured(incoming, monkeypatch):
    """A deployment that never set one imports from nowhere, rather than from
    everywhere."""
    monkeypatch.setattr(settings, "import_roots", "")

    with pytest.raises(file_source.FolderError) as raised:
        file_source.resolve(str(incoming))

    assert "No import folder is configured" in str(raised.value)


def test_an_empty_path_is_refused(incoming):
    with pytest.raises(file_source.FolderError):
        file_source.resolve("   ")


# --- What it finds -----------------------------------------------------------


def staged(folder: Path, name: str, seconds: int = 3600, body: bytes = b"x") -> Path:
    """A file that landed `seconds` ago."""
    path = folder / name
    path.write_bytes(body)
    return aged(path, seconds)


def test_it_reads_the_files_a_survey_arrives_as(incoming):
    for name in ("export.zip", "roster.dta", "interviews.tab", "households.csv"):
        staged(incoming, name)

    assert {one.name for one in file_source.listing(incoming)} == {
        "export.zip",
        "roster.dta",
        "interviews.tab",
        "households.csv",
    }


def test_it_leaves_alone_what_it_cannot_read(incoming):
    for name in ("notes.pdf", "export.zip.part", "readme.md"):
        staged(incoming, name)

    assert file_source.listing(incoming) == []


def test_a_hidden_file_is_not_a_delivery(incoming):
    """A half-synced file from a cloud drive is often a dotfile."""
    staged(incoming, ".export.zip")

    assert file_source.listing(incoming) == []


def test_it_does_not_walk_into_what_is_under_the_folder(incoming):
    """The folder is where the files land. What else is under it - a backup, a
    different project's archive - was not offered."""
    nested = incoming / "archive"
    nested.mkdir()
    staged(nested, "old.zip")

    assert file_source.listing(incoming) == []


def test_the_oldest_is_imported_first(incoming):
    for name, age in (("third.zip", 60), ("first.zip", 3600), ("second.zip", 600)):
        staged(incoming, name, age)

    assert [one.name for one in file_source.listing(incoming)] == [
        "first.zip",
        "second.zip",
        "third.zip",
    ]


def test_a_file_still_being_written_is_not_settled(incoming):
    """Not skipped forever - skipped this time round, read the next."""
    staged(incoming, "arriving.zip", seconds=5)
    staged(incoming, "arrived.zip", seconds=3600)

    settled = {one.name: one.settled for one in file_source.listing(incoming)}

    assert settled == {"arriving.zip": False, "arrived.zip": True}


def test_waiting_can_be_switched_off(incoming, monkeypatch):
    """An office copying files onto the machine itself has nothing to wait for."""
    monkeypatch.setattr(settings, "import_settle_seconds", 0)
    path = incoming / "just-now.zip"
    path.write_bytes(b"x")

    assert file_source.listing(incoming)[0].settled is True


# --- Which file is the one already imported ----------------------------------


def test_the_same_content_reads_as_the_same_file(incoming):
    one = incoming / "monday.zip"
    one.write_bytes(b"the same export")
    two = incoming / "monday-copy.zip"
    two.write_bytes(b"the same export")

    assert file_source.digest_of(one) == file_source.digest_of(two)


def test_tomorrows_export_under_the_same_name_is_a_different_file(incoming):
    """Which is the whole point: a nightly export is called the same thing
    every night, and only its content says it is new."""
    path = incoming / "nightly.zip"
    path.write_bytes(b"monday")
    monday = file_source.digest_of(path)
    path.write_bytes(b"tuesday")

    assert file_source.digest_of(path) != monday


def test_a_file_too_big_to_hold_is_still_read(incoming):
    """Read a megabyte at a time, so a four gigabyte census export is hashed
    without being loaded."""
    path = incoming / "big.zip"
    path.write_bytes(b"0" * (3 * 1024 * 1024 + 7))

    assert len(file_source.digest_of(path, chunk=1024)) == 64


def test_a_link_inside_the_folder_pointing_out_is_not_read(incoming, tmp_path):
    """The fence is around what is read, not only around what is named.

    A folder connection reads a directory somebody else fills. If a link in it
    could point at another project's export, or at anything else the container
    can reach, the root would be a fence with a door in it.
    """
    outside = tmp_path / "another-project"
    outside.mkdir()
    secret = outside / "export.csv"
    secret.write_text("a,b\n1,2\n")
    link = incoming / "leak.csv"
    link.symlink_to(secret)
    aged(link, 3600)
    staged(incoming, "ours.csv")

    assert [one.name for one in file_source.listing(incoming)] == ["ours.csv"]


def test_a_link_inside_the_folder_pointing_inside_it_is_read(incoming):
    """Only where it leads matters. A link to a file in the same folder is a
    file in the same folder."""
    real = staged(incoming, "export.zip")
    link = incoming / "latest.zip"
    link.symlink_to(real)
    aged(link, 3600)

    assert {one.name for one in file_source.listing(incoming)} == {
        "export.zip",
        "latest.zip",
    }
