"""The little arithmetic an indicator can be defined by.

An indicator used to be one aggregate and an optional "as a share of every
row". A completion rate is that; a refusal per interview, a gap between
visits and interviews, or a rate among those who answered one particular
question, is not. So an indicator can be named parts combined by a sum.

The parts of that worth pinning are the ones that bite in a survey office:
an expression typed by somebody who is not a programmer must fail with a
sentence rather than a traceback, a province where nothing was issued must
report nothing rather than divide by zero, and the whole thing must never
become a way to run code on the server.
"""

from __future__ import annotations

import pytest

from app.services.formula import FormulaError, compute, names_in, parse


def test_a_rate_is_a_division_and_a_hundred():
    assert compute("done / issued * 100", {"done": 30, "issued": 40}) == 75.0


def test_the_usual_four_operators_read_as_arithmetic_does():
    assert compute("a + b * c", {"a": 1, "b": 2, "c": 3}) == 7.0
    assert compute("(a + b) * c", {"a": 1, "b": 2, "c": 3}) == 9.0
    assert compute("a - b - c", {"a": 10, "b": 3, "c": 2}) == 5.0
    assert compute("a / b / c", {"a": 100, "b": 5, "c": 2}) == 10.0


def test_a_leading_minus_is_a_sign_rather_than_a_syntax_error():
    assert compute("-a + 10", {"a": 4}) == 6.0
    assert compute("-(a - b)", {"a": 1, "b": 4}) == 3.0


def test_nothing_issued_is_no_rate_rather_than_a_crash():
    """A province that has not started has no completion rate. The tile says
    so by being blank; an infinity would draw as a bar."""
    assert compute("done / issued * 100", {"done": 0, "issued": 0}) is None


def test_a_part_with_no_value_leaves_the_whole_sum_with_none():
    assert compute("a + b", {"a": 1, "b": None}) is None


def test_the_names_are_read_out_so_a_missing_part_is_caught_on_save():
    assert names_in("done / issued * 100") == {"done", "issued"}
    assert names_in("1 + 2") == set()


@pytest.mark.parametrize(
    ("bad", "says"),
    [
        ("", "empty"),
        ("a +", "stops in the middle"),
        ("a + (b", "never closed"),
        ("a b", "left over"),
        ("a @ b", "does not mean anything"),
        (")", "cannot start"),
        ("*", "cannot start"),
    ],
)
def test_a_formula_that_cannot_be_read_says_so_in_a_sentence(bad: str, says: str):
    with pytest.raises(FormulaError) as raised:
        parse(bad)

    assert says in str(raised.value)


@pytest.mark.parametrize(
    "attempt",
    [
        "__import__('os').system('ls')",
        "open('/etc/passwd').read()",
        "a.__class__",
        "[x for x in range(3)]",
        "1 if a else 2",
        "a ** 99999999",
    ],
)
def test_nothing_but_arithmetic_gets_through(attempt: str):
    """The expression is typed by a user and stored. It is parsed into a tree
    of tuples and walked, never evaluated, so none of this is even a formula."""
    with pytest.raises(FormulaError):
        parse(attempt)


def test_a_formula_long_enough_to_be_an_attack_is_refused():
    with pytest.raises(FormulaError) as raised:
        parse("1+" * 400 + "1")

    assert "longer than" in str(raised.value)


def test_brackets_cannot_be_nested_until_the_stack_gives_out():
    with pytest.raises(FormulaError) as raised:
        parse("(" * 100 + "1" + ")" * 100)

    assert "deeply" in str(raised.value)


def test_a_part_name_may_be_written_the_way_anybody_writes_one():
    assert compute("interviews_done / _total", {"interviews_done": 5, "_total": 10}) == 0.5
    assert compute("a1 + b2", {"a1": 1, "b2": 2}) == 3.0


def test_a_number_may_be_written_as_a_decimal():
    assert compute("a * 0.5 + .5", {"a": 3}) == 2.0
