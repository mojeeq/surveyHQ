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
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Dataset, DatasetSource, Project
from app.services.datasets import (
    _apply_ingest,
    create_dataset_record,
    dataset_directory,
    dataset_is_queryable,
)
from app.services.ingest import IngestResult, numeric_code_text
from app.services.query_engine import (
    MISSING_TAG_SUFFIX,
    DatasetContext,
    _quote_path,
    column_types,
    compatible,
    kind_of,
    quote_ident,
    run_sql,
)
from app.services.stata_expr import ExpressionError, Window, translate
from app.services.stata_frame import (
    Frame,
    FrameError,
    Workspace,
    load,
    variables_of,
    write,
)
from app.services.stata_macros import MacroError
from app.services.stata_macros import define as define_macro
from app.services.stata_macros import expand as expand_macros

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
    # Set by a command that only looks - count, summarize, tabulate, assert.
    # It changed nothing, so there is nothing to write back, and a replay
    # after a newer export has no reason to run it again.
    reports_only: bool = False


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

# The options each command takes after its comma, as it checks them. One
# table rather than a tuple at each check, because the script editor offers
# these as you type: a second list there would drift, and an editor that
# suggests an option the command then refuses is worse than one that offers
# nothing. Commands absent here take no options.
OPTIONS: dict[str, tuple[str, ...]] = {
    "merge": ("keepusing", "keep", "nogen", "nogenerate"),
    "collapse": ("by",),
    "destring": ("replace", "generate", "gen", "g", "force", "percent", "dpcomma", "ignore"),
    "egen": ("by",),
    "save": ("replace",),
    "recode": ("generate", "gen", "g", "prefix"),
    "duplicates": ("force", "generate", "gen", "g"),
    "reshape": ("i", "j", "string"),
    "tostring": ("replace", "generate", "gen", "g", "force"),
    "encode": ("generate", "gen", "g", "label"),
    "decode": ("generate", "gen", "g"),
    "sort": ("stable",),
    "order": ("first", "last", "before", "after"),
    "summarize": ("detail",),
    "tabulate": ("missing",),
}


@dataclass
class Saved:
    """A dataset a script wrote, and whether the script made it."""

    dataset_id: str
    name: str
    created: bool
    rows: int


@dataclass(frozen=True)
class ByGroups:
    """`by hhid:` or `bysort hhid (age):` - the groups a command works within.

    `keys` make the groups. `order` is how the rows are ordered inside each,
    which is what the bracketed part of a bysort says and what `_n` counts.
    """

    keys: tuple[str, ...]
    order: tuple[str, ...] = ()


#: The commands a `by` prefix can stand in front of: the ones whose numbers
#: can be counted within a group.
BY_ABLE = {"gen", "replace", "egen", "keep", "drop", "assert"}


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
    # None only while a macro is being defined, which is the one thing a
    # command can do with no data and nowhere to put any.
    work: Workspace | None = None
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
    # Named pieces of script text, by namespace. Both last for the run: a run
    # is the whole session here, so Stata's distinction between a local that
    # ends with the do-file and a global that outlives it has nothing to
    # separate. The two names stay apart because scripts are written with
    # both, and a local and a global of one name are two macros in Stata.
    locals: dict[str, str] = field(default_factory=dict)
    globals: dict[str, str] = field(default_factory=dict)
    # The groups a `by` prefix splits the data into, for the one command it
    # stands in front of. None for every other command.
    by: ByGroups | None = None

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
    # Macro references are replaced before the command is parsed, which is all
    # a macro is - but not in the line that defines one, or `local a `b'` would
    # expand the name being defined rather than the text it stands for.
    if verb.lower().rstrip(",") not in ("local", "global"):
        try:
            # Stripped again: a macro that stands for nothing is a legitimate
            # thing to define - it is how a condition is switched off without
            # deleting the lines using it - and `prefix' at the front of a
            # command then leaves a leading space, which the partition below
            # reads as an empty verb.
            command = expand_macros(command, run.locals, run.globals).strip()
        except MacroError as exc:
            raise CommandError(str(exc)) from exc
        if not command:
            raise CommandError(
                "That command is nothing but macros, and all of them stand "
                "for nothing, so there is no command left to run."
            )
        verb, _, rest = command.partition(" ")
    prefix = BY_PREFIX.match(command)
    if prefix is not None:
        return _by(run, command, prefix)
    # `save as x` and `save, replace` are both the save verb; Stata spells the
    # first with a word and the second with an option, and the partition above
    # would hand "save," on as the verb.
    handler = verbs().get(verb.lower().rstrip(","))
    if handler is None:
        raise CommandError(
            f"'{verb}' is not a command this understands. "
            f"Available: {', '.join(verb_names())}"
        )
    if verb.lower().endswith(",") and not rest.startswith(","):
        rest = "," + rest

    result = handler(run, rest.strip())
    result.command = command
    return result


BY_PREFIX = re.compile(r"^(by|bys|byso|bysor|bysort)\s+([^:]+?)\s*:\s*(\S.*)$", re.IGNORECASE)


def _by(run: Run, command: str, prefix: re.Match[str]) -> CommandResult:
    """`by hhid: gen n = _n`, `bysort hhid (age): keep if _n == 1`.

    The command after the colon runs within each group: `_n` counts from one
    in every household, `_N` is the household's size, `x[_n-1]` is the row
    before in the same household. `bysort` sorts the data by the groups first,
    as Stata does, and keeps it sorted; `by` takes the rows in the order they
    are in.
    """
    groups = prefix.group(2).strip()
    order: list[str] = []
    inside = re.search(r"\(([^)]*)\)\s*$", groups)
    if inside:
        order = _names_in(inside.group(1))
        groups = groups[: inside.start()].strip()
    keys = _names_in(groups)
    if not keys:
        raise CommandError("by needs the variables to group by, e.g. by hhid: gen n = _n")
    _variable_list(run.data.context, " ".join([*keys, *order]))
    inner = prefix.group(3).strip()
    inner_verb = inner.split(" ")[0].lower().rstrip(",")
    handler = verbs().get(inner_verb)
    if handler is None or _canonical(inner_verb) not in BY_ABLE:
        raise CommandError(
            f"by works with {', '.join(sorted(BY_ABLE))}; '{inner_verb}' is not one of them"
        )
    if prefix.group(1).lower().startswith("bys"):
        _sort_frame(run, [(name, False) for name in [*keys, *order]])
    run.by = ByGroups(keys=tuple(keys), order=tuple(order))
    try:
        result = handler(run, inner.partition(" ")[2].strip())
    finally:
        run.by = None
    result.command = command
    return result


def _canonical(verb: str) -> str:
    """The name a command goes by, whichever spelling was typed."""
    handler = verbs().get(verb)
    return next((name for name, one in verbs().items() if one is handler), verb)


def _window(run: Run) -> Window:
    """The rows `_n`, `_N` and subscripts count over for this command."""
    by = run.by or ByGroups(keys=())
    return Window(
        partition=tuple(quote_ident(name) for name in by.keys),
        order=(
            *_order_terms(run.data, [(name, False) for name in by.order]),
            quote_ident(ROW_ORDER),
        ),
    )


# The commands that define a macro rather than doing anything to the data.
# They are the only ones that can run with no data in memory at all, which is
# what lets a script name its conditions above the `use` that opens the file.
NAMING_VERBS = {"local", "global"}


def run(
    db: Session,
    dataset: Dataset,
    text: str,
    record_it: bool = True,
    locals_: dict[str, str] | None = None,
    globals_: dict[str, str] | None = None,
) -> CommandResult:
    """Run one command against a dataset, and remember it if it changed anything.

    The engine works on a copy in a scratch workspace, so this loads one,
    applies the command and writes the result back - which is the in-place
    behaviour the dataset command box has always had, now expressed in terms
    of the same frame a project script uses.

    The two macro dictionaries are passed in rather than made here, because a
    macro has to outlive the command that defined it and every command gets
    its own Run. A caller with no interest in macros passes neither and gets a
    pair that lives for the one command.
    """
    # The variable rows are deleted and rebuilt by every command that changes
    # the data, so a second command in the same transaction would otherwise be
    # deciding against the list as it was before the first one ran.
    db.flush()
    db.refresh(dataset)

    named = dict(locals_ if locals_ is not None else {})
    wider = dict(globals_ if globals_ is not None else {})

    # A macro definition touches no data, so it neither loads the dataset nor
    # writes it back. Loading would refuse on a dataset still waiting for its
    # file, and writing would copy the whole parquet to say nothing changed.
    if text.strip().split(" ")[0].lower().rstrip(",") in NAMING_VERBS:
        result = apply(Run(db=db, work=None, locals=named, globals=wider), text)
    else:
        if not dataset_is_queryable(dataset):
            raise CommandError(f"'{dataset.name}' has no data to work on yet")
        with Workspace() as work:
            frame = load(work, dataset)
            frame.label_books = dict((dataset.meta or {}).get("label_books") or {})
            result = apply(
                Run(db=db, work=work, frame=frame, locals=named, globals=wider), text
            )
            if not result.reports_only:
                _store(db, dataset, frame)

    # Back into the caller's dictionaries, so the next command in the same
    # script can use what this one named.
    if locals_ is not None:
        locals_.update(named)
    if globals_ is not None:
        globals_.update(wider)

    if record_it and not result.reports_only:
        _remember(dataset, result.command)
    return result


def _store(db: Session, dataset: Dataset, frame: Frame) -> None:
    """Write the frame back over the dataset it was loaded from.

    The working file is already Parquet in the platform's own shape, so it is
    moved into the dataset's directory and described where it lands. Reading it
    into pandas and ingesting it again would re-derive what it already is, at
    the cost of a Python object per cell - on a census-sized file, the single
    most expensive thing the engine did.
    """
    destination = dataset_directory(dataset.id) / f"data-{uuid4().hex}.parquet"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(frame.path, destination)

    variables = variables_of(destination, dict(frame.labels), dict(frame.value_labels))
    _apply_ingest(
        db,
        dataset,
        IngestResult(
            parquet_path=destination,
            row_count=frame.rows,
            column_count=len(variables),
            file_size=destination.stat().st_size,
            variables=variables,
            warnings=[] if frame.rows else ["The data has no rows left in it."],
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

        def names() -> list[str]:
            return [name for name in run.data.variables if not name.endswith(MISSING_TAG_SUFFIX)]

        try:
            for step, where in _walk(_blocks(_lines(text)), run.locals, run.globals, names):
                try:
                    results.append(apply(run, step.text))
                except (CommandError, ExpressionError, FrameError) as exc:
                    raise _LineError(step.number, step.text, _within(str(exc), where)) from exc
        except _LineError as exc:
            error = ScriptError(exc.number, exc.line, str(exc), results)
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
    # One set of macros for the whole script, as the project runner has. Every
    # line here gets its own Run, so without this a name defined on one line
    # would be gone by the next.
    named: dict[str, str] = {}
    wider: dict[str, str] = {}

    def names() -> list[str]:
        db.flush()
        db.refresh(dataset)
        return [
            variable.name
            for variable in dataset.variables
            if not variable.name.endswith(MISSING_TAG_SUFFIX)
        ]

    try:
        for step, where in _walk(_blocks(_lines(text)), named, wider, names):
            try:
                results.append(run(db, dataset, step.text, locals_=named, globals_=wider))
            except (CommandError, ExpressionError, FrameError) as exc:
                raise _LineError(step.number, step.text, _within(str(exc), where)) from exc
    except _LineError as exc:
        raise ScriptError(exc.number, exc.line, str(exc), results) from exc
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


def commands(text: str) -> list[str]:
    """The commands in a script, as the runner will see them.

    The public name for the splitter below, so that anything counting or
    listing a script's commands uses the one definition of what a command is.
    A second opinion shows a number the run log never agrees with: a `//`
    line counted as a command, and one command written over four lines with
    `///` counted as four.
    """
    return _lines(text)


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


# --- loops ------------------------------------------------------------------
#
# `foreach v of varlist q1-q5 {` ... `}` and `forvalues i = 1/5 {` ... `}`.
# A loop is unrolled as it runs: each time round, the loop's name is set as a
# local and the lines inside are run as any others are, so `v' in them is
# whatever the loop is on. Its list is read when the loop is reached, not
# before - a varlist taken after the gen above it sees what the gen made.

LOOP_VERBS = ("foreach", "forvalues", "forval", "forv")

#: Most times one loop goes round. A typo in a range - 1/10000 for 1/10 -
#: would otherwise run the lines inside ten thousand times.
LOOP_LIMIT = 1000

FOREACH_HEAD = re.compile(
    r"^foreach\s+([A-Za-z_][A-Za-z0-9_]*)\s+(in|of)\s*(.*?)\s*\{$", re.IGNORECASE | re.DOTALL
)
FORVALUES_HEAD = re.compile(
    r"^(?:forvalues|forval|forv)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*\{$",
    re.IGNORECASE | re.DOTALL,
)
LOOP_NUMBER = r"-?(?:\d+\.?\d*|\.\d+)"


@dataclass
class _Step:
    """A command of the script, or a loop and the commands inside it.

    `number` is the command's place in the script, counted as the runner
    counts them, so an error names the line the editor marks.
    """

    number: int
    text: str
    body: list[_Step] | None = None


class _LineError(CommandError):
    """A command of the script failed, or a loop could not be read."""

    def __init__(self, number: int, line: str, message: str):
        super().__init__(message)
        self.number = number
        self.line = line


def _is_loop_head(line: str) -> bool:
    return line.split(" ", 1)[0].lower() in LOOP_VERBS and line.endswith("{")


def _blocks(lines: list[str]) -> list[_Step]:
    """The script's commands, with each loop's lines gathered under it."""
    top: list[_Step] = []
    open_: list[_Step] = []
    for number, line in enumerate(lines, start=1):
        into = open_[-1].body if open_ else top
        assert into is not None
        if line == "}":
            if not open_:
                raise _LineError(
                    number, line, "This } closes nothing: no foreach or forvalues is open above it"
                )
            open_.pop()
            continue
        if _is_loop_head(line):
            step = _Step(number, line, body=[])
            into.append(step)
            open_.append(step)
            continue
        into.append(_Step(number, line))
    if open_:
        raise _LineError(
            open_[-1].number,
            open_[-1].text,
            "This loop is never closed. End it with } on a line of its own",
        )
    return top


def _walk(
    steps: list[_Step],
    locals_: dict[str, str],
    globals_: dict[str, str],
    variables: Callable[[], list[str]],
) -> Iterator[tuple[_Step, tuple[str, ...]]]:
    """Each command in the order it runs, with what the loops around it are on."""
    for step in steps:
        if step.body is None:
            yield step, ()
            continue
        name, values = _loop_values(step, locals_, globals_, variables)
        had = locals_.get(name)
        try:
            for value in values:
                locals_[name] = value
                for inner, where in _walk(step.body, locals_, globals_, variables):
                    yield inner, (f"{name} is {value}", *where)
        finally:
            # The name means what it meant before the loop, once it is done.
            if had is None:
                locals_.pop(name, None)
            else:
                locals_[name] = had


def _within(message: str, where: tuple[str, ...]) -> str:
    return f"{message} (where {', '.join(where)})" if where else message


def _loop_values(
    step: _Step,
    locals_: dict[str, str],
    globals_: dict[str, str],
    variables: Callable[[], list[str]],
) -> tuple[str, list[str]]:
    """The loop's name, and what it goes round."""
    try:
        head = expand_macros(step.text, locals_, globals_).strip()
        name, values = _loop_head(head, locals_, globals_, variables)
    except (CommandError, ExpressionError, FrameError, MacroError) as exc:
        raise _LineError(step.number, step.text, str(exc)) from exc
    if len(values) > LOOP_LIMIT:
        raise _LineError(
            step.number,
            step.text,
            f"That loop would go round {len(values):,} times; a loop here goes round "
            f"at most {LOOP_LIMIT:,}",
        )
    return name, values


def _loop_head(
    head: str,
    locals_: dict[str, str],
    globals_: dict[str, str],
    variables: Callable[[], list[str]],
) -> tuple[str, list[str]]:
    found = FOREACH_HEAD.match(head)
    if found:
        name, how, listed = found.group(1), found.group(2).lower(), found.group(3).strip()
        if how == "in":
            return name, _words(listed)
        kind, _, rest = listed.partition(" ")
        kind = kind.lower()
        if kind in ("varlist", "var", "varl"):
            return name, _expand_varlist(variables(), rest)
        if kind in ("newlist", "new"):
            return name, _names_in(rest)
        if kind in ("local", "loc"):
            return name, _words(locals_.get(rest.strip(), ""))
        if kind in ("global", "glo"):
            return name, _words(globals_.get(rest.strip(), ""))
        if kind in ("numlist", "num"):
            return name, _numlist(rest)
        raise CommandError(
            f"foreach ... of takes varlist, newlist, local, global or numlist, not '{kind}'"
        )
    found = FORVALUES_HEAD.match(head)
    if found:
        return found.group(1), _range_values(found.group(2), backwards=False)
    raise CommandError(
        "A loop is written foreach v in a b c {, foreach v of varlist q1-q5 {, or "
        "forvalues i = 1/10 {"
    )


def _words(text: str) -> list[str]:
    """A list as Stata reads one: words, with "two words" in quotes as one."""
    try:
        return shlex.split(text)
    except ValueError as exc:
        raise CommandError(f"Could not read the list: {exc}") from exc


def _numlist(text: str) -> list[str]:
    values: list[str] = []
    for piece in re.split(r"[\s,]+", text.strip()):
        if piece:
            values += _range_values(piece, backwards=True)
            if len(values) > LOOP_LIMIT:
                break
    return values


def _range_values(text: str, backwards: bool) -> list[str]:
    """1/10, 0(5)100, 10(-1)1, or one number.

    A range that runs downwards with no step counts down in a numlist and
    runs no times in forvalues, as in Stata.
    """
    text = text.strip()
    single = re.fullmatch(LOOP_NUMBER, text)
    if single:
        return [_loop_number(float(text))]
    stepped = re.fullmatch(
        rf"({LOOP_NUMBER})\s*[(\[]\s*({LOOP_NUMBER})\s*[)\]]\s*({LOOP_NUMBER})", text
    )
    plain = re.fullmatch(rf"({LOOP_NUMBER})\s*/\s*({LOOP_NUMBER})", text)
    if stepped:
        start, step, stop = (float(stepped.group(k)) for k in (1, 2, 3))
    elif plain:
        start, stop = float(plain.group(1)), float(plain.group(2))
        step = -1.0 if backwards and start > stop else 1.0
    else:
        raise CommandError(
            f"'{text}' is not a range. Write 1/10, or 0(5)100 to count in fives"
        )
    if step == 0:
        raise CommandError(f"'{text}' steps by nothing, so it would never end")
    count = int((stop - start) / step + 1e-9) + 1
    if count <= 0:
        return []
    if count > LOOP_LIMIT:
        # Said by the caller in loop terms; the list itself need not be built.
        return [""] * (LOOP_LIMIT + 1)
    return [_loop_number(start + k * step) for k in range(count)]


def _loop_number(value: float) -> str:
    value = round(value, 10)
    return str(int(value)) if value.is_integer() else f"{value:.10g}"


def _expand_varlist(names: list[str], text: str) -> list[str]:
    """`q1-q5`, `inc*`, `q?_a`, names: the variables a varlist stands for."""
    found: list[str] = []
    for piece in re.split(r"\s+", text.strip()):
        if not piece:
            continue
        if "*" in piece or "?" in piece:
            pattern = re.compile(
                "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in piece)
            )
            matched = [name for name in names if pattern.fullmatch(name)]
            if not matched:
                raise CommandError(f"No variable matches {piece}")
            found += matched
        elif "-" in piece:
            first, _, last = piece.partition("-")
            if first not in names or last not in names:
                missing = first if first not in names else last
                raise CommandError(f"'{missing}' is not a variable in the data")
            start, end = names.index(first), names.index(last)
            if start > end:
                raise CommandError(f"{first} comes after {last} in the data, so {piece} is empty")
            found += names[start : end + 1]
        elif piece in names:
            found.append(piece)
        else:
            raise CommandError(f"'{piece}' is not a variable in the data")
    return list(dict.fromkeys(found))


# --- commands ---------------------------------------------------------------


def _expression_kinds(frame: Frame) -> dict[str, str]:
    """Each variable, as either a quantity or text.

    The expression translator needs this to order missing values: Stata puts a
    missing number above every number and a missing string, which is "", below
    every string, and arithmetic on text is a type mismatch rather than a join.

    Asked of the working file rather than of the variable rows, because the
    file is the only thing that cannot be stale or absent. A dataset ingested
    before `storage_type` was recorded carries an empty one, which reads as
    text, and `gen next = age + 1` on it would then be refused as arithmetic on
    text - or worse, before mixed addition was refused, written as "301".
    """
    stored = column_types(str(frame.path))
    kinds: dict[str, str] = {}
    for name, info in frame.variables.items():
        if name in stored:
            kinds[name] = "text" if kind_of(stored[name]) == "text" else "number"
        else:  # pragma: no cover - a variable the file does not carry
            kinds[name] = "number" if info.holds_numbers else "text"
    return kinds




def _local(run: Run, rest: str) -> CommandResult:
    """local <name> <text> - name a piece of script text for this run."""
    return _macro(run, rest, run.locals, "local", "`", "'")


def _global(run: Run, rest: str) -> CommandResult:
    """global <name> <text> - the same, in the namespace written as $name."""
    return _macro(run, rest, run.globals, "global", "$", "")


def _macro(
    run: Run,
    rest: str,
    among: dict[str, str],
    kind: str,
    open_: str,
    close: str,
) -> CommandResult:
    """Define one macro.

    Nothing is evaluated and nothing touches the data, so this is the one
    command that can run before a `use`. That matters: the conditions a script
    names are usually written at the top, above the first dataset it opens.
    """
    try:
        name, body, evaluated = define_macro(rest)
    except MacroError as exc:
        raise CommandError(str(exc)) from exc

    # A macro may be written in terms of ones already defined, and it is the
    # text at the time of definition that is stored - as in Stata, where a
    # later change to the inner macro does not reach back into this one.
    try:
        body = expand_macros(body, run.locals, run.globals)
    except MacroError as exc:
        raise CommandError(str(exc)) from exc

    among[name] = body
    shown = body if body else "nothing"
    message = f"{open_}{name}{close} stands for {shown}"
    if evaluated:
        # Stata would read observation 1 here and store a 0 or a 1, which is
        # how a condition becomes a constant without anybody noticing.
        message += " - the expression itself, not its value on the first row"
    return CommandResult(command="", message=message)


def _generate(run: Run, rest: str) -> CommandResult:
    frame, work = run.data, run.work
    name, expression, condition = _assignment(rest)
    _check_new_name(frame, name)
    ctx = frame.context
    window = _window(run)
    value = translate(expression, _expression_kinds(frame), quote_ident, window)
    where = _condition_sql(frame, condition, window)
    # Outside the if, the new variable is missing - which is what Stata does.
    column = f"CASE WHEN {where} THEN {value} ELSE NULL END" if where else value
    write(work, frame, _select_sql(frame, ctx, extra=[(name, _as_number(frame, column))]))
    return CommandResult(
        command="",
        message=f"Created {name}",
        variables_added=[name],
        changed_rows=frame.rows,
        data_changed=True,
    )


def _replace(run: Run, rest: str) -> CommandResult:
    frame, work = run.data, run.work
    name, expression, condition = _assignment(rest)
    ctx = frame.context
    if name not in ctx.variables:
        raise CommandError(f"'{name}' is not a variable in the data. Use gen to create it.")
    window = _window(run)
    value = translate(expression, _expression_kinds(frame), quote_ident, window)
    where = _condition_sql(frame, condition, window)
    column = f"CASE WHEN {where} THEN {value} ELSE {quote_ident(name)} END" if where else value

    changed = _count_matching(frame, where) if where else None
    write(work, frame, _select_sql(frame, ctx, replace={name: _as_number(frame, column)}))
    affected = changed if changed is not None else frame.rows
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
    # A `by` prefix in front of egen means what by() after it does.
    by = list(run.by.keys) if run.by is not None and not options else _by_variables(ctx, options)

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
        inner = translate(arguments, _expression_kinds(frame), quote_ident)
        over = f" OVER (PARTITION BY {', '.join(quote_ident(v) for v in by)})" if by else " OVER ()"
        column = f"{EGEN_AGGREGATES[function]}({inner}){over}"
    else:
        allowed = sorted(set(EGEN_AGGREGATES) | EGEN_ROWWISE | {"group", "tag"})
        raise CommandError(f"egen has no '{function}'. Available: {', '.join(allowed)}")

    write(work, frame, _select_sql(frame, ctx, extra=[(name, _as_number(frame, column))]))
    return CommandResult(
        command="",
        message=f"Created {name}" + (f" within {', '.join(by)}" if by else ""),
        variables_added=[name],
        changed_rows=frame.rows,
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
    write(work, frame, _select_sql(frame, ctx, rename={was: new}), renamed={was: new})
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
        where = _condition_sql(frame, rest[3:].strip(), _window(run))
        before = frame.rows
        write(work, frame, _select_sql(frame, ctx, where=f"NOT ({where}) OR ({where}) IS NULL"))
        return CommandResult(
            command="",
            message=f"Dropped {before - frame.rows:,} row(s)",
            changed_rows=before - frame.rows,
            data_changed=True,
        )

    names = _variable_list(ctx, rest)
    if not names:
        raise CommandError("drop needs variables, or an if condition")
    remaining = [v for v in ctx.variables if v not in names]
    if not remaining:
        raise CommandError("That would drop every variable in the data")
    write(work, frame, _select_sql(frame, ctx, only=remaining))
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
        where = _condition_sql(frame, rest[3:].strip(), _window(run))
        before = frame.rows
        write(work, frame, _select_sql(frame, ctx, where=where))
        return CommandResult(
            command="",
            message=f"Kept {frame.rows:,} row(s), dropped {before - frame.rows:,}",
            changed_rows=frame.rows,
            data_changed=True,
        )

    names = _variable_list(ctx, rest)
    if not names:
        raise CommandError("keep needs variables, or an if condition")
    dropped = [v for v in ctx.variables if v not in names]
    write(work, frame, _select_sql(frame, ctx, only=names))
    return CommandResult(
        command="",
        message=f"Kept {len(names)} variable(s), dropped {len(dropped)}",
        variables_removed=dropped,
        data_changed=True,
    )


# What destring will read as a number once spaces and ignored characters are
# gone: Stata's own notation, written out rather than left to a cast. DuckDB's
# cast also takes "inf", "nan" and "1_000", none of which Stata would call
# numeric, and a variable holding them would be converted here and refused in
# the do-file it came from.
NUMERIC_TEXT = r"[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?"
# What destring reads as missing: an empty string, and Stata's missing values.
MISSING_TEXT = r"\.[a-z]?"


def _destring(run: Run, rest: str) -> CommandResult:
    """destring [varlist], replace | generate(newvars) [force ignore("chars") percent dpcomma].

    Text that holds numbers - an export that wrote every column as a string,
    or a code read in with its leading zeros - becomes a number, so it can be
    summed, compared and charted as one.

    Stata's rules, because the do-file is the reference: a variable is
    converted only when every value is a number, blank or a missing value. One
    that holds anything else is left as it is and said so, and the command
    goes on to the next - unless `force`, which makes those values missing. A
    variable that is already a number is passed over rather than refused, so
    `destring, replace` over the whole dataset does what it says.
    """
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    # Read before anything else looks at the options: the characters to ignore
    # are quoted and can be anything, a comma or a bracket included.
    ignore = ""
    quoted = re.search(r'\bignore\s*\(\s*"([^"]*)"\s*\)', options, re.IGNORECASE)
    if quoted is not None:
        ignore = quoted.group(1)
        options = options[: quoted.start()] + options[quoted.end() :]
    elif re.search(r"\bignore\b", options, re.IGNORECASE):
        raise CommandError('ignore() takes the characters in quotes, e.g. ignore(",$")')
    # ignore() was taken out above, quoted characters and all.
    _reject_unknown_options(
        options, tuple(one for one in OPTIONS["destring"] if one != "ignore")
    )
    flags = {word.lower() for word in re.findall(r"[A-Za-z]+", re.sub(r"\([^)]*\)", " ", options))}
    generated = re.search(r"\b(?:generate|gen|g)\s*\(([^)]*)\)", options, re.IGNORECASE)
    replacing = "replace" in flags
    if replacing == (generated is not None):
        raise CommandError(
            "destring needs either replace or generate(), e.g. destring age, replace"
        )

    ctx = frame.context
    # No variables means every one of them, as in Stata - but not the hidden
    # columns recording which blanks were .a and which .b. They are text that
    # looks like missing values, so they would convert cleanly and lose the
    # very tags they exist to keep.
    names = (
        _variable_list(ctx, body)
        if body
        else [name for name in ctx.variables if not name.endswith(MISSING_TAG_SUFFIX)]
    )
    new_names = _names_in(generated.group(1)) if generated else []
    if generated and len(new_names) != len(names):
        raise CommandError(
            f"generate() needs one new name for each variable: {len(names)} "
            f"variable(s), {len(new_names)} name(s)"
        )
    for new in new_names:
        _check_new_name(frame, new)
    # Where each variable's numbers go: over itself, or into its new name.
    target = dict(zip(names, new_names, strict=True)) if generated else {n: n for n in names}

    kinds = _expression_kinds(frame)
    notes: list[str] = []
    texts = [name for name in names if kinds.get(name) == "text"]
    for name in names:
        if kinds.get(name) != "text" and body:
            # Named, so worth a word. Over the whole dataset this is most of
            # the variables and saying so for each would bury what happened.
            notes.append(f"{name}: already numeric; left alone")
    if not texts:
        return CommandResult(
            command="",
            message="; ".join(notes) or "Nothing to do: every variable is already numeric",
        )

    cleaned = {name: _destring_cleaned(name, ignore, "percent" in flags, "dpcomma" in flags)
               for name in texts}
    bad = {
        name: f"NOT (regexp_full_match({text}, '{NUMERIC_TEXT}') "
        f"OR regexp_full_match({text}, '{MISSING_TEXT}') OR {text} = '')"
        for name, text in cleaned.items()
    }
    counts = dict(zip(texts, _destring_counts(frame, bad), strict=True))

    force = "force" in flags
    converting: dict[str, str] = {}
    for name in texts:
        if counts[name] and not force:
            notes.append(
                f"{name}: contains nonnumeric characters, such as "
                f"{_destring_examples(frame, name, bad[name])}; left as text"
            )
            continue
        number = (
            f"CASE WHEN regexp_full_match({cleaned[name]}, '{NUMERIC_TEXT}') "
            f"THEN CAST({cleaned[name]} AS DOUBLE) END"
        )
        if "percent" in flags:
            number = f"({number}) / 100"
        converting[name] = number
        made_missing = (
            f" ({counts[name]:,} nonnumeric value(s) made missing)" if counts[name] else ""
        )
        done = "replaced" if replacing else f"generated {target[name]}"
        notes.append(f"{name}: {done} as numeric{made_missing}")

    if not converting:
        return CommandResult(command="", message="; ".join(notes))

    if replacing:
        write(work, frame, _select_sql(frame, ctx, replace=converting))
        added: list[str] = []
    else:
        added = [target[name] for name in converting]
        # The new variable carries the old one's label, as Stata's does.
        for name in converting:
            if frame.label_of(name):
                frame.labels[target[name]] = frame.label_of(name)
        extra = [(target[name], number) for name, number in converting.items()]
        write(work, frame, _select_sql(frame, ctx, extra=extra))
    return CommandResult(
        command="",
        message="; ".join(notes),
        variables_added=added,
        changed_rows=frame.rows,
        data_changed=True,
    )


def _destring_cleaned(name: str, ignore: str, percent: bool, dpcomma: bool) -> str:
    """The SQL for a variable's text as destring reads it.

    Each ignored character is removed wherever it is, which is how Stata reads
    ignore(",") on "1,234". Written into the query as literals, quotes
    doubled, since the characters are the only part of the command that is
    neither a name nor a number.
    """
    text = f"TRIM(CAST({quote_ident(name)} AS VARCHAR))"
    for character in dict.fromkeys(ignore + ("%" if percent else "")):
        text = f"REPLACE({text}, '{character.replace(chr(39), chr(39) * 2)}', '')"
    if dpcomma:
        text = f"REPLACE({text}, ',', '.')"
    # Trimmed again: ignoring a currency sign leaves the space after it.
    return f"COALESCE(TRIM({text}), '')"


def _destring_counts(frame: Frame, bad: dict[str, str]) -> list[int]:
    """How many values of each variable are not numbers, in one scan."""
    counted = ", ".join(f"COUNT(*) FILTER (WHERE {condition})" for condition in bad.values())
    _, rows = run_sql(f"SELECT {counted} FROM read_parquet({_quote_path(str(frame.path))})")
    return [int(value or 0) for value in rows[0]] if rows else [0] * len(bad)


def _destring_examples(frame: Frame, name: str, condition: str) -> str:
    """A few of the values that stopped a conversion, so they can be found."""
    _, rows = run_sql(
        f"SELECT DISTINCT {quote_ident(name)} FROM read_parquet({_quote_path(str(frame.path))}) "
        f"WHERE {condition} LIMIT 3"
    )
    return ", ".join(f'"{row[0]}"' for row in rows)


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
    existing = _lookup(run, name) or _owned_elsewhere(run, name)
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
        where = ""
        if existing.project_id != run.project_id:
            # Said out loud. A script writing into another project is right
            # here - it built this dataset and somebody moved it there to be
            # read - but it is not what the line appears to say, and a log
            # that does not mention it leaves the reader to find out later.
            moved_to = run.db.get(Project, existing.project_id)
            where = f", which now lives in {moved_to.name}" if moved_to else ""
        return CommandResult(
            command="",
            message=f"Saved {frame.rows:,} row(s) over {name}{where}",
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


def _owned_elsewhere(run: Run, name: str) -> Dataset | None:
    """A dataset this script built that now lives in another project.

    A script writes into its own project and reads from it, so the only way
    one project's script feeds another's is for somebody to move the output
    across afterwards - which is the documented way to build a cleaned file
    in one project and report on it in the next.

    Without this, the move quietly broke the arrangement. `save as
    clean_people` looked for the name among its own project's datasets, found
    nothing where there had been something, and made a *second* clean_people
    back where the script lives. The reader went on reading the copy that
    moved, which nothing updated again: a script reporting success on every
    line and a table that stopped changing.

    Two things have to be true, not one. `owns` says this script built it,
    which is authorship and nothing more - it is read off what a past run
    saved and nobody agreed to it. The permission is the move: moving a
    dataset needs the manager role on both projects, so whoever moved it is
    entitled to say that this project's script may write into that one, and
    that is recorded on the dataset at the time. Without the second half, a
    manager of the source project who has no rights at all over the
    destination could overwrite a dataset there by running their own script.
    """
    # Imported here rather than at the top: project_script imports this
    # module, so naming it up there is a cycle.
    from app.services import archive, project_script

    if not run.owns:
        return None
    wanted = name.strip().lower()
    datasets = (
        run.db.execute(select(Dataset).where(Dataset.id.in_(run.owns))).scalars().all()
    )
    for dataset in datasets:
        if dataset.name.lower() != wanted and (dataset.slug or "").lower() != wanted:
            continue
        if dataset.project_id == run.project_id:
            return dataset
        if not project_script.may_rebuild(dataset, run.project_id):
            raise CommandError(
                f"'{name}' was built by this script and now lives in another "
                "project, which has not agreed to this script writing there. "
                "Move it across again to say so, or save under another name."
            )
        destination = run.db.get(Project, dataset.project_id)
        if archive.is_archived(destination):
            # An archived project keeps its dataset rows and loses their data.
            # Writing here would leave it holding live data again, which is
            # the half-unarchived state every other path refuses to create.
            raise CommandError(
                f"'{name}' now lives in '{destination.name}', which is "
                "archived, so there is nowhere to write it. Unarchive that "
                "project first."
            )
        return dataset
    return None


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
    _reject_unknown_options(options, OPTIONS["merge"])
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
    counts = _merge_counts(sql)
    if not generate:
        # The verdict was only ever there to be counted.
        sql = f'SELECT * EXCLUDE ("_merge") FROM ({sql})'

    _carry_labels(frame, other, carried)
    write(work, frame, sql)
    # The data is no longer the dataset it was loaded from, so a bare `save`
    # has nothing to write back over and will ask for a name.
    frame.origin = None
    frame.name = f"{frame.name} + {other.name}"

    return CommandResult(
        command="",
        message=_merge_message(other.name, frame.rows, counts, shadowed, generate),
        variables_added=(["_merge"] if generate else []) + carried,
        changed_rows=frame.rows,
        data_changed=True,
    )


def _merge_counts(sql: str) -> dict[int, int]:
    """How many rows came from each side, counted where the join is.

    One aggregate pass over the join rather than a copy of the whole of it in
    Python. The only column it asks for is the verdict, so DuckDB reads the two
    key columns and the sentinels and skips the rest of both files.
    """
    _, rows = run_sql(f'SELECT "_merge", COUNT(*) FROM ({sql}) GROUP BY 1')
    found = {int(row[0]): int(row[1]) for row in rows}
    return {code: found.get(code, 0) for code in (MASTER_ONLY, USING_ONLY, MATCHED)}


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

    here_types = column_types(str(frame.path))
    there_types = column_types(str(other.storage_path))
    clashes = sorted(
        name
        for name, kind in there_types.items()
        if name in here_types and not compatible(kind_of(here_types[name]), kind_of(kind))
    )
    if clashes:
        name = clashes[0]
        raise CommandError(
            f"'{name}' is {kind_of(here_types[name])} here and "
            f"{kind_of(there_types[name])} in '{other.name}', so the rows "
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
    _carry_labels(frame, other, [name for name in there if not frame.has(name)])
    write(work, frame, sql)
    frame.origin = None
    frame.name = f"{frame.name} + {other.name}"

    return CommandResult(
        command="",
        message=(
            f"Appended {other.name}: {frame.rows:,} row(s), "
            f"{before:,} from here and {frame.rows - before:,} from there"
        ),
        changed_rows=frame.rows - before,
        data_changed=True,
    )


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
    _reject_unknown_options(options, OPTIONS["collapse"])

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
    before = frame.rows
    # The summaries are new numbers, so a label saying what the column held
    # one row at a time no longer describes it.
    kept = set(by)
    frame.labels = {name: text for name, text in frame.labels.items() if name in kept}
    frame.value_labels = {
        name: pairs for name, pairs in frame.value_labels.items() if name in kept
    }
    write(work, frame, sql)
    frame.origin = None
    frame.name = f"{frame.name} collapsed"

    how = ", ".join(f"{stat} of {name}" for stat, name in wanted)
    where = f" by {', '.join(by)}" if by else ""
    return CommandResult(
        command="",
        message=f"Collapsed {before:,} row(s) to {frame.rows:,}{where}: {how}",
        changed_rows=frame.rows,
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
    before = frame.rows
    kept = set(names)
    frame.labels = {name: text for name, text in frame.labels.items() if name in kept}
    frame.value_labels = {
        name: pairs for name, pairs in frame.value_labels.items() if name in kept
    }
    write(work, frame, sql)
    frame.origin = None
    frame.name = f"{frame.name} counted"

    return CommandResult(
        command="",
        message=(
            f"Counted {before:,} row(s) into {frame.rows:,} combination(s) of "
            f"{', '.join(names)}, in _freq"
        ),
        variables_added=["_freq"],
        changed_rows=frame.rows,
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


# --- order ------------------------------------------------------------------


def _order_terms(frame: Frame, keys: list[tuple[str, bool]]) -> list[str]:
    """ORDER BY terms for these variables, missing where Stata puts it.

    A missing number is above every number, so last on the way up; a missing
    string is "", below every string, so first. Going down, missing is last
    either way, which is where gsort leaves it. `keys` are the variables and
    whether each runs downwards.
    """
    kinds = _expression_kinds(frame)
    terms: list[str] = []
    for name, down in keys:
        column = quote_ident(name)
        if down:
            terms.append(f"{column} DESC NULLS LAST")
        elif kinds.get(name) == "text":
            terms.append(f"{column} ASC NULLS FIRST")
        else:
            terms.append(f"{column} ASC NULLS LAST")
    return terms


def _sort_frame(run: Run, keys: list[tuple[str, bool]]) -> None:
    """Put the rows in order, and keep them there.

    Ties keep the order they had, so sorting by region after sorting by age
    leaves each region's rows in age order, which is what people expect of a
    sort whether or not they asked for a stable one.
    """
    frame, work = run.data, run.work
    selected = ", ".join(quote_ident(name) for name in frame.variables)
    ordering = [*_order_terms(frame, keys), quote_ident(ROW_ORDER)]
    write(work, frame, f"SELECT {selected} FROM {_numbered(frame)} ORDER BY {', '.join(ordering)}")


def _sort(run: Run, rest: str) -> CommandResult:
    """sort <variables> - the rows in order of these, smallest first."""
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["sort"])
    names = _variable_list(run.data.context, body)
    if not names:
        raise CommandError("sort needs the variables to sort by: sort hhid line")
    _sort_frame(run, [(name, False) for name in names])
    return CommandResult(
        command="",
        message=f"Sorted {run.data.rows:,} row(s) by {', '.join(names)}",
        data_changed=True,
    )


def _gsort(run: Run, rest: str) -> CommandResult:
    """gsort -<variable> +<variable> ... - sort, each one up or down."""
    body, options = _split_options(rest)
    _reject_unknown_options(options, ())
    if not re.fullmatch(r"(\s*[+-]?\s*[A-Za-z_][A-Za-z0-9_]*)+\s*", body):
        raise CommandError(
            "gsort takes variables, each with - in front to sort it largest first: "
            "gsort province -income"
        )
    keys = [
        (name, sign == "-")
        for sign, name in re.findall(r"([+-]?)\s*([A-Za-z_][A-Za-z0-9_]*)", body)
    ]
    _variable_list(run.data.context, " ".join(name for name, _ in keys))
    _sort_frame(run, keys)
    shown = ", ".join(f"{name} (largest first)" if down else name for name, down in keys)
    return CommandResult(
        command="",
        message=f"Sorted {run.data.rows:,} row(s) by {shown}",
        data_changed=True,
    )


def _order(run: Run, rest: str) -> CommandResult:
    """order <variables> [, first | last | before(<v>) | after(<v>)] - move columns."""
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["order"])
    ctx = frame.context
    moved = _variable_list(ctx, body)
    if not moved:
        raise CommandError("order needs the variables to move: order hhid line age")
    flags = _option_words(options)
    before = re.search(r"\bbefore\s*\(([^)]*)\)", options, re.IGNORECASE)
    after = re.search(r"\bafter\s*\(([^)]*)\)", options, re.IGNORECASE)
    if sum(bool(one) for one in ("first" in flags, "last" in flags, before, after)) > 1:
        raise CommandError("order takes one of first, last, before() and after()")

    others = [name for name in ctx.variables if name not in moved]
    if before or after:
        anchors = _variable_list(ctx, (before or after).group(1))  # type: ignore[union-attr]
        if len(anchors) != 1:
            raise CommandError("before() and after() name one variable to place them by")
        anchor = anchors[0]
        if anchor in moved:
            raise CommandError(f"{anchor} is one of the variables being moved")
        at = others.index(anchor) + (1 if after else 0)
        names = others[:at] + moved + others[at:]
        where = f"{'after' if after else 'before'} {anchor}"
    elif "last" in flags:
        names = others + moved
        where = "to the end"
    else:
        names = moved + others
        where = "to the front"
    write(work, frame, _select_sql(frame, ctx, only=names))
    return CommandResult(
        command="", message=f"Moved {', '.join(moved)} {where}", data_changed=True
    )


# --- checks and reports -----------------------------------------------------
#
# These look and change nothing. Their answer is the message: a count, a
# table, or - for assert - a stop, so a script that builds on a wrong
# assumption halts on the line that checks it instead of saving a bad file.


def _assert(run: Run, rest: str) -> CommandResult:
    """assert <expression> [if <condition>] - stop the script unless it holds."""
    frame = run.data
    expression, condition = _split_if(rest)
    if not expression:
        raise CommandError("assert needs something to check, e.g. assert age >= 0")
    window = _window(run)
    check = translate(expression, _expression_kinds(frame), quote_ident, window)
    # A number is true where it is not zero, and a missing number is not
    # zero - Stata's rule. A comparison that cannot be decided is not true.
    held = (
        f"COALESCE({check}, FALSE)"
        if _is_boolean(frame, check)
        else f"COALESCE(({check}) <> 0, TRUE)"
    )
    where = _condition_sql(frame, condition, window)
    within = f", COALESCE({where}, FALSE) AS __within" if where else ""
    marked = (
        f"(SELECT {quote_ident(ROW_ORDER)} AS __at, {held} AS __held{within} "
        f"FROM {_numbered(frame)})"
    )
    scope = " WHERE __within" if where else ""
    _, rows = run_sql(
        f"SELECT COUNT(*) FILTER (WHERE NOT __held), COUNT(*) FROM {marked}{scope}"
    )
    failed, total = (int(rows[0][0] or 0), int(rows[0][1] or 0)) if rows else (0, 0)
    among = f" where {condition}" if condition else ""
    if failed:
        _, first = run_sql(
            f"SELECT __at FROM {marked}{scope}{' AND' if where else ' WHERE'} NOT __held "
            f"ORDER BY __at LIMIT 5"
        )
        at = ", ".join(f"{int(row[0]):,}" for row in first)
        raise CommandError(
            f"Assertion is false in {failed:,} of {total:,} row(s){among}: {expression}. "
            f"First at row {at}"
        )
    return CommandResult(
        command="",
        message=f"Assertion is true in all {total:,} row(s){among}",
        reports_only=True,
    )


def _count(run: Run, rest: str) -> CommandResult:
    """count [if <condition>] - how many rows, or how many meet a condition."""
    frame = run.data
    body, condition = _split_if(rest)
    if body:
        raise CommandError("count takes only an if condition: count if age >= 18")
    if not condition:
        return CommandResult(command="", message=f"{frame.rows:,} row(s)", reports_only=True)
    found = _count_matching(frame, _condition_sql(frame, condition, _window(run)))
    return CommandResult(
        command="",
        message=f"{found:,} of {frame.rows:,} row(s) where {condition}",
        reports_only=True,
    )


#: Most variables a summarize lays out at once.
SUMMARY_LIMIT = 200


def _summarize(run: Run, rest: str) -> CommandResult:
    """summarize [<variables>] [if <condition>] [, detail] - the numbers at a glance."""
    frame = run.data
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["summarize"])
    detail = "detail" in _option_words(options)
    names_text, condition = _split_if(body)
    ctx = frame.context
    kinds = _expression_kinds(frame)
    named = (
        _variable_list(ctx, names_text)
        if names_text
        else [name for name in ctx.variables if not name.endswith(MISSING_TAG_SUFFIX)]
    )
    numbers = [name for name in named if kinds.get(name) == "number"]
    if not numbers:
        raise CommandError(
            "There is nothing to summarize: "
            + ("those are text. Try tabulate." if names_text else "no variable holds numbers.")
        )
    left_out = len(numbers) - SUMMARY_LIMIT
    numbers = numbers[:SUMMARY_LIMIT]

    where = _condition_sql(frame, condition, _window(run))
    statistics = ["COUNT({v})", "AVG({v})", "STDDEV_SAMP({v})", "MIN({v})"]
    if detail:
        statistics += ["QUANTILE_CONT({v}, 0.25)", "MEDIAN({v})", "QUANTILE_CONT({v}, 0.75)"]
    statistics.append("MAX({v})")
    columns = [
        statistic.format(v=f"TRY_CAST({quote_ident(name)} AS DOUBLE)")
        for name in numbers
        for statistic in statistics
    ]
    _, rows = run_sql(f"SELECT {', '.join(columns)} FROM {_rows_where(frame, where)}")
    values = list(rows[0]) if rows else [None] * len(columns)

    head = ["Variable", "Obs", "Mean", "Std. dev.", "Min"]
    if detail:
        head += ["p25", "Median", "p75"]
    head.append("Max")
    body_rows = []
    for index, name in enumerate(numbers):
        found = values[index * len(statistics) : (index + 1) * len(statistics)]
        body_rows.append(
            [_cell(name), f"{int(found[0] or 0):,}", *(_figure(one) for one in found[1:])]
        )
    message = _grid(head, body_rows)
    texts = [name for name in named if kinds.get(name) != "number"]
    if texts and names_text:
        message += f"\n\nLeft out, as text: {', '.join(texts)}"
    if left_out > 0:
        message += f"\n\n...and {left_out:,} more numeric variable(s), not shown"
    if condition:
        message = f"Where {condition}\n\n{message}"
    return CommandResult(command="", message=message, reports_only=True)


#: How much of a frequency table the log shows.
TABLE_ROWS = 200
TABLE_COLUMNS = 20


def _tabulate(run: Run, rest: str) -> CommandResult:
    """tabulate <variable> [<variable>] [if <condition>] [, missing] - frequencies."""
    frame = run.data
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["tabulate"])
    with_missing = "missing" in _option_words(options)
    names_text, condition = _split_if(body)
    names = _variable_list(frame.context, names_text)
    if len(names) not in (1, 2):
        raise CommandError(
            "tabulate takes one variable, or two for a cross-table: tab region sex"
        )
    kinds = _expression_kinds(frame)
    where = _condition_sql(frame, condition, _window(run))
    source = _rows_where(frame, where)
    present = [
        f"{quote_ident(name)} IS NOT NULL"
        + (f" AND {quote_ident(name)} <> ''" if kinds.get(name) == "text" else "")
        for name in names
    ]
    keep = "" if with_missing else f" WHERE {' AND '.join(present)}"
    grouped = ", ".join(quote_ident(name) for name in names)
    _, rows = run_sql(
        f"SELECT {grouped}, COUNT(*) FROM {source}{keep} GROUP BY {grouped}"
    )
    if not rows:
        among = f" where {condition}" if condition else ""
        return CommandResult(command="", message=f"No observations{among}", reports_only=True)

    def shown(name: str, value: Any) -> str:
        labels = frame.value_labels.get(name) or {}
        if value is not None and labels:
            key = str(value) if kinds.get(name) == "text" else numeric_code_text(value)
            if key in labels:
                return _cell(labels[key])
        return _cell(_value_text(value))

    message = (
        _one_way(names[0], rows, shown)
        if len(names) == 1
        else _two_way(names[0], names[1], rows, shown)
    )
    if condition:
        message = f"Where {condition}\n\n{message}"
    return CommandResult(command="", message=message, reports_only=True)


def _in_order(value: Any) -> tuple[bool, Any]:
    """Values smallest first, missing last."""
    return (value is None, value if value is not None else 0)


def _one_way(name: str, rows: list[Any], shown: Any) -> str:
    counted = sorted(((row[0], int(row[1])) for row in rows), key=lambda one: _in_order(one[0]))
    total = sum(count for _, count in counted)
    body: list[list[str]] = []
    running = 0
    for value, count in counted[:TABLE_ROWS]:
        running += count
        body.append(
            [shown(name, value), f"{count:,}", f"{100 * count / total:.2f}",
             f"{100 * running / total:.2f}"]
        )
    table = _grid(
        [_cell(name), "Freq.", "Percent", "Cum."], body, ["Total", f"{total:,}", "100.00", ""]
    )
    if len(counted) > TABLE_ROWS:
        table += f"\n\n...and {len(counted) - TABLE_ROWS:,} more value(s), not shown"
    return table


def _two_way(down: str, across: str, rows: list[Any], shown: Any) -> str:
    columns = sorted({row[1] for row in rows}, key=_in_order)
    if len(columns) > TABLE_COLUMNS:
        raise CommandError(
            f"{across} has {len(columns):,} values, more than the {TABLE_COLUMNS} columns "
            f"a table here shows. Put the variable with fewer values second: "
            f"tab {across} {down}"
        )
    cells: dict[Any, dict[Any, int]] = {}
    for row in rows:
        cells.setdefault(row[0], {})[row[1]] = int(row[2])
    lines = sorted(cells, key=_in_order)
    body = [
        [shown(down, value), *(f"{cells[value].get(c, 0):,}" for c in columns),
         f"{sum(cells[value].values()):,}"]
        for value in lines[:TABLE_ROWS]
    ]
    totals = [sum(cells[value].get(c, 0) for value in lines) for c in columns]
    table = _grid(
        [_cell(down), *(shown(across, c) for c in columns), "Total"],
        body,
        ["Total", *(f"{one:,}" for one in totals), f"{sum(totals):,}"],
        caption=across,
        total_column=True,
    )
    if len(lines) > TABLE_ROWS:
        table += f"\n\n...and {len(lines) - TABLE_ROWS:,} more row(s), not shown"
    return table


def _grid(
    head: list[str],
    body: list[list[str]],
    foot: list[str] | None = None,
    *,
    caption: str = "",
    total_column: bool = False,
) -> str:
    """A table for the log, laid out the way Stata prints one.

    The first column names the row and stands against a bar; the figures are
    right-aligned so their digits line up. `foot` is a totals row under a
    rule, and `total_column` sets the last column off with a second bar, as a
    cross-table's row totals are.
    """
    every = [head, *body, *([foot] if foot else [])]
    widths = [max(len(row[k]) for row in every) for k in range(len(head))]
    widths = [width if k == 0 else max(width, 7) for k, width in enumerate(widths)]

    def line(row: list[str]) -> str:
        cells = [cell.rjust(widths[k]) for k, cell in enumerate(row)]
        figures = cells[1:]
        if total_column and len(figures) > 1:
            middle = "   ".join(figures[:-1]) + " | " + figures[-1]
        else:
            middle = "   ".join(figures)
        return f"{cells[0]} | {middle}".rstrip()

    top = line(head)
    rule = re.sub(r"[^|]", "-", top).replace("|", "+")
    out = []
    if caption:
        out.append(f"{' ' * widths[0]} | {caption}")
    out += [top, rule, *(line(row) for row in body)]
    if foot:
        out += [rule, line(foot)]
    return "\n".join(out)


def _cell(text: str, limit: int = 28) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _value_text(value: Any) -> str:
    """A value as the log shows it: a code as a code, not 1.0 or 2,024."""
    if value is None:
        return "."
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if value != value:
            return "."
        return str(int(value)) if value.is_integer() else f"{value:.6g}"
    if isinstance(value, str):
        return value if value else '""'
    return str(value)


def _figure(value: Any) -> str:
    """A statistic as the log shows it, to about four figures."""
    if value is None:
        return "."
    number = float(value)
    if number != number:
        return "."
    if number.is_integer() and abs(number) < 1e15:
        return f"{int(number):,}"
    if abs(number) >= 1000:
        return f"{number:,.1f}"
    return f"{number:.4g}"


# --- duplicates -------------------------------------------------------------


def _duplicates(run: Run, rest: str) -> CommandResult:
    """duplicates report|tag|drop [<variables>] [, generate(<name>) force].

    Rows are duplicates when they agree on the variables named, or on every
    variable when none are. Missing agrees with missing, as in Stata.
    """
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["duplicates"])
    kind, _, names_text = body.partition(" ")
    kind = kind.lower()
    if kind not in ("report", "tag", "drop"):
        raise CommandError(
            "duplicates takes report, tag or drop: duplicates report hhid, or "
            "duplicates drop"
        )
    ctx = frame.context
    named = bool(names_text.strip())
    names = _variable_list(ctx, names_text) if named else list(ctx.variables)
    terms = f"in terms of {', '.join(names)}" if named else "in terms of all variables"
    partition = ", ".join(quote_ident(name) for name in names)

    if kind == "report":
        _, rows = run_sql(
            f"SELECT __copies, COUNT(*) FROM (SELECT COUNT(*) OVER (PARTITION BY {partition}) "
            f"AS __copies FROM read_parquet({_quote_path(str(frame.path))})) "
            f"GROUP BY 1 ORDER BY 1"
        )
        if all(int(row[0]) == 1 for row in rows):
            return CommandResult(
                command="", message=f"No duplicates {terms}", reports_only=True
            )
        table = _grid(
            ["Copies", "Observations", "Surplus"],
            [
                [f"{int(copies):,}", f"{int(count):,}",
                 f"{int(count) - int(count) // int(copies):,}"]
                for copies, count in rows
            ],
        )
        return CommandResult(
            command="", message=f"Duplicates {terms}\n\n{table}", reports_only=True
        )

    if kind == "tag":
        generated = re.search(r"\b(?:generate|gen|g)\s*\(([^)]*)\)", options, re.IGNORECASE)
        if generated is None or not generated.group(1).strip():
            raise CommandError(
                "duplicates tag needs a name for the tag: duplicates tag hhid, generate(dup)"
            )
        new = generated.group(1).strip()
        _check_new_name(frame, new)
        column = f"COUNT(*) OVER (PARTITION BY {partition}) - 1"
        write(work, frame, _select_sql(frame, ctx, extra=[(new, column)]))
        tagged = _count_matching(frame, f"{quote_ident(new)} > 0")
        return CommandResult(
            command="",
            message=(
                f"Created {new}: {tagged:,} row(s) have at least one duplicate {terms}; "
                f"{new} says how many"
            ),
            variables_added=[new],
            changed_rows=frame.rows,
            data_changed=True,
        )

    if named and "force" not in _option_words(options):
        raise CommandError(
            f"Dropping duplicates in terms of {', '.join(names)} keeps the first row of "
            f"each and loses whatever the others held in their other variables. Add "
            f"force to say that is meant: duplicates drop {names_text.strip()}, force"
        )
    before = frame.rows
    first = (
        f"ROW_NUMBER() OVER (PARTITION BY {partition} ORDER BY {quote_ident(ROW_ORDER)}) = 1"
    )
    write(work, frame, _select_sql(frame, ctx, where=first))
    dropped = before - frame.rows
    return CommandResult(
        command="",
        message=(
            f"Dropped {dropped:,} duplicate row(s) {terms}, keeping the first of each"
            if dropped
            else f"No duplicates {terms}; nothing dropped"
        ),
        changed_rows=dropped,
        data_changed=bool(dropped),
    )


# --- recode -----------------------------------------------------------------

RULE_NUMBER = r"-?(?:\d+\.?\d*|\.\d+)"


@dataclass
class _Rule:
    """One bracket of a recode: the old values, and what they become."""

    tests: list[tuple[str, ...]]
    value: float | None
    label: str | None
    written: str


def _recode(run: Run, rest: str) -> CommandResult:
    """recode <variables> (rule) [(rule)...] [if <condition>] [, generate() prefix()].

    Each rule says which old values become which new one: (1 2 = 0), (3/5 =
    1), (min/0 = .), (missing = 9), (else = 0), with a label in quotes after
    the new value if it wants one. The first rule a value fits is the one it
    takes, as in Stata, and a value no rule fits is left as it was.
    """
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["recode"])
    head, condition = _split_if(body)
    start = head.find("(")
    if start < 0:
        raise CommandError("recode needs rules in brackets: recode q5 (1 2 = 1) (3 4 5 = 0)")
    ctx = frame.context
    names = _variable_list(ctx, head[:start])
    if not names:
        raise CommandError("recode needs the variables to recode, before the rules")
    rules = [_recode_rule(text) for text in _recode_rules(head[start:])]
    _check_rule_order(rules)

    kinds = _expression_kinds(frame)
    for name in names:
        if kinds.get(name) != "number":
            raise CommandError(
                f"recode works on numbers, and {name} is text. Use replace for text, "
                f"or encode to number its values first"
            )

    generated = re.search(r"\b(?:generate|gen|g)\s*\(([^)]*)\)", options, re.IGNORECASE)
    prefix = re.search(r"\bprefix\s*\(([^)]*)\)", options, re.IGNORECASE)
    if generated and prefix:
        raise CommandError("recode takes generate() or prefix(), not both")
    if generated:
        targets = _names_in(generated.group(1))
        if len(targets) != len(names):
            raise CommandError(
                f"generate() needs one new name for each variable: {len(names)} "
                f"variable(s), {len(targets)} name(s)"
            )
    elif prefix:
        targets = [prefix.group(1).strip() + name for name in names]
    else:
        targets = list(names)
    in_place = targets == names
    if not in_place:
        for target in targets:
            _check_new_name(frame, target)

    bounds = _recode_bounds(frame, names, rules)
    where = _condition_sql(frame, condition, _window(run))
    cases: dict[str, str] = {}
    for name in names:
        column = quote_ident(name)
        case = _recode_case(column, rules, bounds.get(name, (None, None)))
        if where:
            # Outside the if, a variable recoded in place keeps its value and
            # a new one is missing - Stata's rule for both.
            outside = column if in_place else "NULL"
            case = f"CASE WHEN COALESCE({where}, FALSE) THEN {case} ELSE {outside} END"
        cases[name] = case

    # How many values change, counted before they do.
    marked = ", ".join(
        f"{case} AS {quote_ident(f'__new{k}')}" for k, case in enumerate(cases.values())
    )
    counted = ", ".join(
        f"SUM(CASE WHEN {quote_ident(f'__new{k}')} IS DISTINCT FROM {quote_ident(name)} "
        f"THEN 1 ELSE 0 END)"
        for k, name in enumerate(names)
    )
    _, rows = run_sql(f"SELECT {counted} FROM (SELECT *, {marked} FROM {_numbered(frame)})")
    changes = [int(one or 0) for one in rows[0]] if rows else [0] * len(names)

    pairs = {
        numeric_code_text(rule.value): rule.label
        for rule in rules
        if rule.label is not None and rule.value is not None
    }
    for name, target in zip(names, targets, strict=True):
        if pairs:
            frame.value_labels[target] = dict(pairs)
            frame.label_books[target] = dict(pairs)
        if not in_place:
            own = frame.label_of(name)
            frame.labels[target] = f"RECODE of {name}" + (f" ({own})" if own else "")

    if in_place:
        write(work, frame, _select_sql(frame, ctx, replace=cases))
        done = ", ".join(
            f"{name} ({count:,} change(s))" for name, count in zip(names, changes, strict=True)
        )
        message = f"Recoded {done}"
    else:
        extra = [(target, cases[name]) for name, target in zip(names, targets, strict=True)]
        write(work, frame, _select_sql(frame, ctx, extra=extra))
        done = ", ".join(
            f"{target} from {name} ({count:,} value(s) differ)"
            for name, target, count in zip(names, targets, changes, strict=True)
        )
        message = f"Created {done}"
    return CommandResult(
        command="",
        message=message,
        variables_added=[] if in_place else targets,
        changed_rows=sum(changes),
        data_changed=True,
    )


def _recode_rules(text: str) -> list[str]:
    """The bracketed rules, each as the text inside its brackets."""
    rules: list[str] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        if text[index] != "(":
            raise CommandError(
                f"Expected a rule in brackets, like (1 2 = 0), at '{text[index:index + 20]}'"
            )
        quoted = False
        end = index + 1
        while end < len(text) and (quoted or text[end] != ")"):
            if text[end] == '"':
                quoted = not quoted
            end += 1
        if end >= len(text):
            raise CommandError("A recode rule is not closed with )")
        rules.append(text[index + 1 : end].strip())
        index = end + 1
    if not rules:
        raise CommandError("recode needs at least one rule, like (1 2 = 0)")
    return rules


def _recode_rule(text: str) -> _Rule:
    left, sign, right = text.partition("=")
    if not sign:
        raise CommandError(f"The rule ({text}) has no '='. Write it (old values = new value)")
    found = re.fullmatch(rf'({RULE_NUMBER}|\.)\s*(?:"([^"]*)")?', right.strip())
    if found is None:
        raise CommandError(
            f"The rule ({text}) has to end in one new value - a number, or . for "
            f"missing - with a label in quotes after it if you want one"
        )
    value = None if found.group(1) == "." else float(found.group(1))
    tests: list[tuple[str, ...]] = []
    for word in left.split():
        lowered = word.lower()
        if lowered in ("else", "*"):
            tests.append(("else",))
        elif lowered in ("missing", "miss", "mis") or word == ".":
            tests.append(("missing",))
        elif lowered in ("nonmissing", "nonmiss", "nonmis"):
            tests.append(("nonmissing",))
        elif re.fullmatch(r"\.[a-z]", lowered):
            raise CommandError(
                f"Tagged missing values like {word} are not told apart by recode here; "
                f"use . for every missing value"
            )
        elif "/" in word:
            low, _, high = lowered.partition("/")
            for end in (low, high):
                if end not in ("min", "max") and not re.fullmatch(RULE_NUMBER, end):
                    raise CommandError(f"'{word}' in ({text}) is not a range like 1/5 or min/0")
            if (
                re.fullmatch(RULE_NUMBER, low)
                and re.fullmatch(RULE_NUMBER, high)
                and float(low) > float(high)
            ):
                raise CommandError(
                    f"'{word}' in ({text}) runs backwards; write the lower end first"
                )
            tests.append(("range", low, high))
        elif lowered in ("min", "max") or re.fullmatch(RULE_NUMBER, word):
            tests.append(("equal", lowered))
        else:
            raise CommandError(
                f"'{word}' in ({text}) is not a value recode understands. It takes "
                f"numbers, ranges like 1/5, min, max, ., missing, nonmissing and else"
            )
    if not tests:
        raise CommandError(f"The rule ({text}) has nothing on the left of its '='")
    if ("else",) in tests and len(tests) > 1:
        raise CommandError(f"else stands on its own in its rule: (else = 0), not ({text})")
    return _Rule(tests=tests, value=value, label=found.group(2), written=text)


def _check_rule_order(rules: list[_Rule]) -> None:
    """else, missing and nonmissing mean "every other", so they come last."""
    catch_all = {("else",), ("missing",), ("nonmissing",)}
    seen_general = False
    for index, rule in enumerate(rules):
        general = any(test in catch_all for test in rule.tests) and all(
            test in catch_all for test in rule.tests
        )
        if seen_general and not general:
            raise CommandError(
                f"({rule.written}) comes after a rule for every other value, so nothing "
                f"is left for it. Put else, missing and nonmissing rules last"
            )
        if ("else",) in rule.tests and index != len(rules) - 1:
            raise CommandError("else catches every value left, so it has to be the last rule")
        seen_general = seen_general or general


def _recode_bounds(
    frame: Frame, names: list[str], rules: list[_Rule]
) -> dict[str, tuple[float | None, float | None]]:
    """Each variable's smallest and largest value, where a rule says min or max."""
    words = {word for rule in rules for test in rule.tests for word in test[1:]}
    if not words & {"min", "max"}:
        return {}
    columns = ", ".join(
        f"MIN({quote_ident(name)}), MAX({quote_ident(name)})" for name in names
    )
    _, rows = run_sql(f"SELECT {columns} FROM read_parquet({_quote_path(str(frame.path))})")
    found = list(rows[0]) if rows else [None] * (2 * len(names))
    return {
        name: (
            None if found[2 * k] is None else float(found[2 * k]),
            None if found[2 * k + 1] is None else float(found[2 * k + 1]),
        )
        for k, name in enumerate(names)
    }


def _recode_case(column: str, rules: list[_Rule], bounds: tuple[float | None, float | None]) -> str:
    low, high = bounds

    def resolved(word: str) -> float | None:
        return low if word == "min" else high if word == "max" else float(word)

    whens: list[str] = []
    fallback = column
    for rule in rules:
        value = "NULL" if rule.value is None else _number_sql(rule.value)
        if rule.tests == [("else",)]:
            fallback = value
            break
        tests: list[str] = []
        for test in rule.tests:
            if test[0] == "missing":
                tests.append(f"{column} IS NULL")
            elif test[0] == "nonmissing":
                tests.append(f"{column} IS NOT NULL")
            elif test[0] == "equal":
                number = resolved(test[1])
                if number is not None:
                    tests.append(f"{column} = {_number_sql(number)}")
            else:
                start, end = resolved(test[1]), resolved(test[2])
                if start is not None and end is not None:
                    tests.append(f"{column} BETWEEN {_number_sql(start)} AND {_number_sql(end)}")
        if tests:
            whens.append(f"WHEN {' OR '.join(tests)} THEN {value}")
    return f"CASE {' '.join(whens)} ELSE {fallback} END" if whens else fallback


def _number_sql(value: float) -> str:
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"CAST({value!r} AS DOUBLE)"


# --- text and codes ---------------------------------------------------------


def _tostring(run: Run, rest: str) -> CommandResult:
    """tostring <variables>, replace | generate(<names>) [force] - numbers as text.

    A whole number is written without a decimal point, so a code 3 becomes
    "3" and not "3.0". Missing stays missing rather than becoming ".", which
    would read as a category of its own on every chart.
    """
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["tostring"])
    generated = re.search(r"\b(?:generate|gen|g)\s*\(([^)]*)\)", options, re.IGNORECASE)
    replacing = "replace" in _option_words(options)
    if replacing == (generated is not None):
        raise CommandError(
            "tostring needs either replace or generate(), e.g. tostring hhid, replace"
        )
    ctx = frame.context
    names = _variable_list(ctx, body)
    if not names:
        raise CommandError("tostring needs the variables to write as text")
    new_names = _names_in(generated.group(1)) if generated else list(names)
    if len(new_names) != len(names):
        raise CommandError(
            f"generate() needs one new name for each variable: {len(names)} "
            f"variable(s), {len(new_names)} name(s)"
        )
    if generated:
        for new in new_names:
            _check_new_name(frame, new)

    kinds = _expression_kinds(frame)
    notes: list[str] = []
    converting: dict[str, str] = {}
    target = dict(zip(names, new_names, strict=True))
    for name in names:
        if kinds.get(name) == "text":
            notes.append(f"{name}: already text; left alone")
            continue
        number = f"TRY_CAST({quote_ident(name)} AS DOUBLE)"
        converting[name] = (
            f"CASE WHEN {number} IS NULL THEN NULL "
            f"WHEN {number} = TRUNC({number}) AND ABS({number}) < 1e15 "
            f"THEN CAST(CAST({number} AS BIGINT) AS VARCHAR) "
            f"ELSE CAST({number} AS VARCHAR) END"
        )
        labelled = " (it had value labels; decode writes those as text instead)" if (
            frame.value_labels.get(name)
        ) else ""
        notes.append(
            f"{name}: {'replaced' if replacing else f'generated {target[name]}'} as text{labelled}"
        )
    if not converting:
        return CommandResult(command="", message="; ".join(notes))
    if replacing:
        for name in converting:
            frame.value_labels.pop(name, None)
        write(work, frame, _select_sql(frame, ctx, replace=converting))
    else:
        for name in converting:
            if frame.label_of(name):
                frame.labels[target[name]] = frame.label_of(name)
        write(
            work, frame,
            _select_sql(frame, ctx, extra=[(target[n], sql) for n, sql in converting.items()]),
        )
    return CommandResult(
        command="",
        message="; ".join(notes),
        variables_added=[] if replacing else [target[name] for name in converting],
        changed_rows=frame.rows,
        data_changed=True,
    )


#: Most distinct values encode will number. More than this is not a category.
ENCODE_LIMIT = 1000


def _encode(run: Run, rest: str) -> CommandResult:
    """encode <variable>, generate(<name>) [label(<set>)] - text as numbered codes.

    Each distinct text gets a number, alphabetically from 1, and the number
    is labelled with the text, so the variable charts and tabulates by its
    words and sums and compares as a code. With label() naming a set that
    exists, its codes are used and new texts are numbered after them.
    """
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["encode"])
    names = _variable_list(frame.context, body)
    if len(names) != 1:
        raise CommandError("encode takes one variable: encode province, generate(province_code)")
    name = names[0]
    generated = re.search(r"\b(?:generate|gen|g)\s*\(([^)]*)\)", options, re.IGNORECASE)
    if generated is None or not generated.group(1).strip():
        raise CommandError(
            f"encode needs a name for the codes: encode {name}, generate({name}_code)"
        )
    new = generated.group(1).strip()
    _check_new_name(frame, new)
    if _expression_kinds(frame).get(name) != "text":
        raise CommandError(f"encode numbers text, and {name} already holds numbers")
    named_set = re.search(r"\blabel\s*\(([^)]*)\)", options, re.IGNORECASE)
    book = named_set.group(1).strip() if named_set else new
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", book):
        raise CommandError(f"'{book}' is not a usable name for a label set")

    column = quote_ident(name)
    _, rows = run_sql(
        f"SELECT DISTINCT {column} FROM read_parquet({_quote_path(str(frame.path))}) "
        f"WHERE {column} IS NOT NULL AND {column} <> '' ORDER BY 1 LIMIT {ENCODE_LIMIT + 1}"
    )
    values = [str(row[0]) for row in rows]
    if len(values) > ENCODE_LIMIT:
        raise CommandError(
            f"{name} has more than {ENCODE_LIMIT:,} different values, which is not a set "
            f"of categories to number"
        )
    pairs = dict(frame.label_books.get(book) or {}) if named_set else {}
    by_text = {text: code for code, text in pairs.items()}
    used: list[float] = []
    for code in pairs:
        try:
            used.append(float(code))
        except ValueError:
            raise CommandError(
                f"The label set '{book}' has a code that is not a number: {code}"
            ) from None
    following = int(max(used, default=0)) + 1
    mapping: dict[str, str] = {}
    added = 0
    for value in values:
        if value in by_text:
            mapping[value] = by_text[value]
            continue
        mapping[value] = str(following)
        pairs[str(following)] = value
        following += 1
        added += 1
    whens = " ".join(
        f"WHEN {column} = {_text_sql(value)} THEN {_number_sql(float(code))}"
        for value, code in mapping.items()
    )
    case = f"CASE {whens} END" if whens else "CAST(NULL AS INTEGER)"
    frame.value_labels[new] = dict(pairs)
    frame.label_books[book] = dict(pairs)
    if frame.label_of(name):
        frame.labels[new] = frame.label_of(name)
    write(work, frame, _select_sql(frame, frame.context, extra=[(new, case)]))
    reused = len(mapping) - added
    return CommandResult(
        command="",
        message=(
            f"Created {new}: {len(mapping):,} value(s) of {name} as codes, labelled with "
            f"the text (label set '{book}'"
            + (f"; {reused:,} code(s) already in it" if reused else "")
            + ")"
        ),
        variables_added=[new],
        changed_rows=frame.rows,
        data_changed=True,
    )


def _decode(run: Run, rest: str) -> CommandResult:
    """decode <variable>, generate(<name>) - a labelled code as its label's text."""
    frame, work = run.data, run.work
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["decode"])
    names = _variable_list(frame.context, body)
    if len(names) != 1:
        raise CommandError("decode takes one variable: decode province, generate(province_name)")
    name = names[0]
    generated = re.search(r"\b(?:generate|gen|g)\s*\(([^)]*)\)", options, re.IGNORECASE)
    if generated is None or not generated.group(1).strip():
        raise CommandError(
            f"decode needs a name for the text: decode {name}, generate({name}_text)"
        )
    new = generated.group(1).strip()
    _check_new_name(frame, new)
    pairs = frame.value_labels.get(name) or {}
    if not pairs:
        raise CommandError(
            f"{name} has no value labels to decode. Give it some first: "
            f"label values {name} <set>"
        )
    column = quote_ident(name)
    numeric = _expression_kinds(frame).get(name) == "number"
    tests: list[tuple[str, str]] = []
    for code, text in pairs.items():
        if numeric:
            try:
                tests.append((f"TRY_CAST({column} AS DOUBLE) = {_number_sql(float(code))}", text))
            except ValueError:
                continue
        else:
            tests.append((f"CAST({column} AS VARCHAR) = {_text_sql(code)}", text))
    whens = " ".join(f"WHEN {test} THEN {_text_sql(text)}" for test, text in tests)
    case = f"CASE {whens} END" if whens else "CAST(NULL AS VARCHAR)"
    unlabelled = _count_matching(
        frame, f"{column} IS NOT NULL AND ({case}) IS NULL"
    )
    if frame.label_of(name):
        frame.labels[new] = frame.label_of(name)
    write(work, frame, _select_sql(frame, frame.context, extra=[(new, case)]))
    note = (
        f"; {unlabelled:,} row(s) have a value with no label, and are missing in {new}"
        if unlabelled
        else ""
    )
    return CommandResult(
        command="",
        message=f"Created {new}: {name} as its labels' text{note}",
        variables_added=[new],
        changed_rows=frame.rows,
        data_changed=True,
    )


def _text_sql(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


# --- reshape ----------------------------------------------------------------

#: Most columns a reshape wide makes from one stub.
RESHAPE_LIMIT = 200


def _reshape(run: Run, rest: str) -> CommandResult:
    """reshape long|wide <stubs>, i(<ids>) j(<name>) [string].

    Long turns inc2019 inc2020 inc2021 into one inc column and a year column,
    a row for each household and year; wide turns them back. Like collapse,
    the result is no longer the dataset it was loaded from, so it is saved
    under a name of its own.
    """
    frame = run.data
    body, options = _split_options(rest)
    _reject_unknown_options(options, OPTIONS["reshape"])
    direction, _, stubs_text = body.partition(" ")
    direction = direction.lower()
    if direction not in ("long", "wide"):
        raise CommandError(
            "reshape goes long or wide: reshape long inc, i(hhid) j(year)"
        )
    stubs = _names_in(stubs_text)
    if not stubs:
        raise CommandError(
            f"reshape {direction} needs the stubs: reshape {direction} inc, i(hhid) j(year)"
        )
    ids_given = re.search(r"(?<![A-Za-z0-9_])i\s*\(([^)]*)\)", options, re.IGNORECASE)
    j_given = re.search(r"(?<![A-Za-z0-9_])j\s*\(([^)]*)\)", options, re.IGNORECASE)
    if ids_given is None or j_given is None:
        raise CommandError(
            f"reshape needs i() for what identifies a row and j() for the suffix: "
            f"reshape {direction} {stubs_text.strip()}, i(hhid) j(year)"
        )
    ids = _variable_list(frame.context, ids_given.group(1))
    j_names = _names_in(j_given.group(1))
    if not ids or len(j_names) != 1:
        raise CommandError("i() names the identifying variables and j() one variable")
    textual = "string" in _option_words(options)
    if direction == "long":
        return _reshape_long(run, stubs, ids, j_names[0], textual)
    return _reshape_wide(run, stubs, ids, j_names[0])


def _unique_by(frame: Frame, keys: list[str], what: str) -> None:
    grouped = ", ".join(quote_ident(name) for name in keys)
    _, rows = run_sql(
        f"SELECT COUNT(*) FROM (SELECT 1 FROM read_parquet({_quote_path(str(frame.path))}) "
        f"GROUP BY {grouped} HAVING COUNT(*) > 1)"
    )
    repeated = int(rows[0][0]) if rows else 0
    if repeated:
        raise CommandError(
            f"{', '.join(keys)} does not identify the rows: {repeated:,} value(s) appear "
            f"more than once, so {what}"
        )


def _reshape_long(
    run: Run, stubs: list[str], ids: list[str], j: str, textual: bool
) -> CommandResult:
    frame, work = run.data, run.work
    ctx = frame.context
    if frame.has(j):
        raise CommandError(
            f"'{j}' is already a variable; j() names the new one that holds the suffixes"
        )
    _check_new_name(frame, j)
    stored = column_types(str(frame.path))
    path = _quote_path(str(frame.path))
    suffix_pattern = r".+" if textual else r"\d+"
    sources: dict[str, dict[str, str]] = {}
    for stub in stubs:
        if frame.has(stub):
            raise CommandError(
                f"'{stub}' is already a variable, and reshape long makes it from "
                f"{stub}1, {stub}2 and the like"
            )
        found = {
            name[len(stub):]: name
            for name in ctx.variables
            if name.startswith(stub)
            and name not in ids
            and not name.endswith(MISSING_TAG_SUFFIX)
            and re.fullmatch(suffix_pattern, name[len(stub):])
        }
        if not found:
            ending = "anything" if textual else "a number"
            raise CommandError(f"No variable starts with {stub} and ends in {ending}")
        kinds = {kind_of(stored[name]) for name in found.values() if name in stored}
        if "text" in kinds and len(kinds) > 1:
            raise CommandError(
                f"Some of the {stub} variables are text and some are numbers, so they "
                f"cannot share one column. Make them the same type first"
            )
        sources[stub] = found
    suffixes = sorted(
        {suffix for found in sources.values() for suffix in found},
        key=(lambda one: one) if textual else (lambda one: (int(one), one)),
    )
    _unique_by(frame, ids, "there is no telling whose values are whose")

    spread = {name for found in sources.values() for name in found.values()}
    dropped = spread | {name + MISSING_TAG_SUFFIX for name in spread}
    carried = [name for name in ctx.variables if name not in ids and name not in dropped]
    parts = []
    for suffix in suffixes:
        selected = [quote_ident(name) for name in ids]
        selected.append(
            f"{_text_sql(suffix) if textual else int(suffix)} AS {quote_ident(j)}"
        )
        for stub in stubs:
            source = sources[stub].get(suffix)
            selected.append(
                f"{quote_ident(source)} AS {quote_ident(stub)}"
                if source
                else f"NULL AS {quote_ident(stub)}"
            )
        selected += [quote_ident(name) for name in carried]
        parts.append(f"SELECT {', '.join(selected)} FROM read_parquet({path})")
    ordering = ", ".join([*_order_terms(frame, [(name, False) for name in ids]), quote_ident(j)])
    sql = f"SELECT * FROM ({' UNION ALL BY NAME '.join(parts)}) ORDER BY {ordering}"

    for stub in stubs:
        first = sources[stub][min(sources[stub], key=lambda one: suffixes.index(one))]
        if frame.value_labels.get(first):
            frame.value_labels[stub] = dict(frame.value_labels[first])
    before = frame.rows
    write(work, frame, sql)
    frame.origin = None
    frame.name = f"{frame.name} long"
    return CommandResult(
        command="",
        message=(
            f"Reshaped {before:,} row(s) to {frame.rows:,}, one for each "
            f"{', '.join(ids)} and {j}: {', '.join(stubs)} from {len(suffixes):,} "
            f"value(s) of {j}"
        ),
        variables_added=[j, *stubs],
        variables_removed=sorted(spread),
        changed_rows=frame.rows,
        data_changed=True,
    )


def _reshape_wide(run: Run, stubs: list[str], ids: list[str], j: str) -> CommandResult:
    frame, work = run.data, run.work
    ctx = frame.context
    _variable_list(ctx, " ".join([j, *stubs]))
    if j in ids or j in stubs or set(ids) & set(stubs):
        raise CommandError("i(), j() and the stubs have to be different variables")
    column = quote_ident(j)
    textual = _expression_kinds(frame).get(j) == "text"
    path = _quote_path(str(frame.path))
    blank = f"{column} IS NULL" + (f" OR {column} = ''" if textual else "")
    unplaced = _count_matching(frame, blank)
    if unplaced:
        raise CommandError(
            f"{j} is missing on {unplaced:,} row(s), and a row with no {j} has no "
            f"column to go to. Drop them first: drop if missing({j})"
        )
    _, rows = run_sql(
        f"SELECT DISTINCT {column} FROM read_parquet({path}) ORDER BY 1 LIMIT {RESHAPE_LIMIT + 1}"
    )
    values = [row[0] for row in rows]
    if len(values) > RESHAPE_LIMIT:
        raise CommandError(
            f"{j} has more than {RESHAPE_LIMIT} values, which would make more than "
            f"{RESHAPE_LIMIT} columns from each stub"
        )
    suffixes: list[str] = []
    for value in values:
        if textual:
            suffixes.append(str(value))
            continue
        number = float(value)
        if not number.is_integer():
            raise CommandError(
                f"{j} has a value that is not a whole number ({value}), which cannot end a name"
            )
        suffixes.append(str(int(number)))
    _unique_by(frame, [*ids, j], f"some {', '.join(ids)} have two rows for one {j}")

    spread = set(stubs) | {j}
    dropped = spread | {name + MISSING_TAG_SUFFIX for name in spread}
    carried = [name for name in ctx.variables if name not in ids and name not in dropped]
    made = [f"{stub}{suffix}" for stub in stubs for suffix in suffixes]
    for name in made:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise CommandError(
                f"'{name}' would not be a usable variable name; change the values of {j} first"
            )
        if name in carried or name in ids:
            raise CommandError(f"'{name}' is already a variable, so reshape wide cannot make it")
    _constant_within(frame, carried, ids)

    selected = [quote_ident(name) for name in ids]
    selected += [f"ANY_VALUE({quote_ident(name)}) AS {quote_ident(name)}" for name in carried]
    for stub in stubs:
        for value, suffix in zip(values, suffixes, strict=True):
            test = f"{column} = {_text_sql(str(value)) if textual else _number_sql(float(value))}"
            selected.append(
                f"MAX({quote_ident(stub)}) FILTER (WHERE {test}) AS {quote_ident(stub + suffix)}"
            )
    grouped = ", ".join(quote_ident(name) for name in ids)
    ordering = ", ".join(_order_terms(frame, [(name, False) for name in ids]))
    sql = (
        f"SELECT {', '.join(selected)} FROM read_parquet({path}) "
        f"GROUP BY {grouped} ORDER BY {ordering}"
    )

    for stub in stubs:
        own = frame.label_of(stub) or stub
        for suffix in suffixes:
            frame.labels[stub + suffix] = f"{own}, {j} {suffix}"
            if frame.value_labels.get(stub):
                frame.value_labels[stub + suffix] = dict(frame.value_labels[stub])
    before = frame.rows
    write(work, frame, sql)
    frame.origin = None
    frame.name = f"{frame.name} wide"
    return CommandResult(
        command="",
        message=(
            f"Reshaped {before:,} row(s) to {frame.rows:,}, one for each {', '.join(ids)}: "
            f"{len(made):,} variable(s) from {', '.join(stubs)}, one per {j}"
        ),
        variables_added=made,
        variables_removed=sorted(spread),
        changed_rows=frame.rows,
        data_changed=True,
    )


def _constant_within(frame: Frame, names: list[str], ids: list[str]) -> None:
    """A variable reshape wide carries along has one value for each id.

    Otherwise only one of its values survives and the rest go without a
    word, which is the kind of loss nobody notices until a total is wrong.
    """
    if not names:
        return
    grouped = ", ".join(quote_ident(name) for name in ids)
    varies = ", ".join(
        f"(COUNT(DISTINCT {quote_ident(name)}) > 1 OR (COUNT({quote_ident(name)}) > 0 "
        f"AND COUNT({quote_ident(name)}) < COUNT(*))) AS {quote_ident(f'__varies{k}')}"
        for k, name in enumerate(names)
    )
    counted = ", ".join(
        f"COUNT(*) FILTER (WHERE {quote_ident(f'__varies{k}')})" for k in range(len(names))
    )
    _, rows = run_sql(
        f"SELECT {counted} FROM (SELECT {varies} FROM read_parquet("
        f"{_quote_path(str(frame.path))}) GROUP BY {grouped})"
    )
    for name, groups in zip(names, rows[0] if rows else [], strict=False):
        if groups:
            raise CommandError(
                f"{name} is not constant within {', '.join(ids)}: it differs inside "
                f"{int(groups):,} of them. Add it to the stubs to spread it out too, or "
                f"drop it first"
            )


# --- prefixes and blocks, written on their own ------------------------------


def _by_alone(run: Run, rest: str) -> CommandResult:
    raise CommandError(
        "by goes in front of a command, with a colon: by hhid: gen members = _N"
    )


def _bysort_alone(run: Run, rest: str) -> CommandResult:
    raise CommandError(
        "bysort goes in front of a command, with a colon: bysort hhid (age): gen eldest = _n == _N"
    )


def _foreach_alone(run: Run, rest: str) -> CommandResult:
    raise CommandError(
        "foreach runs the lines below it, up to a } on a line of its own. End its "
        "line with {: foreach v of varlist q1 q2 q3 {"
    )


def _forvalues_alone(run: Run, rest: str) -> CommandResult:
    raise CommandError(
        "forvalues runs the lines below it, up to a } on a line of its own. End its "
        "line with {: forvalues i = 1/5 {"
    )


def _option_words(options: str) -> set[str]:
    """The options given, by name and lower-cased, without their arguments."""
    return {word.lower() for word in re.findall(r"[A-Za-z]+", re.sub(r"\([^)]*\)", " ", options))}


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
        "destring": _destring,
        "recode": _recode,
        "duplicates": _duplicates,
        "reshape": _reshape,
        "tostring": _tostring,
        "encode": _encode,
        "decode": _decode,
        "sort": _sort,
        "gsort": _gsort,
        "order": _order,
        "assert": _assert,
        "count": _count,
        "summarize": _summarize, "sum": _summarize, "su": _summarize,
        "tabulate": _tabulate, "tab": _tabulate, "ta": _tabulate,
        "by": _by_alone,
        "bysort": _bysort_alone, "bys": _bysort_alone,
        "foreach": _foreach_alone,
        "forvalues": _forvalues_alone, "forval": _forvalues_alone, "forv": _forvalues_alone,
        "local": _local,
        "global": _global,
    }


def verb_names() -> list[str]:
    """One name per command, for saying what is available.

    Read off the table rather than written out next to it, because the two
    drifted: the list this used to carry named nine commands and left out
    `collapse`, `contract`, `merge` and `append`, all of which have worked for
    as long as they have been in the table. Somebody who mistyped a collapse
    was told, in so many words, that collapse was not a command here.

    Aliases are folded away by handler, so `gen` is offered once rather than
    as four spellings of itself.
    """
    first: dict[Any, str] = {}
    for name, handler in verbs().items():
        first.setdefault(handler, name)
    return list(first.values())


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
    """Split `body , options` on the comma Stata uses for options.

    The first comma outside brackets and quotes: `egen t = rowtotal(a, b)`
    has its options after the bracket, and a recode label "Yes, always" has
    none inside its quotes.
    """
    depth = 0
    quoted = False
    for index, character in enumerate(rest):
        if character == '"':
            quoted = not quoted
        elif quoted:
            continue
        elif character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "," and depth <= 0:
            return rest[:index].strip(), rest[index + 1 :].strip()
    return rest.strip(), ""


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


def _condition_sql(frame: Frame, condition: str, window: Window | None = None) -> str:
    if not condition:
        return ""
    return translate(condition, _expression_kinds(frame), quote_ident, window)


def _filtering(where: str) -> str:
    """WHERE, or QUALIFY where the condition counts rows.

    `keep if _n == 1` is a window function, which SQL evaluates after WHERE
    and so cannot filter by there. QUALIFY is the clause that runs after the
    windows - and refuses a condition with none in it, so it is used only
    where one is.
    """
    return "QUALIFY" if " OVER (" in where else "WHERE"


def _numbered(frame: Frame) -> str:
    """The working file with its row order, which every window counts in."""
    return (
        f"(SELECT *, ROW_NUMBER() OVER () AS {quote_ident(ROW_ORDER)} "
        f"FROM read_parquet({_quote_path(str(frame.path))}))"
    )


def _rows_where(frame: Frame, where: str) -> str:
    """The working file's rows that meet a condition, or all of them."""
    if not where:
        return _numbered(frame)
    return f"(SELECT * FROM {_numbered(frame)} {_filtering(where)} {where})"


def _count_matching(frame: Frame, where: str) -> int:
    _, rows = run_sql(f"SELECT COUNT(*) FROM {_rows_where(frame, where)}")
    return int(rows[0][0]) if rows else 0


def _select_sql(
    frame: Frame,
    ctx: DatasetContext,
    extra: list[tuple[str, str]] | None = None,
    replace: dict[str, str] | None = None,
    rename: dict[str, str] | None = None,
    only: list[str] | None = None,
    where: str = "",
) -> str:
    """The query describing the data as the command leaves it.

    Returned rather than run: the result's only destination is the working
    Parquet file, so it goes there directly instead of being read into Python
    and written back out again.
    """
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
        sql += f" {_filtering(where)} {where}"
    sql += f" ORDER BY {ordinal}"
    return sql


def _as_number(frame: Frame, expression: str) -> str:
    """Turn a true/false expression into 1/0, because Stata has no true or false.

    `gen adult = age >= 18` is a number in Stata, and everything downstream
    assumes that: `egen total = sum(adult)` and `collapse (sum) adult` are
    arithmetic, and a chart of it is a chart of a count. DuckDB answers a
    comparison with a BOOLEAN, which cannot be summed at all - the binder
    refuses `sum(BOOLEAN)` outright - so the column has to become what Stata
    would have made it before it is written.

    The type is asked of DuckDB rather than guessed, because an expression can
    reach a boolean in more ways than a comparison: `inlist(...)`, a function,
    a nested case. DESCRIBE binds the query without running it, so this costs a
    parse and no scan.

    Missing stays missing: a cast of NULL is NULL, not a zero.
    """
    return f"CAST({expression} AS INTEGER)" if _is_boolean(frame, expression) else expression


def _is_boolean(frame: Frame, expression: str) -> bool:
    """Whether DuckDB answers this expression with a true or false.

    Asked over the numbered rows, since an expression counting rows - `_n`,
    `x[_n-1]` - is written in terms of their order.
    """
    _, rows = run_sql(f"DESCRIBE SELECT {expression} AS __value FROM {_numbered(frame)}")
    return bool(rows) and str(rows[0][1]).strip().upper() == "BOOLEAN"


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
    # Codes written as the data is read: `label define yn 1.0 "Yes"` is a
    # label for the value 1, and keyed "1.0" it would never be found.
    pairs = {numeric_code_text(rest[i]): rest[i + 1] for i in range(0, len(rest), 2)}
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
    # One set of macros for the whole replay, as a script has. The recorded
    # commands are the expanded ones, so most of them need no macro at all -
    # but a definition written in terms of another was recorded as typed, and
    # replaying it without what came before fails on a name it cannot find.
    named: dict[str, str] = {}
    wider: dict[str, str] = {}
    for text in entries(dataset):
        try:
            run(db, dataset, text, record_it=False, locals_=named, globals_=wider)
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

