"""Reading survey data out of ZIP archives.

A Survey Solutions export archive holds one file per roster level, not one file
per round. A labour force survey export contains, say:

    VN_LF2024.dta        the interview level
    R_demographics.dta   one row per person in the household
    abroad_roster.dta    one row per person living abroad

Those are three different tables and appending them together would be nonsense.
So an archive yields one dataset per member file, keyed by that file's name.

Rounds arrive as separate archives with the same member names, which is what
makes the name the right key: the September and October exports both contain
VN_LF2024.dta, and those two do belong appended together.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.core.logging import get_logger
from app.services.ingest import SUPPORTED_EXTENSIONS, IngestError, read_source

logger = get_logger(__name__)

# Written onto every combined dataset so a row can be traced to its file.
SOURCE_COLUMN = "source_file"

# Survey Solutions writes these beside the interview data; they are not the
# subject of analysis and would otherwise be mistaken for extra rounds.
SYSTEM_FILE_STEMS = {
    "interview__actions",
    "interview__errors",
    "interview__comments",
    "interview__diagnostics",
    "assignment__actions",
}

# .txt counts as a data format here, so a Survey Solutions export's own readme
# would otherwise be read as tabular and appended as though it were a round.
IGNORED_STEM_FRAGMENTS = ("readme", "codebook")

MAX_MEMBERS = 200


@dataclass
class ExtractedMember:
    """One data file found inside an archive."""

    name: str
    path: Path
    frame: pd.DataFrame
    variable_labels: dict[str, str] = field(default_factory=dict)
    value_labels: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(str(c) for c in self.frame.columns)


@dataclass
class CombineResult:
    frame: pd.DataFrame
    variable_labels: dict[str, str]
    value_labels: dict[str, dict[str, str]]
    members: list[str]
    warnings: list[str] = field(default_factory=list)


def is_archive(path: Path) -> bool:
    return path.suffix.lower() == ".zip"


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Data files worth reading, ignoring directories and system exports.

    Member names are never joined onto a filesystem path - only the basename is
    used - so an archive cannot write outside the directory it is extracted to.
    """
    members: list[zipfile.ZipInfo] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = Path(info.filename).name
        if not name or name.startswith("."):
            continue
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            continue
        stem = Path(name).stem.lower()
        if stem in SYSTEM_FILE_STEMS:
            continue
        if any(fragment in stem for fragment in IGNORED_STEM_FRAGMENTS):
            continue
        members.append(info)
    return members


def extract_members(archive_path: Path, destination: Path) -> list[ExtractedMember]:
    """Unpack an archive and read every data file inside it."""
    destination.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise IngestError(f"'{archive_path.name}' is not a readable zip archive.") from exc

    extracted: list[ExtractedMember] = []
    with archive:
        members = _safe_members(archive)
        if not members:
            raise IngestError(
                "The archive contains no data files. Expected one or more of: "
                + ", ".join(sorted(SUPPORTED_EXTENSIONS))
            )
        if len(members) > MAX_MEMBERS:
            raise IngestError(
                f"The archive holds {len(members)} data files, more than the "
                f"{MAX_MEMBERS} this platform will read at once."
            )
        for info in members:
            name = Path(info.filename).name
            target = destination / name
            with archive.open(info) as source, open(target, "wb") as handle:
                handle.write(source.read())
            try:
                frame, variable_labels, value_labels = read_source(target)
            except IngestError as exc:
                logger.warning("Skipping %s inside the archive: %s", name, exc)
                continue
            extracted.append(
                ExtractedMember(
                    name=name,
                    path=target,
                    frame=frame,
                    variable_labels=variable_labels,
                    value_labels=value_labels,
                )
            )

    if not extracted:
        raise IngestError("None of the files inside the archive could be read.")
    return extracted


def combine(members: list[ExtractedMember], strict: bool = False) -> CombineResult:
    """Append several files into one frame.

    Rounds of the same survey usually share a schema but not always exactly: a
    later round may add a question. Appending on the union of columns keeps every
    row, leaving a variable blank where a round did not ask it - which is the
    honest representation, and the same thing Stata's append does. Pass
    strict=True to refuse anything but an exact column match.
    """
    if not members:
        raise IngestError("There is nothing to combine.")

    warnings: list[str] = []
    first = set(members[0].columns)
    frames: list[pd.DataFrame] = []

    for member in members:
        columns = set(member.columns)
        if columns != first:
            missing = sorted(first - columns)
            extra = sorted(columns - first)
            if strict:
                raise IngestError(
                    f"'{member.name}' does not match the first file's columns. "
                    + (f"Missing: {', '.join(missing[:5])}. " if missing else "")
                    + (f"Unexpected: {', '.join(extra[:5])}." if extra else "")
                )
            if missing:
                warnings.append(
                    f"'{member.name}' does not contain {len(missing)} variable(s) "
                    f"present in '{members[0].name}', left blank: "
                    + ", ".join(missing[:5])
                    + ("..." if len(missing) > 5 else "")
                )
            if extra:
                warnings.append(
                    f"'{member.name}' adds {len(extra)} variable(s) not in "
                    f"'{members[0].name}': "
                    + ", ".join(extra[:5])
                    + ("..." if len(extra) > 5 else "")
                )
        frame = member.frame.copy()
        frame[SOURCE_COLUMN] = member.name
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True, sort=False)

    # Later files win only where earlier ones said nothing, so the first file's
    # labels are the ones that stand.
    variable_labels: dict[str, str] = {}
    value_labels: dict[str, dict[str, str]] = {}
    for member in members:
        for key, value in member.variable_labels.items():
            variable_labels.setdefault(key, value)
        for key, value in member.value_labels.items():
            value_labels.setdefault(key, value)
    variable_labels.setdefault(SOURCE_COLUMN, "File this row was imported from")

    return CombineResult(
        frame=combined,
        variable_labels=variable_labels,
        value_labels=value_labels,
        members=[m.name for m in members],
        warnings=warnings,
    )


def group_by_schema(members: list[ExtractedMember]) -> list[list[ExtractedMember]]:
    """Group files that share a column set, largest group first.

    Only used by the "combine everything" escape hatch now that each member
    becomes its own dataset. Kept for archives that really do hold several
    rounds of one table rather than several levels of one round.
    """
    groups: dict[tuple[str, ...], list[ExtractedMember]] = {}
    for member in members:
        groups.setdefault(tuple(sorted(member.columns)), []).append(member)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0].name))


def member_key(name: str) -> str:
    """The name a member file is matched by across archives.

    The stem, lowercased: September's VN_LF2024.dta and October's must resolve
    to the same key or the two rounds never meet. Extension is dropped so an
    export that switches format between rounds still matches.
    """
    return Path(name).stem.lower()


def by_member_name(members: list[ExtractedMember]) -> dict[str, ExtractedMember]:
    """One member per name, which is how an archive's levels are told apart.

    Names are unique inside a zip, so a collision here means two files differing
    only by extension; the first wins and the second is reported by the caller.
    """
    grouped: dict[str, ExtractedMember] = {}
    for member in members:
        grouped.setdefault(member_key(member.name), member)
    return grouped
