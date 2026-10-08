"""The help pane's examples, checked against the engine that has to run them.

A pane of examples that do not work is worse than no pane: somebody clicks one,
it fails, and now they distrust the whole box. The pane is written by hand -
generating it would list verbs and say nothing about when to reach for them -
so this is what stops the two drifting apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.stata import (
    COLLAPSE_STATS,
    EGEN_AGGREGATES,
    EGEN_ROWWISE,
    verbs,
)
from app.services.stata_expr import FUNCTIONS, SPECIAL

PANE = Path(__file__).resolve().parents[2] / "frontend/src/components/ProjectScriptHelp.tsx"


def pane_text() -> str:
    assert PANE.is_file(), f"the help pane moved: {PANE}"
    return PANE.read_text()


def example_lines() -> list[str]:
    """Every `line: '...'` in the pane, which is what a click inserts."""
    found = re.findall(r"\{ line: '((?:[^'\\]|\\.)*)'", pane_text())
    assert found, "no examples found in the pane"
    return [line.replace("\\'", "'").replace('\\"', '"') for line in found]


def test_every_example_starts_with_a_command_the_engine_has():
    """Catches a typo, and a verb removed from the engine but not the pane."""
    known = set(verbs())
    for line in example_lines():
        # `save, replace` carries its options on the verb itself.
        verb = line.split()[0].rstrip(",")
        assert verb in known, f"'{verb}' is not a command: {line!r}"


def test_the_pane_offers_an_example_of_every_command_the_engine_has():
    """The ask was examples of everything possible, so missing one is a bug.

    Abbreviations are the same command under another spelling, so one example
    of each distinct command is enough.
    """
    offered = {line.split()[0].rstrip(",") for line in example_lines()}
    commands = verbs()
    missing = {
        name
        for name, handler in commands.items()
        if not any(commands.get(shown) is handler for shown in offered)
    }
    assert not missing, f"no example uses: {sorted(missing)}"


@pytest.mark.parametrize(
    "named,source",
    [
        ("collapse statistics", set(COLLAPSE_STATS)),
        ("egen, down a column", set(EGEN_AGGREGATES)),
        ("egen, across a row", set(EGEN_ROWWISE)),
        ("in expressions", set(FUNCTIONS) - {"strlen", "strlower", "strupper", "strtrim"}),
        ("same thing, Stata spelling", {"strlen", "strlower", "strupper", "strtrim"}),
        ("and these", SPECIAL),
    ],
)
def test_the_vocabulary_lists_what_the_engine_actually_knows(named: str, source: set[str]):
    """A list that drifts is worse than no list: it sends people to a function
    that was renamed, and hides one that was added."""
    text = pane_text()
    start = text.index(f"'{named}'")
    listed = text[start : start + 600]
    for word in sorted(source):
        assert re.search(rf"\b{re.escape(word)}\b", listed), (
            f"'{word}' is in the engine but not under '{named}' in the pane"
        )
