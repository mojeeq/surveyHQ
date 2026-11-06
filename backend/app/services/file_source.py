"""A folder of exports, read as a source of data.

Not every survey office can have an API user. Creating one is an
administrator's privilege on the survey server, and the answer is sometimes
no - which leaves a monitoring platform that can do nothing with a file the
same people download by hand every morning.

So a connection can be a directory instead of a server. Somebody puts an
export in it - by hand, by `rsync`, by a cloud drive syncing the folder the
survey server was told to push to - and the import that follows is the one a
server connection runs: the same unpacking, the same one dataset per roster
level, the same replacement in place that keeps charts and indicators
working.

Two things make that safe and quiet rather than clever:

- the directory has to sit inside a configured root, so a connection cannot
  be pointed at `/etc` or at another project's storage; and
- a file is left alone until it has stopped changing, because a large export
  arrives under its final name long before it is whole.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.services.ingest import SUPPORTED_EXTENSIONS

logger = get_logger(__name__)

#: What a folder connection will pick up. An export from a survey server is a
#: zip of one file per roster level; the rest are what somebody saves out of a
#: spreadsheet or a statistics package.
READABLE_EXTENSIONS = {".zip"} | SUPPORTED_EXTENSIONS


class FolderError(RuntimeError):
    """A folder that cannot be read, said in a sentence."""


@dataclass(frozen=True)
class FoundFile:
    """One file in the folder, as the importer sees it."""

    path: Path
    name: str
    size: int
    modified: dt.datetime
    #: False while the file is still being written into place.
    settled: bool

    @property
    def digest(self) -> str:
        return digest_of(self.path)


def roots() -> list[Path]:
    return settings.import_root_paths


def resolve(folder: str) -> Path:
    """The folder as a real path, or a complaint naming what is wrong.

    Resolved before it is judged, so a path that climbs out with `..`, or a
    symlink pointing somewhere else entirely, is measured by where it actually
    lands rather than by how it is spelled.
    """
    typed = (folder or "").strip()
    if not typed:
        raise FolderError("No folder given")
    try:
        here = Path(typed).resolve()
    except (OSError, RuntimeError) as exc:  # pragma: no cover - exotic paths
        raise FolderError(f"That folder cannot be read: {exc}") from None

    allowed = roots()
    if not allowed:
        raise FolderError(
            "No import folder is configured on this server. An administrator "
            "sets IMPORT_ROOTS to the directory exports are staged in."
        )
    if not any(here == root or root in here.parents for root in allowed):
        where = ", ".join(str(root) for root in allowed)
        raise FolderError(
            f"{here} is outside the folders this server will import from ({where})"
        )
    if not here.exists():
        raise FolderError(f"{here} does not exist on the server")
    if not here.is_dir():
        raise FolderError(f"{here} is a file, not a folder")
    return here


def digest_of(path: Path, chunk: int = 1024 * 1024) -> str:
    """A file's content, as a hash, read a megabyte at a time.

    What makes a file "the one already imported" is its content, not its name:
    a nightly export is called the same thing every night, and the only thing
    that says this morning's is new is that it reads differently.
    """
    hashed = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            hashed.update(block)
    return hashed.hexdigest()


def inside_a_root(path: Path) -> bool:
    """Whether a path, once followed, is still somewhere this server may read."""
    try:
        real = path.resolve()
    except (OSError, RuntimeError):  # pragma: no cover - a link that loops
        return False
    return any(real == root or root in real.parents for root in roots())


def listing(folder: Path, now: dt.datetime | None = None) -> list[FoundFile]:
    """Every file in the folder this platform could read, oldest first.

    Oldest first because a folder holding three rounds of an export should
    import them in the order they were produced: the last one in is the one
    whose rows stand at the end.

    Not recursive. A folder connection is pointed at the directory the files
    land in, and walking into whatever else is under it - a backup, an
    unrelated project's archive - is a surprise nobody asked for.

    Every entry is followed before it is accepted. The fence around the folder
    is no fence at all if a link inside it may point out: a `leak.csv` in the
    staging folder aimed at another project's export would otherwise be
    imported as a dataset, which is the one thing naming a root was for.
    """
    moment = now or dt.datetime.now(dt.UTC)
    settle = dt.timedelta(seconds=max(0, settings.import_settle_seconds))
    found: list[FoundFile] = []
    for entry in sorted(folder.iterdir()):
        if not entry.is_file() or entry.name.startswith("."):
            continue
        if entry.suffix.lower() not in READABLE_EXTENSIONS:
            continue
        if not inside_a_root(entry):
            logger.warning(
                "Ignoring %s: it leads outside the folders this server reads from", entry
            )
            continue
        try:
            stat = entry.stat()
        except OSError:  # pragma: no cover - vanished between listing and stat
            continue
        modified = dt.datetime.fromtimestamp(stat.st_mtime, dt.UTC)
        found.append(
            FoundFile(
                path=entry,
                name=entry.name,
                size=stat.st_size,
                modified=modified,
                settled=(moment - modified) >= settle,
            )
        )
    return sorted(found, key=lambda one: (one.modified, one.name))
