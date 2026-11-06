"""A large upload, sent in pieces and put back together before it is read.

A census export is gigabytes, and plenty of the paths between a browser and
this server refuse one request that size: Cloudflare stops at 100 MB on its
free plan and its Pro plan, and no setting on the server reaches it. So a
large file is sent as pieces of a size every proxy accepts, kept here until the
last one arrives, joined, and then handed to the ordinary upload as if it had
come in whole - the same checks, the same queue, the same import.

Each upload is a directory named by a random id, holding the pieces and a note
of who started it, what the file is called and how big it is. An id belongs to
the person who started it; nobody else can add to it or use it. Anything left
unfinished is cleared a day later by `prune`.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.config import settings

# Under Cloudflare's 100 MB with room to spare, and large enough that a 20 GB
# export is four hundred requests rather than four thousand.
CHUNK_BYTES = 50 * 1024 * 1024

# An upload nobody finished, after which its pieces are removed.
ABANDONED_AFTER_SECONDS = 24 * 60 * 60

_ID = re.compile(r"^[0-9a-f]{32}$")
_ASSEMBLED = "file"


class StagingError(ValueError):
    """The upload cannot be continued as asked."""


@dataclass
class Staged:
    """A finished upload, ready to be imported."""

    id: str
    filename: str
    size: int
    path: Path


def root() -> Path:
    return settings.uploads_path / "staged"


def _directory(upload_id: str) -> Path:
    # The id becomes a path, so it is held to exactly what start() makes.
    if not _ID.match(upload_id or ""):
        raise StagingError("No such upload")
    return root() / upload_id


def _note(upload_id: str, user_id: str) -> dict:
    """What start() wrote down, if this person started it."""
    try:
        note = json.loads((_directory(upload_id) / "upload.json").read_text())
    except (OSError, ValueError) as exc:
        raise StagingError("No such upload") from exc
    # Not "not yours": an id somebody else holds is not confirmed to exist.
    if note.get("user_id") != user_id:
        raise StagingError("No such upload")
    return note


def check(upload_id: str, user_id: str) -> None:
    """Raise unless this upload exists and this person started it."""
    _note(upload_id, user_id)


def pieces(size: int) -> int:
    """How many pieces a file of this size is sent as. An empty file is one."""
    return max(1, -(-size // CHUNK_BYTES))


def start(user_id: str, filename: str, size: int) -> str:
    """Make room for an upload and say what it is called."""
    if size < 0:
        raise StagingError("A file cannot be smaller than nothing")
    upload_id = uuid4().hex
    directory = _directory(upload_id)
    directory.mkdir(parents=True)
    (directory / "upload.json").write_text(
        json.dumps(
            {
                "user_id": user_id,
                "filename": Path(filename).name or "upload.dat",
                "size": int(size),
                "started": time.time(),
            }
        )
    )
    return upload_id


async def write_piece(
    upload_id: str, user_id: str, index: int, body: AsyncIterator[bytes]
) -> int:
    """Store one piece as it streams in, and say how many bytes it held.

    Written beside its final name and moved into place, so a piece cut off
    halfway is not mistaken for a whole one; sending it again replaces it.
    """
    note = _note(upload_id, user_id)
    if not 0 <= index < pieces(note["size"]):
        raise StagingError(f"This upload has no piece {index}")
    directory = _directory(upload_id)
    partial = directory / f"{index:06d}.partial"
    received = 0
    with open(partial, "wb") as handle:
        async for block in body:
            received += len(block)
            if received > CHUNK_BYTES:
                handle.close()
                partial.unlink(missing_ok=True)
                raise StagingError(f"A piece holds at most {CHUNK_BYTES // (1024 * 1024)} MB")
            handle.write(block)
    partial.replace(directory / f"{index:06d}.piece")
    return received


def complete(upload_id: str, user_id: str) -> Staged:
    """Join the pieces into the file, once every one of them is here."""
    note = _note(upload_id, user_id)
    directory = _directory(upload_id)
    expected = [directory / f"{index:06d}.piece" for index in range(pieces(note["size"]))]
    missing = [index for index, piece in enumerate(expected) if not piece.exists()]
    if missing:
        raise StagingError(
            f"{len(missing)} piece(s) of {note['filename']} have not arrived, "
            f"the first being piece {missing[0]}"
        )
    arrived = sum(piece.stat().st_size for piece in expected)
    if arrived != note["size"]:
        raise StagingError(
            f"{note['filename']} should be {note['size']:,} bytes and "
            f"{arrived:,} arrived. Send it again."
        )
    assembled = directory / _ASSEMBLED
    with open(assembled, "wb") as out:
        for piece in expected:
            with open(piece, "rb") as source:
                shutil.copyfileobj(source, out, 1024 * 1024)
            piece.unlink()
    return Staged(upload_id, note["filename"], note["size"], assembled)


def take(upload_ids: list[str], user_id: str) -> list[Staged]:
    """The finished uploads named, in the order named, for the import to use."""
    found: list[Staged] = []
    for upload_id in upload_ids:
        note = _note(str(upload_id), user_id)
        assembled = _directory(str(upload_id)) / _ASSEMBLED
        if not assembled.exists():
            raise StagingError(f"{note['filename']} has not finished uploading")
        found.append(Staged(str(upload_id), note["filename"], note["size"], assembled))
    return found


def discard(upload_id: str) -> None:
    shutil.rmtree(_directory(upload_id), ignore_errors=True)


def prune(now: float | None = None) -> int:
    """Remove uploads nobody finished or used within a day."""
    now = time.time() if now is None else now
    removed = 0
    if not root().exists():
        return 0
    for directory in root().iterdir():
        try:
            started = json.loads((directory / "upload.json").read_text())["started"]
        except (OSError, ValueError, KeyError):
            started = directory.stat().st_mtime
        if now - started > ABANDONED_AFTER_SECONDS:
            shutil.rmtree(directory, ignore_errors=True)
            removed += 1
    return removed
