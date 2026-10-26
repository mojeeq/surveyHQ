"""What the command box says it accepts has to be what it accepts.

These drifted. The message for an unknown command carried a list written out
beside it, and that list named nine commands while the table held thirteen:
`collapse`, `contract`, `merge` and `append` were missing from it, and had been
working the whole time. Somebody who mistyped a collapse was told that collapse
was not a command this understands, which is the sort of wrong answer that
sends people to look for another tool.

So the message is built from the table now, and this holds the two together.
"""

from __future__ import annotations

import pytest

from app.services import stata
from app.services.stata import CommandError, verb_names


def test_every_command_in_the_table_is_offered():
    offered = set(verb_names())
    for name, handler in stata.verbs().items():
        assert any(
            stata.verbs()[one] is handler for one in offered
        ), f"'{name}' is a command but nothing in the offered list reaches it"


def test_the_commands_people_lose_are_named():
    """The four that were missing, pinned by name rather than by count.

    A count would pass again the moment somebody adds a verb and forgets the
    list, which is the failure this is here to stop.
    """
    offered = verb_names()
    for name in ("collapse", "contract", "merge", "append"):
        assert name in offered, f"'{name}' works but is not offered"


def test_an_alias_is_not_offered_twice():
    """`gen`, `gene`, `generate` and `g` are one command, not four."""
    offered = verb_names()
    assert len(offered) == len(set(offered))
    handlers = [stata.verbs()[name] for name in offered]
    assert len(handlers) == len({id(h) for h in handlers})


def test_the_refusal_names_the_commands(db_session):
    """The message somebody actually reads, not just the helper behind it.

    A real Run rather than None: macro references are expanded before the
    verb is looked up, because a macro may hold the verb itself, and the
    expander reads the run's two dictionaries to do it.
    """
    with pytest.raises(CommandError) as raised:
        stata.apply(stata.Run(db=db_session), "xtile band = age, nq(5)")

    said = str(raised.value)
    assert "'xtile' is not a command" in said
    for name in ("collapse", "contract", "merge", "append", "gen", "egen", "local"):
        assert name in said, f"the refusal does not mention '{name}': {said}"


def test_a_macro_can_hold_the_command_itself(db_session):
    """Which is why expansion comes before the verb is looked up."""
    run = stata.Run(db=db_session)
    stata.apply(run, "local verb xtile")
    with pytest.raises(CommandError) as raised:
        stata.apply(run, "`verb' band = age, nq(5)")
    assert "'xtile' is not a command" in str(raised.value)
