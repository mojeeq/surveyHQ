"""A small Stata command line over a dataset.

Anyone who has prepared survey data has the idioms in their fingers - gen,
replace, egen, label, drop if - and reaching for a spreadsheet to add one
derived column is a poor substitute. This runs a useful subset of them against
the dataset in place.

Two things make it fit a live monitoring tool rather than being a one-off edit.
Commands are recorded on the dataset, and replayed after a newer export
replaces it: a variable somebody generated is not in the file, so without that
it would vanish on exactly the upload this platform exists to make routine, and
take every chart built on it. And nothing is passed through to the database as
text - see stata_expr - so what runs is only ever what was recognised.

The record lives on the dataset itself, in meta["commands"], as an ordered list
of the command text. Order is the whole of it: a `gen` that a later `replace`
depends on has to run first, so the list is replayed front to back and never
sorted or deduplicated.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Dataset, DatasetSource
from app.services.datasets import (
    _apply_ingest,
    create_dataset_record,
    dataset_directory,
    dataset_is_queryable,
)
from app.services.ingest import ingest_frame
from app.services.query_engine import (
    DatasetContext,
    _quote_path,
    quote_ident,
    run_sql,
)
from app.services.stata_expr import ExpressionError, translate
from app.services.stata_frame import Frame, FrameError, Workspace, load, write

logger = get_logger(__name__)

# The ordering column added while a command runs. Underscored so it cannot
# collide with a variable name, which cannot start with one.
ROW_ORDER = "__row_order"


class CommandError(ValueError):
    """The command could not be understood, or cannot be run."""


@dataclass
class CommandResult:
    command: str
    message: str
    changed_rows: int = 0
    variables_added: list[str] = field(default_factory=list)
    variables_removed: list[str] = field(default_factory=list)
    # Set when the data itself changed, so the caller knows to re-run merges.
    data_changed: bool = False


# egen name -> the SQL aggregate behind it. Stata's `total` is a sum, and its
# `count` counts the non-missing, which is what SQL's COUNT(column) does.
EGEN_AGGREGATES = {
    "total": "SUM",
    "sum": "SUM",
    "mean": "AVG",
    "count": "COUNT",
    "min": "MIN",
    "max": "MAX",
    "median": "MEDIAN",
    "sd": "STDDEV_SAMP",
}
# These work across the variables of one row rather than down a column.
EGEN_ROWWISE = {"rowtotal", "rowmean", "rowmiss", "rownonmiss", "rowmax", "rowmin"}


@dataclass
class Saved:
    """A dataset a script wrote, and whether the script made it."""

    dataset_id: str
    name: str
    created: bool
    rows: int


@dataclass
class Run:
    """One script, running.

    Everything a command might need: the data in memory, the scratch
    workspace it lives in, and - for `use` and `save`, which are the only two
    that reach past the data in front of them - the project whose datasets can
    be read and written, and the session to do it through.

    `project_id` is None for the dataset command box, which works on one file
    and has no project to look names up in. A `use` there says so rather than
    failing obscurely.
    """

    db: Session
    work: Workspace
    frame: Frame | None = None
    project_id: str | None = None
    saved: list[Saved] = field(default_factory=list)
    # The datasets this project's script made last time. A `save as` may write
    # over one of these, because the script owns what it built and re-running
    # it has to rebuild them; anything else it refuses, so a script cannot
    # quietly take over a dataset somebody else made.
    owns: set[str] = field(default_factory=set)
    # Every dataset this run opened, in the order it opened them. Recorded as
    # it happens rather than parsed out of the text afterwards: parsing would
    # have to resolve names the way `use` does, and would count a line that
    # never ran because the one above it failed.
    read: list[str] = field(default_factory=list)

    @property
    def data(self) -> Frame:
        """The data in memory, or a clear word about there being none."""
        if self.frame is None:
            raise CommandError(
                "There is no data in memory. Start with `use <dataset>`."
            )
        return self.frame


def apply(run: Run, text: str) -> CommandResult:
    """Run one command.

    Most commands never touch a dataset: they read the working copy and write
    the next one, and what reaches disk is decided by `save`. `use` and `save`
    are the exceptions, which is why they are handed the whole run.
    """
    command = text.strip().rstrip(";").strip()
    if not command:
        raise CommandError("Type a command, for example: gen adult = age >= 18")

    verb, _, rest = command.partition(" ")
    # `save as x` and `save, replace` are both the save verb; Stata spells the
    # first with a word and the second with an option, and the partition above
    # would hand "save," on as the verb.
    handler = verbs().get(verb.lower().rstrip(","))
    if handler is None:
        raise CommandError(
            f"'{verb}' is not a command this understands. Available: "
            "use, save, gen, replace, egen, label, rename, drop, keep"
        )
    if verb.lower().endswith(",") and not rest.startswith(","):
        rest = "," + rest

    result = handler(run, rest.strip())
    result.command = command
    return result


def run(db: Session, dataset: Dataset, text: str, record_it: bool = True) -> CommandResult:
    """Run one command against a dataset, and remember it if it changed anything.

    The engine works on a copy in a scratch workspace, so this loads one,
    applies the command and writes the result back - which is the in-place
    behaviour the dataset command box has always had, now expressed in terms
    of the same frame a project script uses.
    """
    # The variable rows are deleted and rebuilt by every command that changes
    # the data, so a second command in the same transaction would otherwise be
    # deciding against the list as it was before the first one ran.
    db.flush()
    db.refresh(dataset)

    if not dataset_is_queryable(dataset):
        raise CommandError(f"'{dataset.name}' has no data to work on yet")

    with Workspace() as work:
        frame = load(work, dataset)
        frame.label_books = dict((dataset.meta or {}).get("label_books") or {})
        result = apply(Run(db=db, work=work, frame=frame), text)
        _store(db, dataset, frame)

    if record_it:
        _remember(dataset, result.command)
    return result


def _store(db: Session, dataset: Dataset, frame: Frame) -> None:
    """Write the frame back over the dataset it was loaded from."""
    import pandas as pd_

    columns, rows = run_sql(f"SELECT * FROM read_parquet({_quote_path(str(frame.path))})")
    _apply_ingest(
        db,
        dataset,
        ingest_frame(
            pd_.DataFrame(rows, columns=columns),
            dict(frame.labels),
            dict(frame.value_labels),
            dataset_directory(dataset.id),
            [],
        ),
    )
    # Label sets outlive the command that defined them, so a later script can
    # apply one without defining it again.
    if frame.label_books:
        meta = dict(dataset.meta or {})
        meta["label_books"] = dict(frame.label_books)
        dataset.meta = meta


@dataclass
class ScriptOutcome:
    """What a project's script did."""

    results: list[CommandResult]
    saved: list[Saved]
    read: list[str] = field(default_factory=list)

    @property
    def created(self) -> list[Saved]:
        return [entry for entry in self.saved if entry.created]

    @property
    def written(self) -> list[str]:
        return list(dict.fromkeys(entry.dataset_id for entry in self.saved))


def run_project_script(
    db: Session, project_id: str, text: str, owns: set[str] | None = None
) -> ScriptOutcome:
    """Run a project's do-file, from the first `use` to the last `save`.

    The whole script shares one workspace and one piece of data in memory, so
    a `use` partway down starts a new section and a `save` puts the section's
    work somewhere. Nothing reaches a dataset except through a save, which is
    what lets a script that goes wrong halfway leave the project as it was.

    A script that saves nothing is not an error - a run that only reports is a
    reasonable thing to write - but the caller is told, because a script meant
    to build something and silently building nothing is the likelier case.
    """
    results: list[CommandResult] = []
    with Workspace() as work:
        run = Run(db=db, work=work, project_id=project_id, owns=set(owns or ()))
        for number, line in enumerate(_lines(text), start=1):
            try:
                results.append(apply(run, line))
            except (CommandError, ExpressionError, FrameError) as exc:
                error = ScriptError(number, line, str(exc), results)
                # What it managed to read before stopping still says which
                # datasets this script stands on, which is what decides
                # whether a later import re-runs it.
                error.read = list(run.read)
                error.saved = list(run.saved)
                raise error from exc
        if not results:
            raise CommandError("There is nothing to run")
        # Inside the workspace: the saves have already read what they needed
        # from it, but the frame's file is only there until this block ends.
        outcome = ScriptOutcome(
            results=results, saved=list(run.saved), read=list(run.read)
        )
    return outcome


def run_script(db: Session, dataset: Dataset, text: str) -> list[CommandResult]:
    """Run several commands in order, as a do-file does.

    Stops at the first one that fails, and says which: the commands that ran
    before it have already changed the data, and carrying on past a failure
    would apply the rest of the script to something the author did not mean.
    What ran stays run, which is also what Stata does.
    """
    results: list[CommandResult] = []
    for number, line in enumerate(_lines(text), start=1):
        try:
            results.append(run(db, dataset, line))
        except (CommandError, ExpressionError) as exc:
            raise ScriptError(number, line, str(exc), results) from exc
    if not results:
        raise CommandError("There is nothing to run")
    return results


class ScriptError(CommandError):
    """One line of a script failed. Carries what ran before it."""

    def __init__(self, line_number: int, line: str, message: str, done: list[CommandResult]):
        super().__init__(f"Line {line_number} ({line}): {message}")
        self.line_number = line_number
        self.line = line
        self.reason = message
        self.done = done
        # Filled in by the runner: what the script had read, and saved, before
        # it stopped. A run that failed halfway still says which datasets it
        # stands on, which is what decides whether a later import re-runs it.
        self.read: list[str] = []
        self.saved: list[Saved] = []


def _lines(text: str) -> list[str]:
    """Split a script into commands, honouring comments and continuations.

    `*` starts a comment line and `//` a trailing one, as in Stata, and `///`
    at the end of a line joins it to the next - which is how a long generate
    gets written without a horizontal scrollbar.
    """
    joined: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("*"):
            continue
        marker = _comment_at(line)
        if marker is not None:
            head = line[:marker].strip()
            # /// continues the line rather than ending it.
            if line[marker:].startswith("///"):
                buffer += " " + head
                continue
            line = head
        if not line:
            continue
        buffer = (buffer + " " + line).strip() if buffer else line
        joined.append(buffer)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def _is_name_char(character: str) -> bool:
    """Part of a variable name. Underscores are, which is the whole point.

    Without this an `if` inside a name was read as the qualifier: `gen copy =
    if_flag` split into an empty expression and a condition of `_flag`.
    """
    return character.isalnum() or character == "_"


def _comment_at(line: str) -> int | None:
    """Where a // comment starts on this line, or None if it holds none.

    Scanned rather than counted. Counting the quotes on the line and calling it
    a comment while the count was even looks right and is not: a line with a
    balanced string has an even count, so the // inside `gen site =
    "https://example.org"` was read as a comment and the command was truncated
    to an unterminated string.
    """
    quoted = False
    index = 0
    while index < len(line):
        character = line[index]
        if character == '"':
            quoted = not quoted
        elif not quoted and line.startswith("//", index):
            return index
        index += 1
    return None


# --- commands ---------------------------------------------------------------


def _generate(run: Run, rest: str) -> CommandResult:
    frame, work = run.data, run.work
    name, expression, condition = _assignment(rest)
    _check_new_name(frame, name)
    ctx = frame.context
    value = translate(expression, set(ctx.variables), quote_ident)
    where = _condition_sql(ctx, condition)
    # Outside the if, the new variable is missing - which is what Stata does.
    column = f"CASE WHEN {where} THEN {value} ELSE NULL END" if where else value
    data = _as_numbers(_select(frame, ctx, extra=[(name, column)]), [name])
    write(work, frame, data)
    return CommandResult(
        command="",
        message=f"Created {name}",
        variables_added=[name],
        changed_rows=len(data),
        data_changed=True,
    )


def _replace(run: Run, rest: str) -> CommandResult:
    frame, work = run.data, run.work
    name, expression, condition = _assignment(rest)
    ctx = frame.context
    if name not in ctx.variables:
        raise CommandError(f"'{name}' is not a variable in the data. Use gen to create it.")
    value = translate(expression, set(ctx.variables), quote_ident)
    where = _condition_sql(ctx, condition)
    column = f"CASE WHEN {where} THEN {value} ELSE {quote_ident(name)} END" if where else value

    changed = _count_matching(frame, where) if where else None
    data = _as_numbers(_select(frame, ctx, replace={name: column}), [name])
    write(work, frame, data)
    affected = changed if changed is not None else len(data)
    return CommandResult(
        command="",
        message=f"Replaced {name} in {affected:,} row(s)",
        changed_rows=affected,
        data_changed=True,
    )


def _egen(run: Run, rest: str) -> CommandResult:
    """egen new = fn(args) [, by(v1 v2)] - the aggregate and row-wise forms."""
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    name, _, call = (part.strip() for part in body.partition("="))
    if not name or not call:
        raise CommandError('egen needs a name and a function, e.g. egen n = count(age), by(region)')
    _check_new_name(frame, name)

    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)$", call.strip(), re.DOTALL)
    if match is None:
        raise CommandError(f"'{call}' is not a function call egen understands")
    function, arguments = match.group(1).lower(), match.group(2).strip()

    ctx = frame.context
    by = _by_variables(ctx, options)

    if function in EGEN_ROWWISE:
        column = _rowwise(ctx, function, arguments)
    elif function == "group":
        columns = _variable_list(ctx, arguments or "")
        if not columns:
            raise CommandError("egen group() needs at least one variable")
        ordering = ", ".join(quote_ident(c) for c in columns)
        column = f"DENSE_RANK() OVER (ORDER BY {ordering})"
    elif function == "tag":
        columns = _variable_list(ctx, arguments or "")
        if not columns:
            raise CommandError("egen tag() needs at least one variable")
        partition = ", ".join(quote_ident(c) for c in columns)
        column = (
            f"CASE WHEN ROW_NUMBER() OVER (PARTITION BY {partition}) = 1 THEN 1 ELSE 0 END"
        )
    elif function in EGEN_AGGREGATES:
        if not arguments:
            raise CommandError(f"egen {function}() needs an expression")
        inner = translate(arguments, set(ctx.variables), quote_ident)
        over = f" OVER (PARTITION BY {', '.join(quote_ident(v) for v in by)})" if by else " OVER ()"
        column = f"{EGEN_AGGREGATES[function]}({inner}){over}"
    else:
        allowed = sorted(set(EGEN_AGGREGATES) | EGEN_ROWWISE | {"group", "tag"})
        raise CommandError(f"egen has no '{function}'. Available: {', '.join(allowed)}")

    data = _as_numbers(_select(frame, ctx, extra=[(name, column)]), [name])
    write(work, frame, data)
    return CommandResult(
        command="",
        message=f"Created {name}" + (f" within {', '.join(by)}" if by else ""),
        variables_added=[name],
        changed_rows=len(data),
        data_changed=True,
    )


def _label(run: Run, rest: str) -> CommandResult:
    """label variable / label define / label values - names, not data.

    These change the frame's own labels rather than any dataset's. They are
    written out by whatever `save` comes next, which is what makes a script
    that labels and then saves under a new name leave the original's labels
    alone.
    """
    # No workspace: nothing here writes a new copy of the data.
    frame = run.data
    kind, _, body = rest.partition(" ")
    kind, body = kind.lower(), body.strip()

    if kind in ("variable", "var", "v"):
        name, _, text = body.partition(" ")
        info = frame.info(name)
        frame.labels[info.name] = _unquote(text.strip())
        return CommandResult(command="", message=f"Labelled {info.name}")

    if kind in ("define", "def"):
        book, pairs = _label_definition(body)
        frame.label_books[book] = pairs
        return CommandResult(
            command="", message=f"Defined label set '{book}' with {len(pairs)} value(s)"
        )

    if kind in ("values", "val", "value"):
        name, _, book = body.partition(" ")
        book = book.strip()
        info = frame.info(name)
        if book and book not in frame.label_books:
            raise CommandError(
                f"No label set called '{book}'. Define it first: "
                f'label define {book} 1 "Yes" 2 "No"'
            )
        pairs = dict(frame.label_books.get(book) or {}) if book else {}
        if pairs:
            frame.value_labels[info.name] = pairs
        else:
            frame.value_labels.pop(info.name, None)
        return CommandResult(
            command="",
            message=(
                f"Applied '{book}' to {info.name}"
                if book
                else f"Cleared labels on {info.name}"
            ),
        )

    raise CommandError(
        "label takes variable, define or values, e.g. label variable age \"Age in years\""
    )


def _rename(run: Run, rest: str) -> CommandResult:
    frame, work = run.data, run.work
    parts = rest.split()
    if len(parts) != 2:
        raise CommandError("rename takes the old name and the new one: rename q1 age")
    old, new = parts
    info = frame.info(old)
    _check_new_name(frame, new)

    ctx = frame.context
    was = info.name
    data = _select(frame, ctx, rename={was: new})
    write(work, frame, data, renamed={was: new})
    return CommandResult(
        command="",
        message=f"Renamed {was} to {new}",
        variables_added=[new],
        variables_removed=[was],
        data_changed=True,
    )


def _drop(run: Run, rest: str) -> CommandResult:
    frame, work = run.data, run.work
    ctx = frame.context
    if rest.lower().startswith("if "):
        where = _condition_sql(ctx, rest[3:].strip())
        before = frame.rows
        data = _select(frame, ctx, where=f"NOT ({where}) OR ({where}) IS NULL")
        write(work, frame, data)
        return CommandResult(
            command="",
            message=f"Dropped {before - len(data):,} row(s)",
            changed_rows=before - len(data),
            data_changed=True,
        )

    names = _variable_list(ctx, rest)
    if not names:
        raise CommandError("drop needs variables, or an if condition")
    remaining = [v for v in ctx.variables if v not in names]
    if not remaining:
        raise CommandError("That would drop every variable in the data")
    data = _select(frame, ctx, only=remaining)
    write(work, frame, data)
    return CommandResult(
        command="",
        message=f"Dropped {', '.join(names)}",
        variables_removed=names,
        data_changed=True,
    )


def _keep(run: Run, rest: str) -> CommandResult:
    frame, work = run.data, run.work
    ctx = frame.context
    if rest.lower().startswith("if "):
        where = _condition_sql(ctx, rest[3:].strip())
        before = frame.rows
        data = _select(frame, ctx, where=where)
        write(work, frame, data)
        return CommandResult(
            command="",
            message=f"Kept {len(data):,} row(s), dropped {before - len(data):,}",
            changed_rows=len(data),
            data_changed=True,
        )

    names = _variable_list(ctx, rest)
    if not names:
        raise CommandError("keep needs variables, or an if condition")
    dropped = [v for v in ctx.variables if v not in names]
    data = _select(frame, ctx, only=names)
    write(work, frame, data)
    return CommandResult(
        command="",
        message=f"Kept {len(names)} variable(s), dropped {len(dropped)}",
        variables_removed=dropped,
        data_changed=True,
    )


# --- reading and writing datasets -------------------------------------------
#
# The only two commands that reach past the data in front of them. Everything
# else in this engine changes what is in memory; these decide what that memory
# was filled from and what becomes of it.


def _use(run: Run, rest: str) -> CommandResult:
    """use <dataset> - load a copy of one of the project's datasets."""
    name = _unquote(rest.strip().rstrip(","))
    if not name:
        raise CommandError("use needs a dataset name, e.g. use members")

    dataset = _find_dataset(run, name)
    if not dataset_is_queryable(dataset):
        raise CommandError(f"'{dataset.name}' has no data to work on yet")

    # A `use` after unsaved work throws that work away, which is what Stata
    # does and what makes a script re-runnable: each `use` starts a section.
    run.frame = load(run.work, dataset)
    run.frame.label_books = dict((dataset.meta or {}).get("label_books") or {})
    _note_read(run, dataset)
    return CommandResult(
        command="",
        message=f"Loaded {dataset.name}: {run.frame.rows:,} row(s), "
        f"{len(run.frame.variables)} variable(s)",
    )


def _save(run: Run, rest: str) -> CommandResult:
    """save as <name> | save, replace - put the data in memory on disk.

    `save as` makes a new dataset in the project. A bare `save` writes back
    over the one the data was loaded from, and needs `, replace` to say so out
    loud - Stata's rule, and the one that stops a script quietly overwriting
    the file it read.
    """
    frame = run.data
    body, options = _split_options(rest)
    body = body.strip()
    replacing = "replace" in options.lower()

    word, _, target = body.partition(" ")
    if word.lower() == "as":
        name = _unquote(target.strip())
        if not name:
            raise CommandError('save as needs a name, e.g. save as "Adults"')
        return _save_as(run, frame, name, replacing=replacing)

    if body:
        raise CommandError(
            f"save does not understand '{body}'. "
            "Write `save as <name>` for a new dataset, or `save, replace`."
        )
    if frame.origin is None:
        raise CommandError(
            "This data did not come from a single dataset, so there is nothing "
            "to write back over. Give it a name: save as <name>."
        )
    if not replacing:
        raise CommandError(
            f"'{frame.name}' already exists. Write `save, replace` to write "
            f"over it, or `save as <name>` to make a new dataset."
        )
    return _save_over(run, frame)


def _save_as(run: Run, frame: Frame, name: str, replacing: bool = False) -> CommandResult:
    """Write the data in memory out, as a new dataset or over the script's own.

    A script is a recipe, so running it twice has to rebuild what it built the
    first time rather than refusing because that already exists - otherwise it
    could only ever be run once, which is the opposite of the point. What it
    may write over is only what it wrote before: the ids the last run saved.
    Anything else is somebody else's dataset and is refused, unless the line
    says `replace` out loud.
    """
    if run.project_id is None:
        raise CommandError("save as needs a project to save into")
    existing = _lookup(run, name)
    if existing is not None:
        if not (replacing or existing.id in run.owns):
            raise CommandError(
                f"'{name}' already exists in this project and was not built by "
                f"this script. Pick another name, or write `save as {name}, "
                f"replace` to take it over."
            )
        _store(run.db, existing, frame)
        run.saved.append(
            Saved(dataset_id=existing.id, name=existing.name, created=False, rows=frame.rows)
        )
        frame.origin = existing.id
        frame.name = existing.name
        return CommandResult(
            command="",
            message=f"Saved {frame.rows:,} row(s) over {name}",
            data_changed=True,
        )

    dataset = create_dataset_record(
        run.db,
        name=name,
        description=f"Built by the project's script from {frame.name}.",
        source=DatasetSource.derived,
        project_id=run.project_id,
    )
    run.db.flush()
    _store(run.db, dataset, frame)
    run.saved.append(
        Saved(dataset_id=dataset.id, name=dataset.name, created=True, rows=frame.rows)
    )
    # What is in memory is now that dataset, so a second `save, replace` after
    # more work writes back over what was just made rather than asking for a
    # name again.
    frame.origin = dataset.id
    frame.name = dataset.name
    return CommandResult(
        command="",
        message=f"Saved {frame.rows:,} row(s) as a new dataset, {name}",
        data_changed=True,
    )


def _save_over(run: Run, frame: Frame) -> CommandResult:
    """Write the data in memory back over the dataset it was loaded from."""
    dataset = run.db.get(Dataset, frame.origin)
    if dataset is None:
        raise CommandError(
            f"'{frame.name}' is no longer there to write over. "
            "Give it a name: save as <name>."
        )
    _store(run.db, dataset, frame)
    run.saved.append(
        Saved(dataset_id=dataset.id, name=dataset.name, created=False, rows=frame.rows)
    )
    return CommandResult(
        command="",
        message=f"Saved {frame.rows:,} row(s) over {dataset.name}",
        data_changed=True,
    )


def _note_read(run: Run, dataset: Dataset) -> None:
    """Remember that the script read this one, without repeating it."""
    if dataset.id not in run.read:
        run.read.append(dataset.id)


def _find_dataset(run: Run, name: str) -> Dataset:
    found = _lookup(run, name)
    if found is None:
        if run.project_id is None:
            raise CommandError(
                "`use` reads a dataset from the project's own datasets, and "
                "this is not running in a project."
            )
        raise CommandError(f"This project has no dataset called '{name}'")
    return found


def _lookup(run: Run, name: str) -> Dataset | None:
    """A project's dataset by name, or by slug for a name with spaces in it.

    Matched without regard to case, because a script is typed by hand and
    "Members" and "members" are the same file to everyone but a database.
    """
    if run.project_id is None:
        return None
    wanted = name.strip().lower()
    datasets = (
        run.db.execute(select(Dataset).where(Dataset.project_id == run.project_id))
        .scalars()
        .all()
    )
    for dataset in datasets:
        if dataset.name.lower() == wanted or (dataset.slug or "").lower() == wanted:
            return dataset
    return None


# --- putting datasets together ----------------------------------------------


# The shapes Stata's merge takes, and what each promises about the key. m:m is
# deliberately absent: Stata's own manual advises against it, and the
# relationships feature here refuses it for the same reason - joining two
# many-sided tables multiplies rows rather than adding columns.
MERGE_SHAPES = {"1:1": (True, True), "m:1": (False, True), "1:m": (True, False)}

# Stata's own codes. Numbers rather than words because `keep if _merge == 3` is
# the idiom people already have in their fingers.
MASTER_ONLY, USING_ONLY, MATCHED = 1, 2, 3
MERGE_WORDS = {"master": MASTER_ONLY, "using": USING_ONLY, "match": MATCHED,
               "matched": MATCHED, "1": MASTER_ONLY, "2": USING_ONLY, "3": MATCHED}


def _merge(run: Run, rest: str) -> CommandResult:
    """merge 1:1|m:1|1:m <key...> using <name> [, keepusing() keep() nogen].

    A full outer join, which is what Stata's merge is before anything narrows
    it: rows that matched, rows only the data in memory had, and rows only the
    other dataset had, all kept and told apart by `_merge`.

    A variable on both sides is taken from the data in memory and the other
    copy is not brought over. That is Stata's rule, and the alternative -
    keeping both under invented names - leaves somebody to work out afterwards
    which of the two their analysis should have used.

    Keys are joined as SQL joins them, so a missing key matches nothing, not
    even another missing key. Stata pairs missings up; here that would take
    every row whose key was never recorded and multiply it by every other one,
    which is a large accident to leave lying in a script that runs nightly.
    Those rows come back as `_merge == 1`, which says plainly what happened.
    """
    frame, work = run.data, run.work
    body, options = _split_options(rest)

    shape, _, remainder = body.strip().partition(" ")
    if shape not in MERGE_SHAPES:
        raise CommandError(
            f"'{shape}' is not a merge this understands. The shape comes first: "
            "merge 1:1, merge m:1 or merge 1:m."
        )
    master_unique, using_unique = MERGE_SHAPES[shape]

    keys_text, found, using_name = _partition_word(remainder, "using")
    if not found:
        raise CommandError(
            "merge needs the dataset to read from: merge m:1 hhid using interviews"
        )
    using_name = _unquote(using_name.strip())
    if not using_name:
        raise CommandError("merge needs the name of the dataset to read from")

    keys = _names_in(keys_text)
    if not keys:
        raise CommandError("merge needs at least one key variable to join on")
    absent = [name for name in keys if not frame.has(name)]
    if absent:
        raise CommandError(
            f"The data in memory has no variable(s) called: {', '.join(absent)}"
        )

    other = _find_dataset(run, using_name)
    if not dataset_is_queryable(other):
        raise CommandError(f"'{other.name}' has no data to merge")
    _note_read(run, other)
    there_names = [variable.name for variable in other.variables]
    absent = [name for name in keys if name not in there_names]
    if absent:
        raise CommandError(
            f"'{other.name}' has no variable(s) called: {', '.join(absent)}"
        )

    wanted = _keepusing(options, there_names, keys, other.name)
    keeping = _merge_keep(options)
    generate = not re.search(r"\bnogen(erate)?\b", options, re.IGNORECASE)
    _reject_unknown_options(options, ("keepusing", "keep", "nogen", "nogenerate"))
    if generate and frame.has("_merge"):
        raise CommandError(
            "_merge is already there from an earlier merge. Drop it first "
            "(drop _merge), or add the nogen option."
        )

    here, there = str(frame.path), str(other.storage_path)
    if master_unique:
        _one_row_per_key(here, keys, "The data in memory", shape)
    if using_unique:
        _one_row_per_key(there, keys, f"'{other.name}'", shape)

    carried = [name for name in wanted if not frame.has(name)]
    shadowed = sorted(name for name in wanted if frame.has(name))

    on = " AND ".join(f"m.{quote_ident(k)} = u.{quote_ident(k)}" for k in keys)
    # The key is taken from whichever side has the row: on a using-only row
    # every master column is null, the key included, and a null key would lose
    # the one thing saying which group the row belongs to.
    selected = [
        f"COALESCE(m.{quote_ident(k)}, u.{quote_ident(k)}) AS {quote_ident(k)}"
        for k in keys
    ]
    selected += [
        f"m.{quote_ident(name)} AS {quote_ident(name)}"
        for name in frame.variables
        if name not in keys
    ]
    selected += [f"u.{quote_ident(name)} AS {quote_ident(name)}" for name in carried]
    # Sentinel columns rather than a key test: a row can match and still have
    # nulls everywhere, and only "was there a row on this side" is reliable.
    verdict = (
        f"CASE WHEN u.{MERGE_THERE} IS NULL THEN {MASTER_ONLY} "
        f"WHEN m.{MERGE_HERE} IS NULL THEN {USING_ONLY} "
        f"ELSE {MATCHED} END"
    )
    selected.append(f'{verdict} AS "_merge"')

    sql = (
        f"SELECT {', '.join(selected)} FROM "
        f"(SELECT *, TRUE AS {MERGE_HERE} FROM read_parquet({_quote_path(here)})) m "
        f"FULL OUTER JOIN "
        f"(SELECT *, TRUE AS {MERGE_THERE} FROM read_parquet({_quote_path(there)})) u "
        f"ON {on}"
    )
    if keeping:
        sql += f" WHERE {verdict} IN ({', '.join(str(code) for code in sorted(keeping))})"
    columns, rows = run_sql(sql)
    data = pd.DataFrame(rows, columns=columns)

    counts = {code: int((data["_merge"] == code).sum()) for code in (1, 2, 3)}
    if not generate:
        data = data.drop(columns=["_merge"])

    _carry_labels(frame, other, carried)
    write(work, frame, data)
    # The data is no longer the dataset it was loaded from, so a bare `save`
    # has nothing to write back over and will ask for a name.
    frame.origin = None
    frame.name = f"{frame.name} + {other.name}"

    return CommandResult(
        command="",
        message=_merge_message(other.name, len(data), counts, shadowed, generate),
        variables_added=(["_merge"] if generate else []) + carried,
        changed_rows=len(data),
        data_changed=True,
    )


MERGE_HERE = "__in_memory"
MERGE_THERE = "__in_using"


def _merge_message(
    name: str, rows: int, counts: dict[int, int], shadowed: list[str], generate: bool
) -> str:
    parts = [
        f"Merged {name}: {rows:,} row(s)",
        f"{counts[MATCHED]:,} matched",
        f"{counts[MASTER_ONLY]:,} only in memory",
        f"{counts[USING_ONLY]:,} only in {name}",
    ]
    message = parts[0] + " - " + ", ".join(parts[1:])
    if generate:
        message += " (see _merge)"
    if shadowed:
        few = ", ".join(shadowed[:5]) + ("..." if len(shadowed) > 5 else "")
        message += f". Kept this data's own {few}"
    return message


def _keepusing(options: str, there: list[str], keys: list[str], name: str) -> list[str]:
    """Which of the other dataset's variables to bring over. All, by default."""
    match = re.search(r"keepusing\s*\(([^)]*)\)", options, re.IGNORECASE)
    if match is None:
        return [column for column in there if column not in keys]
    asked = _names_in(match.group(1))
    absent = [column for column in asked if column not in there]
    if absent:
        raise CommandError(f"'{name}' has no variable(s) called: {', '.join(absent)}")
    return [column for column in asked if column not in keys]


def _merge_keep(options: str) -> set[int]:
    """`keep(match)`, `keep(master match)` - which rows survive. All by default."""
    match = re.search(r"(?<!\w)keep\s*\(([^)]*)\)", options, re.IGNORECASE)
    if match is None:
        return set()
    codes: set[int] = set()
    for word in _names_in(match.group(1)):
        code = MERGE_WORDS.get(word.lower())
        if code is None:
            raise CommandError(
                f"keep() does not understand '{word}'. It takes master, using "
                "and match."
            )
        codes.add(code)
    if not codes:
        raise CommandError("keep() needs at least one of master, using or match")
    return codes


def _one_row_per_key(path: str, keys: list[str], who: str, shape: str) -> None:
    """Hold the merge to the shape it claimed, rather than silently reshaping.

    A `1:1` that meets a repeated key quietly becomes a one-to-many and
    multiplies rows, which is the kind of mistake that is only noticed weeks
    later when a total is too big. Saying so at the line that caused it is the
    whole value of writing the shape down.
    """
    grouped = ", ".join(quote_ident(name) for name in keys)
    sql = (
        f"SELECT COUNT(*) FROM (SELECT 1 FROM read_parquet({_quote_path(path)}) "
        f"GROUP BY {grouped} HAVING COUNT(*) > 1)"
    )
    _, rows = run_sql(sql)
    repeated = int(rows[0][0]) if rows else 0
    if repeated:
        raise CommandError(
            f"{who} has {repeated:,} key value(s) appearing more than once, so "
            f"this is not a {shape} merge on {', '.join(keys)}. Use m:1, 1:m, "
            f"or collapse that side first."
        )


def _carry_labels(frame: Frame, other: Dataset, carried: list[str]) -> None:
    """A variable that crosses over brings its label and codes with it."""
    wanted = set(carried)
    for variable in other.variables:
        if variable.name not in wanted:
            continue
        if variable.label:
            frame.labels[variable.name] = variable.label
        if variable.value_labels:
            frame.value_labels[variable.name] = dict(variable.value_labels)


def _append(run: Run, rest: str) -> CommandResult:
    """append using <name> - put another dataset's rows under this one.

    Matched on variable name rather than position, which is what makes
    appending two rounds of the same survey safe when somebody inserted a
    question in between. A variable only one side has is missing on the rows
    from the other, as it is in Stata.
    """
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    _reject_unknown_options(options, ())

    word, found, using_name = _partition_word(body, "using")
    if not found or word.strip():
        raise CommandError("append reads one dataset: append using round2")
    using_name = _unquote(using_name.strip())
    if not using_name:
        raise CommandError("append needs the name of the dataset to read from")

    other = _find_dataset(run, using_name)
    if not dataset_is_queryable(other):
        raise CommandError(f"'{other.name}' has no data to append")
    _note_read(run, other)

    here_types = _column_types(str(frame.path))
    there_types = _column_types(str(other.storage_path))
    clashes = sorted(
        name
        for name, kind in there_types.items()
        if name in here_types and _kind_of(here_types[name]) != _kind_of(kind)
    )
    if clashes:
        name = clashes[0]
        raise CommandError(
            f"'{name}' is {_kind_of(here_types[name])} here and "
            f"{_kind_of(there_types[name])} in '{other.name}', so the rows "
            f"cannot be stacked"
            + (f" (and {len(clashes) - 1} other(s))" if len(clashes) > 1 else "")
            + ". Make them the same type first."
        )
    there = {variable.name: variable for variable in other.variables}

    before = frame.rows
    # UNION ALL BY NAME lines the columns up by name and fills what is missing
    # on either side with nulls, which is the whole of what append means.
    sql = (
        f"SELECT * FROM read_parquet({_quote_path(str(frame.path))}) "
        f"UNION ALL BY NAME "
        f"SELECT * FROM read_parquet({_quote_path(str(other.storage_path))})"
    )
    columns, rows = run_sql(sql)
    data = pd.DataFrame(rows, columns=columns)

    _carry_labels(frame, other, [name for name in there if not frame.has(name)])
    write(work, frame, data)
    frame.origin = None
    frame.name = f"{frame.name} + {other.name}"

    return CommandResult(
        command="",
        message=(
            f"Appended {other.name}: {len(data):,} row(s), "
            f"{before:,} from here and {len(data) - before:,} from there"
        ),
        changed_rows=len(data) - before,
        data_changed=True,
    )


def _column_types(path: str) -> dict[str, str]:
    """What each column is actually stored as, asked of the file itself.

    Not the variable's `var_type`, which is what the interface offers it as: a
    column of 1s and 0s is stored as a number and described as categorical, so
    reading that would have called every 0/1 question text and let it stack on
    top of a word.
    """
    _, rows = run_sql(f"DESCRIBE SELECT * FROM read_parquet({_quote_path(path)})")
    return {str(row[0]): str(row[1]) for row in rows}


def _kind_of(stored: str) -> str:
    """The grouping append has to care about: what will not stack on what."""
    stored = stored.upper()
    if stored.startswith(("VARCHAR", "CHAR", "TEXT", "STRING", "BLOB", "UUID")):
        return "text"
    if stored.startswith(("DATE", "TIME", "INTERVAL")):
        return "a date"
    return "a number"


# What `collapse` can work out, in the spelling Stata uses for it.
COLLAPSE_STATS = {
    "mean": "AVG", "sum": "SUM", "count": "COUNT", "max": "MAX", "min": "MIN",
    "median": "MEDIAN", "p50": "MEDIAN", "sd": "STDDEV_SAMP", "first": "FIRST",
    "last": "LAST",
}


def _collapse(run: Run, rest: str) -> CommandResult:
    """collapse [(stat)] <varlist> [(stat) <varlist>...] [, by(...)].

    One row per group, as Stata does it, and like Stata it replaces what is in
    memory rather than adding to it: a person-level file becomes a province
    -level one. That is why nothing reaches disk without a save, and why the
    result has to be given a name of its own.
    """
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    by = _by_variables(frame.context, options)
    _reject_unknown_options(options, ("by",))

    wanted = _collapse_terms(frame, body, by)
    if not wanted:
        raise CommandError(
            "collapse needs something to summarise: collapse (mean) wage, by(province)"
        )

    selected = [quote_ident(name) for name in by]
    for stat, name in wanted:
        selected.append(f"{COLLAPSE_STATS[stat]}({quote_ident(name)}) AS {quote_ident(name)}")
    sql = f"SELECT {', '.join(selected)} FROM read_parquet({_quote_path(str(frame.path))})"
    if by:
        grouped = ", ".join(quote_ident(name) for name in by)
        sql += f" GROUP BY {grouped} ORDER BY {grouped}"
    columns, rows = run_sql(sql)
    data = pd.DataFrame(rows, columns=columns)

    before = frame.rows
    # The summaries are new numbers, so a label saying what the column held
    # one row at a time no longer describes it.
    kept = set(by)
    frame.labels = {name: text for name, text in frame.labels.items() if name in kept}
    frame.value_labels = {
        name: pairs for name, pairs in frame.value_labels.items() if name in kept
    }
    write(work, frame, data)
    frame.origin = None
    frame.name = f"{frame.name} collapsed"

    how = ", ".join(f"{stat} of {name}" for stat, name in wanted)
    where = f" by {', '.join(by)}" if by else ""
    return CommandResult(
        command="",
        message=f"Collapsed {before:,} row(s) to {len(data):,}{where}: {how}",
        changed_rows=len(data),
        data_changed=True,
    )


def _collapse_terms(frame: Frame, body: str, by: list[str]) -> list[tuple[str, str]]:
    """`(mean) wage (sum) hours` - and a bare varlist, which means mean."""
    body = body.strip()
    if not body:
        return []
    terms: list[tuple[str, str]] = []
    stat = "mean"
    # Split on the bracketed statistics, keeping them: everything after one
    # belongs to it until the next.
    for piece in re.split(r"\(([A-Za-z0-9]+)\)", body):
        piece = piece.strip()
        if not piece:
            continue
        if piece.lower() in COLLAPSE_STATS:
            stat = piece.lower()
            continue
        for name in _names_in(piece):
            if not frame.has(name):
                raise CommandError(f"'{name}' is not a variable in the data")
            if name in by:
                raise CommandError(
                    f"'{name}' is what the rows are grouped by, so it cannot "
                    f"also be summarised"
                )
            terms.append((stat, name))
    return terms


def _contract(run: Run, rest: str) -> CommandResult:
    """contract <varlist> - how many rows each combination has.

    The frequency table as a dataset, which is what makes it chartable. `_freq`
    is Stata's name for the count and is kept so the idiom carries over.
    """
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    _reject_unknown_options(options, ())

    names = _names_in(body)
    if not names:
        raise CommandError("contract needs at least one variable: contract province")
    absent = [name for name in names if not frame.has(name)]
    if absent:
        raise CommandError(f"'{', '.join(absent)}' is not a variable in the data")

    grouped = ", ".join(quote_ident(name) for name in names)
    sql = (
        f"SELECT {grouped}, COUNT(*) AS \"_freq\" "
        f"FROM read_parquet({_quote_path(str(frame.path))}) "
        f"GROUP BY {grouped} ORDER BY {grouped}"
    )
    columns, rows = run_sql(sql)
    data = pd.DataFrame(rows, columns=columns)

    before = frame.rows
    kept = set(names)
    frame.labels = {name: text for name, text in frame.labels.items() if name in kept}
    frame.value_labels = {
        name: pairs for name, pairs in frame.value_labels.items() if name in kept
    }
    write(work, frame, data)
    frame.origin = None
    frame.name = f"{frame.name} counted"

    return CommandResult(
        command="",
        message=(
            f"Counted {before:,} row(s) into {len(data):,} combination(s) of "
            f"{', '.join(names)}, in _freq"
        ),
        variables_added=["_freq"],
        changed_rows=len(data),
        data_changed=True,
    )


def _partition_word(text: str, word: str) -> tuple[str, bool, str]:
    """Split on a bare word, so a variable called `usingwhat` is not one."""
    match = re.search(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])", text, re.IGNORECASE)
    if match is None:
        return text, False, ""
    return text[: match.start()], True, text[match.end() :]


def _names_in(text: str) -> list[str]:
    return [piece for piece in re.split(r"[\s,]+", text.strip()) if piece]


def _reject_unknown_options(options: str, allowed: tuple[str, ...]) -> None:
    """Say so rather than ignoring an option, which would run the wrong thing.

    Only the option's own name is looked at. What is inside the brackets is
    that option's argument - variable names, usually - and reading those as
    options too refused `by(province)` on the grounds that there is no option
    called province.
    """
    without_arguments = re.sub(r"\([^)]*\)", " ", options)
    for found in re.findall(r"[A-Za-z][A-Za-z0-9_]*", without_arguments):
        if found.lower() not in allowed:
            listed = ", ".join(allowed) if allowed else "none"
            raise CommandError(
                f"'{found}' is not an option here. Options taken: {listed}"
            )


# --- plumbing ---------------------------------------------------------------


def verbs() -> dict[str, Any]:
    """Every spelling Stata takes for the commands that change the data.

    A function rather than a module-level dict, so the table can sit beside
    the commands it names instead of below every one of them, out of sight of
    the dispatcher that reads it.
    """
    return {
        "use": _use,
        "save": _save,
        "merge": _merge,
        "append": _append,
        "collapse": _collapse,
        "contract": _contract,
        "gen": _generate, "gene": _generate, "generate": _generate, "g": _generate,
        "replace": _replace,
        "egen": _egen,
        "label": _label, "la": _label, "lab": _label,
        "rename": _rename, "ren": _rename,
        "drop": _drop,
        "keep": _keep,
    }


def _context(dataset: Dataset) -> DatasetContext:
    return DatasetContext.from_model(dataset)


def _assignment(rest: str) -> tuple[str, str, str]:
    """`name = expression [if condition]`, as gen and replace both take."""
    name, sign, remainder = rest.partition("=")
    if not sign:
        raise CommandError('Expected an "=", e.g. gen adult = age >= 18')
    name = name.strip()
    # A type in front of the name, as in `gen byte adult = ...`, is Stata's
    # storage hint and means nothing here.
    if " " in name:
        name = name.split()[-1]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise CommandError(f"'{name}' is not a usable variable name")

    expression, condition = _split_if(remainder.strip())
    if not expression:
        raise CommandError("There is nothing on the right of the '='")
    return name, expression, condition


def _split_if(text: str) -> tuple[str, str]:
    """Split on a top-level `if`, leaving one inside a string or bracket alone."""
    depth = 0
    in_string = False
    index = 0
    while index < len(text):
        character = text[index]
        if character == '"':
            in_string = not in_string
        elif not in_string:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif (
                depth == 0
                and text[index : index + 2].lower() == "if"
                and (index == 0 or not _is_name_char(text[index - 1]))
                and (index + 2 >= len(text) or not _is_name_char(text[index + 2]))
            ):
                return text[:index].strip(), text[index + 2 :].strip()
        index += 1
    return text.strip(), ""


def _split_options(rest: str) -> tuple[str, str]:
    """Split `body , options` on the comma Stata uses for options."""
    body, _, options = rest.partition(",")
    return body.strip(), options.strip()


def _by_variables(ctx: DatasetContext, options: str) -> list[str]:
    if not options:
        return []
    match = re.search(r"by\s*\(([^)]*)\)", options, re.IGNORECASE)
    if match is None:
        raise CommandError(f"'{options}' is not an option this understands; only by() is")
    return _variable_list(ctx, match.group(1))


def _variable_list(ctx: DatasetContext, text: str) -> list[str]:
    names: list[str] = []
    for raw in re.split(r"[\s,]+", text.strip()):
        if not raw:
            continue
        if raw not in ctx.variables:
            raise CommandError(f"'{raw}' is not a variable in the data")
        names.append(raw)
    return names


def _rowwise(ctx: DatasetContext, function: str, arguments: str) -> str:
    columns = _variable_list(ctx, arguments)
    if not columns:
        raise CommandError(f"egen {function}() needs at least one variable")
    numbers = [f"TRY_CAST({quote_ident(c)} AS DOUBLE)" for c in columns]
    if function == "rowmiss":
        return " + ".join(f"CASE WHEN {n} IS NULL THEN 1 ELSE 0 END" for n in numbers)
    if function == "rownonmiss":
        return " + ".join(f"CASE WHEN {n} IS NULL THEN 0 ELSE 1 END" for n in numbers)
    if function == "rowmax":
        return f"GREATEST({', '.join(numbers)})"
    if function == "rowmin":
        return f"LEAST({', '.join(numbers)})"
    # rowtotal and rowmean treat missing as skipped, as Stata does.
    total = " + ".join(f"COALESCE({n}, 0)" for n in numbers)
    if function == "rowtotal":
        return f"({total})"
    present = " + ".join(f"CASE WHEN {n} IS NULL THEN 0 ELSE 1 END" for n in numbers)
    return f"(({total}) / NULLIF({present}, 0))"


def _condition_sql(ctx: DatasetContext, condition: str) -> str:
    if not condition:
        return ""
    return translate(condition, set(ctx.variables), quote_ident)


def _count_matching(frame: Frame, where: str) -> int:
    sql = (
        f"SELECT COUNT(*) FROM read_parquet({_quote_path(str(frame.path))}) "
        f"WHERE {where}"
    )
    _, rows = run_sql(sql)
    return int(rows[0][0]) if rows else 0


def _select(
    frame: Frame,
    ctx: DatasetContext,
    extra: list[tuple[str, str]] | None = None,
    replace: dict[str, str] | None = None,
    rename: dict[str, str] | None = None,
    only: list[str] | None = None,
    where: str = "",
) -> pd.DataFrame:
    """Build the data as the command leaves it, and read it back."""
    replace = replace or {}
    rename = rename or {}
    names = only if only is not None else list(ctx.variables)

    selected: list[str] = []
    for name in names:
        expression = replace.get(name, quote_ident(name))
        alias = rename.get(name, name)
        selected.append(f"{expression} AS {quote_ident(alias)}")
    for alias, expression in extra or []:
        selected.append(f"{expression} AS {quote_ident(alias)}")

    # The rows come back in the order they are stored in. Without this a
    # command using a window function - egen with by(), say - is free to return
    # them grouped, which silently reorders the data under everything that
    # reads it by position.
    ordinal = quote_ident(ROW_ORDER)
    sql = (
        f"SELECT {', '.join(selected)} FROM ("
        f"SELECT *, ROW_NUMBER() OVER () AS {ordinal} "
        f"FROM read_parquet({_quote_path(str(frame.path))})"
        f")"
    )
    if where:
        sql += f" WHERE {where}"
    sql += f" ORDER BY {ordinal}"
    columns, rows = run_sql(sql)
    return pd.DataFrame(rows, columns=columns)


def _as_numbers(data: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """Turn a true/false column into 1/0, because Stata has no true or false.

    `gen adult = age >= 18` is a number in Stata, and everything downstream
    assumes that: `egen total = sum(adult)` and `collapse (sum) adult` are
    arithmetic, and a chart of it is a chart of a count. DuckDB answers a
    comparison with a BOOLEAN, which cannot be summed at all - the binder
    refuses `sum(BOOLEAN)` outright - so the column has to become what Stata
    would have made it before anything else sees it.

    Missing stays missing: a nullable integer, not a zero.
    """
    for name in names:
        if name in data.columns and data[name].dtype == "bool" or (
            name in data.columns and str(data[name].dtype) == "boolean"
        ):
            data[name] = data[name].astype("Int64")
        elif name in data.columns and data[name].dtype == object:
            # An object column of True/False/None, which is how a nullable
            # boolean arrives through the row-by-row read.
            values = data[name].dropna().unique().tolist()
            if values and all(isinstance(value, bool) for value in values):
                data[name] = data[name].map(
                    lambda value: None if value is None else int(value)
                ).astype("Int64")
    return data


def _check_new_name(frame: Frame, name: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise CommandError(f"'{name}' is not a usable variable name")
    if frame.has(name):
        raise CommandError(f"'{name}' already exists. Use replace to change it.")


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _label_definition(body: str) -> tuple[str, dict[str, str]]:
    """`label define name 1 "Yes" 2 "No"`."""
    try:
        parts = shlex.split(body)
    except ValueError as exc:
        raise CommandError(f"Could not read the label definition: {exc}") from exc
    if len(parts) < 3:
        raise CommandError('label define needs a name and pairs, e.g. label define yn 1 "Yes"')
    book, rest = parts[0], parts[1:]
    if len(rest) % 2:
        raise CommandError("Every code needs a label after it")
    pairs = {rest[i]: rest[i + 1] for i in range(0, len(rest), 2)}
    return book, pairs


def entries(dataset: Dataset) -> list[str]:
    """What has been run, in the order it will be replayed.

    Entries were once dicts carrying a language, from when R scripts shared
    this list. Those are read for their text and nothing else, so a dataset
    carrying the older shape still replays rather than silently doing nothing.
    """
    out: list[str] = []
    for item in (dataset.meta or {}).get("commands") or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("text"):
            out.append(str(item["text"]))
    return out


def forget(dataset: Dataset) -> None:
    """Stop replaying what was recorded, without undoing what it did."""
    meta = dict(dataset.meta or {})
    meta["commands"] = []
    dataset.meta = meta


def replay(db: Session, dataset: Dataset) -> list[str]:
    """Re-run everything recorded, in order, after a newer export replaced the data.

    Failures are reported rather than raised. The import has already happened,
    and a step that no longer applies - it named a variable this export does
    not have - is a note beside the data rather than a 500 on the upload that
    this platform exists to make routine.
    """
    problems: list[str] = []
    for text in entries(dataset):
        try:
            run(db, dataset, text, record_it=False)
        except Exception as exc:  # noqa: BLE001 - a replay must never fail an
            # import that has already happened.
            logger.exception("Replaying a recorded command failed")
            problems.append(f"'{_short(text)}' could not be re-applied: {exc}")
    return problems


def _short(text: str, limit: int = 80) -> str:
    """A step named in a warning, cut to one readable line."""
    first = text.strip().splitlines()[0] if text.strip() else text
    return first if len(first) <= limit else first[:limit] + "..."


def _remember(dataset: Dataset, command: str) -> None:
    meta = dict(dataset.meta or {})
    commands = list(meta.get("commands") or [])
    commands.append(command)
    meta["commands"] = commands
    dataset.meta = meta


def _remember_label(
    dataset: Dataset,
    variable: str,
    label: str | None = None,
    value_labels: dict[str, str] | None = None,
) -> None:
    """Keep it where the label editor keeps its own, so a replace preserves it."""
    meta = dict(dataset.meta or {})
    overrides = dict(meta.get("variable_labels") or {})
    stored = dict(overrides.get(variable) or {})
    if label is not None:
        stored["label"] = label
    if value_labels is not None:
        stored["value_labels"] = value_labels
    overrides[variable] = stored
    meta["variable_labels"] = overrides
    dataset.meta = meta
