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
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Dataset
from app.services.datasets import _apply_ingest, dataset_directory, dataset_is_queryable
from app.services.ingest import ingest_frame
from app.services.query_engine import (
    DatasetContext,
    _quote_path,
    quote_ident,
    run_sql,
)
from app.services.stata_expr import ExpressionError, translate

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


def run(db: Session, dataset: Dataset, text: str, record_it: bool = True) -> CommandResult:
    """Run one command against a dataset, and remember it if it changed anything."""
    # The variable rows are deleted and rebuilt by every command that changes
    # the data, so a second command in the same transaction would otherwise be
    # deciding against the list as it was before the first one ran.
    db.flush()
    db.refresh(dataset)

    if not dataset_is_queryable(dataset):
        raise CommandError(f"'{dataset.name}' has no data to work on yet")

    command = text.strip().rstrip(";").strip()
    if not command:
        raise CommandError("Type a command, for example: gen adult = age >= 18")

    verb, _, rest = command.partition(" ")
    verb = verb.lower()
    rest = rest.strip()

    if verb in ("gen", "gene", "generate", "g"):
        result = _generate(db, dataset, rest)
    elif verb == "replace":
        result = _replace(db, dataset, rest)
    elif verb == "egen":
        result = _egen(db, dataset, rest)
    elif verb in ("label", "la", "lab"):
        result = _label(db, dataset, rest)
    elif verb in ("rename", "ren"):
        result = _rename(db, dataset, rest)
    elif verb == "drop":
        result = _drop(db, dataset, rest)
    elif verb == "keep":
        result = _keep(db, dataset, rest)
    else:
        raise CommandError(
            f"'{verb}' is not a command this understands. "
            "Available: gen, replace, egen, label, rename, drop, keep"
        )

    result.command = command
    if record_it:
        _remember(dataset, command)
    return result


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
        # A // inside a string is part of the string, not a comment.
        if "//" in line and line.count('"') % 2 == 0:
            head, _, tail = line.partition("//")
            if tail.startswith("/"):
                buffer += " " + head.strip()
                continue
            line = head.strip()
        if not line:
            continue
        buffer = (buffer + " " + line).strip() if buffer else line
        joined.append(buffer)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def history(dataset: Dataset) -> list[str]:
    return list((dataset.meta or {}).get("commands") or [])


def forget(dataset: Dataset) -> None:
    meta = dict(dataset.meta or {})
    meta["commands"] = []
    dataset.meta = meta


def replay(db: Session, dataset: Dataset) -> list[str]:
    """Re-run the recorded commands, for after a newer export replaced the data.

    A generated variable is not in the file, so a replacement would drop it and
    everything built on it. Failures are reported rather than raised: a command
    that no longer applies - it named a variable this export does not have -
    must not stop the import that has already happened.
    """
    commands = history(dataset)
    if not commands:
        return []
    problems: list[str] = []
    for command in commands:
        try:
            run(db, dataset, command, record_it=False)
        except (CommandError, ExpressionError) as exc:
            problems.append(f"'{command}' could not be re-applied: {exc}")
        except Exception as exc:  # noqa: BLE001 - a replay must never be able to
            # fail the import that has already happened; the data is in, and a
            # command that broke on it is a note beside it rather than a 500.
            logger.exception("Replaying '%s' failed", command)
            problems.append(f"'{command}' could not be re-applied: {exc}")
    return problems


# --- commands ---------------------------------------------------------------


def _generate(db: Session, dataset: Dataset, rest: str) -> CommandResult:
    name, expression, condition = _assignment(rest)
    _check_new_name(dataset, name)
    ctx = _context(dataset)
    value = translate(expression, set(ctx.variables), quote_ident)
    where = _condition_sql(ctx, condition)
    # Outside the if, the new variable is missing - which is what Stata does.
    column = f"CASE WHEN {where} THEN {value} ELSE NULL END" if where else value
    frame = _select(dataset, ctx, extra=[(name, column)])
    _write(db, dataset, frame)
    return CommandResult(
        command="",
        message=f"Created {name}",
        variables_added=[name],
        changed_rows=len(frame),
        data_changed=True,
    )


def _replace(db: Session, dataset: Dataset, rest: str) -> CommandResult:
    name, expression, condition = _assignment(rest)
    ctx = _context(dataset)
    if name not in ctx.variables:
        raise CommandError(f"'{name}' is not a variable in this dataset. Use gen to create it.")
    value = translate(expression, set(ctx.variables), quote_ident)
    where = _condition_sql(ctx, condition)
    column = f"CASE WHEN {where} THEN {value} ELSE {quote_ident(name)} END" if where else value

    changed = _count_matching(dataset, where) if where else None
    frame = _select(dataset, ctx, replace={name: column})
    _write(db, dataset, frame)
    affected = changed if changed is not None else len(frame)
    return CommandResult(
        command="",
        message=f"Replaced {name} in {affected:,} row(s)",
        changed_rows=affected,
        data_changed=True,
    )


def _egen(db: Session, dataset: Dataset, rest: str) -> CommandResult:
    """egen new = fn(args) [, by(v1 v2)] - the aggregate and row-wise forms."""
    body, options = _split_options(rest)
    name, _, call = (part.strip() for part in body.partition("="))
    if not name or not call:
        raise CommandError('egen needs a name and a function, e.g. egen n = count(age), by(region)')
    _check_new_name(dataset, name)

    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)$", call.strip(), re.DOTALL)
    if match is None:
        raise CommandError(f"'{call}' is not a function call egen understands")
    function, arguments = match.group(1).lower(), match.group(2).strip()

    ctx = _context(dataset)
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

    frame = _select(dataset, ctx, extra=[(name, column)])
    _write(db, dataset, frame)
    return CommandResult(
        command="",
        message=f"Created {name}" + (f" within {', '.join(by)}" if by else ""),
        variables_added=[name],
        changed_rows=len(frame),
        data_changed=True,
    )


def _label(db: Session, dataset: Dataset, rest: str) -> CommandResult:
    """label variable / label define / label values - names, not data."""
    kind, _, body = rest.partition(" ")
    kind, body = kind.lower(), body.strip()

    if kind in ("variable", "var", "v"):
        name, _, text = body.partition(" ")
        variable = _variable(dataset, name)
        variable.label = _unquote(text.strip())
        _remember_label(dataset, variable.name, label=variable.label)
        return CommandResult(command="", message=f"Labelled {variable.name}")

    if kind in ("define", "def"):
        book, pairs = _label_definition(body)
        meta = dict(dataset.meta or {})
        books = dict(meta.get("label_books") or {})
        books[book] = pairs
        meta["label_books"] = books
        dataset.meta = meta
        return CommandResult(
            command="", message=f"Defined label set '{book}' with {len(pairs)} value(s)"
        )

    if kind in ("values", "val", "value"):
        name, _, book = body.partition(" ")
        book = book.strip()
        variable = _variable(dataset, name)
        books = (dataset.meta or {}).get("label_books") or {}
        if book and book not in books:
            raise CommandError(
                f"No label set called '{book}'. Define it first: "
                f'label define {book} 1 "Yes" 2 "No"'
            )
        pairs = dict(books.get(book) or {}) if book else {}
        variable.value_labels = pairs
        _remember_label(dataset, variable.name, value_labels=pairs)
        return CommandResult(
            command="",
            message=(
                f"Applied '{book}' to {variable.name}"
                if book
                else f"Cleared labels on {variable.name}"
            ),
        )

    raise CommandError(
        "label takes variable, define or values, e.g. label variable age \"Age in years\""
    )


def _rename(db: Session, dataset: Dataset, rest: str) -> CommandResult:
    parts = rest.split()
    if len(parts) != 2:
        raise CommandError("rename takes the old name and the new one: rename q1 age")
    old, new = parts
    variable = _variable(dataset, old)
    _check_new_name(dataset, new)

    ctx = _context(dataset)
    frame = _select(dataset, ctx, rename={variable.name: new})
    _write(db, dataset, frame, renamed={variable.name: new})
    return CommandResult(
        command="",
        message=f"Renamed {variable.name} to {new}",
        variables_added=[new],
        variables_removed=[variable.name],
        data_changed=True,
    )


def _drop(db: Session, dataset: Dataset, rest: str) -> CommandResult:
    ctx = _context(dataset)
    if rest.lower().startswith("if "):
        where = _condition_sql(ctx, rest[3:].strip())
        before = dataset.row_count
        frame = _select(dataset, ctx, where=f"NOT ({where}) OR ({where}) IS NULL")
        _write(db, dataset, frame)
        return CommandResult(
            command="",
            message=f"Dropped {before - len(frame):,} row(s)",
            changed_rows=before - len(frame),
            data_changed=True,
        )

    names = _variable_list(ctx, rest)
    if not names:
        raise CommandError("drop needs variables, or an if condition")
    remaining = [v for v in ctx.variables if v not in names]
    if not remaining:
        raise CommandError("That would drop every variable in the dataset")
    frame = _select(dataset, ctx, only=remaining)
    _write(db, dataset, frame)
    return CommandResult(
        command="",
        message=f"Dropped {', '.join(names)}",
        variables_removed=names,
        data_changed=True,
    )


def _keep(db: Session, dataset: Dataset, rest: str) -> CommandResult:
    ctx = _context(dataset)
    if rest.lower().startswith("if "):
        where = _condition_sql(ctx, rest[3:].strip())
        before = dataset.row_count
        frame = _select(dataset, ctx, where=where)
        _write(db, dataset, frame)
        return CommandResult(
            command="",
            message=f"Kept {len(frame):,} row(s), dropped {before - len(frame):,}",
            changed_rows=len(frame),
            data_changed=True,
        )

    names = _variable_list(ctx, rest)
    if not names:
        raise CommandError("keep needs variables, or an if condition")
    dropped = [v for v in ctx.variables if v not in names]
    frame = _select(dataset, ctx, only=names)
    _write(db, dataset, frame)
    return CommandResult(
        command="",
        message=f"Kept {len(names)} variable(s), dropped {len(dropped)}",
        variables_removed=dropped,
        data_changed=True,
    )


# --- plumbing ---------------------------------------------------------------


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
                and (index == 0 or not text[index - 1].isalnum())
                and (index + 2 >= len(text) or not text[index + 2].isalnum())
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
            raise CommandError(f"'{raw}' is not a variable in this dataset")
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


def _count_matching(dataset: Dataset, where: str) -> int:
    sql = (
        f"SELECT COUNT(*) FROM read_parquet({_quote_path(dataset.storage_path)}) "
        f"WHERE {where}"
    )
    _, rows = run_sql(sql)
    return int(rows[0][0]) if rows else 0


def _select(
    dataset: Dataset,
    ctx: DatasetContext,
    extra: list[tuple[str, str]] | None = None,
    replace: dict[str, str] | None = None,
    rename: dict[str, str] | None = None,
    only: list[str] | None = None,
    where: str = "",
) -> pd.DataFrame:
    """Build the dataset as the command leaves it, and read it back."""
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
    # them grouped, which silently reorders the dataset under everything that
    # reads it by position.
    ordinal = quote_ident(ROW_ORDER)
    sql = (
        f"SELECT {', '.join(selected)} FROM ("
        f"SELECT *, ROW_NUMBER() OVER () AS {ordinal} "
        f"FROM read_parquet({_quote_path(dataset.storage_path)})"
        f")"
    )
    if where:
        sql += f" WHERE {where}"
    sql += f" ORDER BY {ordinal}"
    columns, rows = run_sql(sql)
    return pd.DataFrame(rows, columns=columns)


def _write(
    db: Session, dataset: Dataset, frame: pd.DataFrame, renamed: dict[str, str] | None = None
) -> None:
    """Persist the new shape of the dataset, keeping the labels it had."""
    renamed = renamed or {}
    labels = {}
    value_labels = {}
    for variable in dataset.variables:
        name = renamed.get(variable.name, variable.name)
        if variable.label:
            labels[name] = variable.label
        if variable.value_labels:
            value_labels[name] = variable.value_labels
    _apply_ingest(
        db,
        dataset,
        ingest_frame(frame, labels, value_labels, dataset_directory(dataset.id), []),
    )


def _variable(dataset: Dataset, name: str) -> Any:
    name = name.strip()
    for variable in dataset.variables:
        if variable.name == name:
            return variable
    raise CommandError(f"'{name}' is not a variable in this dataset")


def _check_new_name(dataset: Dataset, name: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise CommandError(f"'{name}' is not a usable variable name")
    if any(v.name == name for v in dataset.variables):
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
