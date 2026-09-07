"""The ordered record of everything run against a dataset.

A dataset carries what was done to it, so that a newer export can be dropped on
top of it without losing the work: a generated variable is not in the file, and
neither is a recode written in R, so both would vanish on exactly the upload
this platform exists to make routine.

There are two languages now, and the order between them is the whole point. A
Stata `gen` followed by an R script that reads the generated column, replayed
the other way round, fails; replayed in order, it does not. So both go into one
list in the order they were run, and this module is what reads that list.

An entry is a plain string where it always was - a Stata command - or a dict
carrying its language. Old datasets are therefore already correct, without a
migration: every entry they hold is Stata, which is what a bare string means.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Dataset
from app.services import rscript, stata

logger = get_logger(__name__)

STATA = "stata"
R = "r"


def entries(dataset: Dataset) -> list[dict[str, str]]:
    """What has been run, in the order it will be replayed."""
    out: list[dict[str, str]] = []
    for item in (dataset.meta or {}).get("commands") or []:
        if isinstance(item, str):
            out.append({"kind": STATA, "text": item})
        elif isinstance(item, dict) and item.get("text"):
            out.append({"kind": str(item.get("kind") or STATA), "text": str(item["text"])})
    return out


def forget(dataset: Dataset) -> None:
    meta = dict(dataset.meta or {})
    meta["commands"] = []
    dataset.meta = meta


def replay(db: Session, dataset: Dataset) -> list[str]:
    """Re-run everything recorded, in order, after a newer export replaced the data.

    Failures are reported rather than raised, as they always were: the import
    has already happened, and a step that no longer applies - it named a
    variable this export does not have - is a note beside the data rather than
    a 500 on the upload.

    An R script that cannot be replayed because R has since been switched off
    reports that plainly, which is the case worth being clear about: the data
    came in, and something that used to be applied to it no longer is.
    """
    problems: list[str] = []
    for entry in entries(dataset):
        kind, text = entry["kind"], entry["text"]
        try:
            if kind == R:
                rscript.run_script(db, dataset, text, record_it=False)
            else:
                stata.run(db, dataset, text, record_it=False)
        except Exception as exc:  # noqa: BLE001 - a replay must never fail the
            # import that has already happened.
            logger.exception("Replaying %s step failed", kind)
            problems.append(f"'{_short(text)}' could not be re-applied: {exc}")
    return problems


def _short(text: str, limit: int = 80) -> str:
    """A step named in a warning. An R script is a page; its first line will do."""
    first = text.strip().splitlines()[0] if text.strip() else text
    return first if len(first) <= limit else first[:limit] + "..."
