"""What a condition means when the value is missing, checked against Stata.

Stata treats numeric missing as larger than any number. SQL treats NULL as
unknown and a WHERE clause reads unknown as no. The two disagree on almost
every comparison, and they disagree silently, which is how

    replace ilo_lfs_emp = 3 if !inlist(ilo_lfs_emp, 1, 2)

- the line that ends every recode cascade - came to match no rows at all and
report success while doing it.

So these are not tests of the SQL text. Each one builds the SQL, runs it on
DuckDB against a row whose value really is missing, and asserts the answer
Stata gives. The expected column is Stata's, taken from its rule rather than
from this implementation: if the two ever part company again, this is where it
shows.

Being faithful means inheriting the traps. `age >= 18` is true for somebody
whose age was never recorded, in Stata and here alike. That is deliberate: a
figure this platform reports should be the figure the do-file produced, and
somebody checking it against their own Stata run should find the same number.
"""

from __future__ import annotations

import duckdb
import pytest

from app.services.stata_expr import translate

# x is missing, y holds 5, s is missing text, t holds "b".
COLUMNS = {"x": "number", "y": "number", "s": "text", "t": "text"}


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect()
    connection.execute("create table one(x double, y double, s varchar, t varchar)")
    connection.execute("insert into one values (NULL, 5, NULL, 'b')")
    return connection


def answer(con, expression: str) -> int:
    """What the expression says about the one row, as Stata's 1 or 0."""
    sql = translate(expression, COLUMNS, lambda name: f'"{name}"')
    got = con.execute(f"select ({sql}) from one").fetchone()[0]
    # A condition in Stata is 1 or 0 and never missing. If this ever returns
    # None the expression has gone back to three-valued logic, which is the
    # whole bug, so it is reported as such rather than quietly read as false.
    assert got is not None, f"{expression} answered NULL, not true or false: {sql}"
    return int(bool(got))


# --- Relational operators, one side missing ----------------------------------


@pytest.mark.parametrize(
    ("expression", "stata"),
    [
        # Missing is larger than any number, so it is greater than all of them.
        ("x > 1", 1),
        ("x >= 1", 1),
        ("x > 1000000", 1),
        ("x < 1", 0),
        ("x <= 1", 0),
        ("x == 1", 0),
        ("x != 1", 1),
        # And a number is correspondingly smaller than a missing.
        ("y > x", 0),
        ("y >= x", 0),
        ("y < x", 1),
        ("y <= x", 1),
        ("y == x", 0),
        ("y != x", 1),
        # Both missing. Equal to each other, and neither strictly larger.
        ("x == x", 1),
        ("x != x", 0),
        ("x > x", 0),
        ("x >= x", 1),
        ("x < x", 0),
        ("x <= x", 1),
        # Against the literal missing, which is how Stata asks the question.
        ("x == .", 1),
        ("x != .", 0),
        ("y == .", 0),
        ("y != .", 1),
        ("missing(x)", 1),
        ("mi(x)", 1),
        ("missing(y)", 0),
    ],
)
def test_a_comparison_answers_what_stata_answers(con, expression, stata):
    assert answer(con, expression) == stata


# --- The helpers a recode cascade is written with ----------------------------


@pytest.mark.parametrize(
    ("expression", "stata"),
    [
        # inlist is "equal to any of these", so a missing is in none of them.
        ("inlist(x, 1, 2)", 0),
        ("inlist(x, 1, 2, 3, 4)", 0),
        # This is the line the bug was found in. It has to be true.
        ("!inlist(x, 1, 2)", 1),
        ("~inlist(x, 1, 2)", 1),
        # Unless the list holds a missing itself, which Stata counts as a match.
        ("inlist(x, 1, .)", 1),
        ("inlist(y, 5, .)", 1),
        ("inlist(y, 1, 2)", 0),
        ("inlist(y, 1, 5)", 1),
        # inrange is "at least the low and at most the high", so a missing,
        # being above every high, is in no range.
        ("inrange(x, 1, 9)", 0),
        ("inrange(x, 1, 1000000)", 0),
        ("inrange(y, 1, 9)", 1),
        ("inrange(y, 6, 9)", 0),
        ("!inrange(x, 1, 9)", 1),
    ],
)
def test_the_helpers_answer_what_stata_answers(con, expression, stata):
    assert answer(con, expression) == stata


def test_the_line_the_whole_bug_was_about(con):
    """The end of a recode cascade, in the shape people actually write it.

    Before this, the translation reached DuckDB as `NOT ("x" IN (1, 2))`, which
    is NULL for a missing x and so matched nothing. A survey where this is the
    "not in employment" rule reports nobody as not in employment.
    """
    assert answer(con, "!inlist(x, 1, 2) & y == 5") == 1


# --- Logical operators -------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "stata"),
    [
        # Zero is false and everything else is true, and missing is not zero.
        ("x & 1", 1),
        ("x | 0", 1),
        ("!x", 0),
        ("y & 1", 1),
        ("!y", 0),
        # A comparison is already 1 or 0, so negating one is ordinary.
        ("!(y == 5)", 0),
        ("!(y == 4)", 1),
        ("(x > 1) & (y == 5)", 1),
        ("(x < 1) | (y == 5)", 1),
        ("(x < 1) | (y == 4)", 0),
    ],
)
def test_a_logical_operator_answers_what_stata_answers(con, expression, stata):
    assert answer(con, expression) == stata


# --- Where the rule stays out of the way -------------------------------------


def test_arithmetic_leaves_missing_missing(con):
    """`. + 1` is missing in Stata, and NULL + 1 is NULL in SQL.

    This is the one place the two already agree, so the missing rule has no
    business here: a value built from a missing is missing, not a very large
    number that would be summed and charted as one.
    """
    sql = translate("x + 1", COLUMNS, lambda name: f'"{name}"')
    assert con.execute(f"select {sql} from one").fetchone()[0] is None

    sql = translate("x * 2", COLUMNS, lambda name: f'"{name}"')
    assert con.execute(f"select {sql} from one").fetchone()[0] is None

    sql = translate("y + 1", COLUMNS, lambda name: f'"{name}"')
    assert con.execute(f"select {sql} from one").fetchone()[0] == 6


def test_a_count_of_a_derived_flag_is_not_inflated_by_arithmetic(con):
    """Guards the reason arithmetic must not take the comparison's rule.

    `gen adult = age >= 18` is 1 for a missing age, which is Stata's answer and
    deliberate. But `gen next = age + 1` must stay missing, or `egen total =
    sum(next)` quietly adds a sentinel to somebody's total.
    """
    flag = translate("x >= 18", COLUMNS, lambda name: f'"{name}"')
    assert con.execute(f"select CAST(({flag}) AS INTEGER) from one").fetchone()[0] == 1
    shifted = translate("x + 1", COLUMNS, lambda name: f'"{name}"')
    assert con.execute(f"select sum({shifted}) from one").fetchone()[0] is None


# --- Text orders missing the other way ---------------------------------------


@pytest.mark.parametrize(
    ("expression", "stata"),
    [
        # Stata's string missing is "", which sorts below every other string.
        ('s == ""', 1),
        ('s != ""', 0),
        # A missing string is "" and really does sort below "a", so unlike a
        # missing number this comparison is true rather than vacuous.
        ('s < "a"', 1),
        ('s > "a"', 0),
        ('t > "a"', 1),
        ('t > s', 1),
        ('s < t', 1),
        ('s == t', 0),
        ('t == "b"', 1),
        ("missing(s)", 1),
        ("missing(t)", 0),
    ],
)
def test_text_orders_missing_below_everything(con, expression, stata):
    assert answer(con, expression) == stata
