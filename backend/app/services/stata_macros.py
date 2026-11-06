"""Named pieces of script text, written once and referred to by name.

A long recode cascade says the same condition over and over. The ILO
employment definition is eight lines of `age >= 15 & worked_hours > 0 &
!missing(status)`, and it appears in the generate, in the egen, and in three
of the replaces that follow. Changing who counts as employed means finding
every copy, which is how a cascade ends up disagreeing with itself.

So a condition can be named:

    local employed  age >= 15 & worked_hours > 0
    gen working = 1 if `employed'
    replace working = 0 if !(`employed')

The name is replaced by its text before the command is parsed, which is all a
macro is. Nothing is evaluated, nothing is stored on a dataset, and the
definition lives as long as the run that made it.

Two namespaces, as in Stata: a local is written `name' and a global $name.
They are separate - a local and a global of one name are two macros - and here
both last for the run, since a run is the whole session.

One deliberate difference. Stata expands an undefined macro to nothing and
carries on, which is the single most reliable way to get a wrong answer out of
a do-file: `keep if `poorr'` quietly becomes `keep if` and the next thing that
fails is somewhere else entirely. There is no interactive session here to type
`macro list` into, so an undefined name is refused by name instead, with the
defined ones listed.
"""

from __future__ import annotations

import re

# `name' for a local, $name or ${name} for a global. The closing mark on a
# local is an apostrophe, not a backtick, which is Stata's and is why a macro
# reference cannot be written with matching quotes.
LOCAL = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)'")
GLOBAL = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")

# A macro whose text names another is expanded again. The cap is for a macro
# that names itself, directly or through a ring of others, which would
# otherwise expand until the process ran out of memory.
ROUNDS = 16

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class MacroError(ValueError):
    """A macro could not be defined or could not be expanded."""


def define(text: str) -> tuple[str, str, bool]:
    """Read `name rest` into the name, the text it stands for, and whether an
    equals sign was written.

    The quotes around a definition are Stata's way of keeping leading and
    trailing spaces, so they come off: `local a "x"` defines x, not "x". A
    definition with no text at all is a macro that stands for nothing, which
    is a legitimate thing to write and how a condition gets switched off
    without deleting the lines that use it.
    """
    stripped = text.strip()
    if not stripped:
        raise MacroError(
            "Give the macro a name and what it stands for, "
            "for example: local employed age >= 15 & worked_hours > 0"
        )
    name, _, rest = stripped.partition(" ")
    name = name.strip()
    if not NAME.match(name):
        raise MacroError(
            f"'{name}' is not a name a macro can have. Start with a letter or "
            "an underscore and use letters, numbers and underscores."
        )

    body = rest.strip()
    # `local x = age > 15` is Stata's evaluated form, and in Stata it reads
    # observation 1 and stores a 0 or a 1 - the classic way to get a constant
    # where a condition was meant. The equals sign is taken off and the
    # expression named instead, which is what anybody writing it here wants,
    # and the run log says so rather than leaving it to be discovered.
    evaluated = body.startswith("=")
    if evaluated:
        body = body[1:].strip()
    if len(body) >= 2 and body[0] == '"' and body[-1] == '"':
        body = body[1:-1]
    return name, body, evaluated


def expand(text: str, locals_: dict[str, str], globals_: dict[str, str]) -> str:
    """Replace every macro reference in one command with what it stands for.

    Repeated rather than single-pass, so a macro may be written in terms of
    another - which is the whole point of naming the parts of a long
    condition separately.
    """
    seen = text
    for _ in range(ROUNDS):
        grown = _once(seen, locals_, globals_)
        if grown == seen:
            # Settled. A reference still standing means a macro put its own
            # name back, which reads as settled and is not: `local a `a''
            # expands to itself in one step and would be handed on with a
            # backtick in it, to fail somewhere with no mention of macros.
            if referenced(grown):
                break
            return grown
        seen = grown
    raise MacroError(
        "A macro refers to itself, directly or through another, so expanding "
        f"it never finishes: {text.strip()[:80]}"
    )


def _once(text: str, locals_: dict[str, str], globals_: dict[str, str]) -> str:
    def local(match: re.Match[str]) -> str:
        return _lookup(match.group(1), locals_, "local", "`", "'")

    def wider(match: re.Match[str]) -> str:
        return _lookup(match.group(1) or match.group(2), globals_, "global", "$", "")

    return GLOBAL.sub(wider, LOCAL.sub(local, text))


def _lookup(name: str, among: dict[str, str], kind: str, open_: str, close: str) -> str:
    if name in among:
        return among[name]
    known = ", ".join(sorted(among)) if among else "none"
    raise MacroError(
        f"{open_}{name}{close} is not a {kind} macro this run has defined. "
        f"Defined: {known}. Stata would quietly put nothing here; this says so "
        "instead, because a condition that silently empties is how a do-file "
        "comes back with the wrong answer and no error."
    )


def referenced(text: str) -> bool:
    """Whether a command mentions a macro at all, without expanding one."""
    return bool(LOCAL.search(text) or GLOBAL.search(text))
