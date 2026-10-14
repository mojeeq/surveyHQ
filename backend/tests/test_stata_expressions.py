"""Translating a Stata expression into SQL, and refusing everything else.

The expression is typed by a user and ends up in a query, so what is not
recognised has to be refused rather than passed along. These cover both halves:
the idioms that should work, and the things that must not.
"""

from __future__ import annotations

import pytest

from app.services.stata_expr import ExpressionError, translate

COLUMNS = {
    "age": "number",
    "sex": "number",
    "income": "number",
    "region": "number",
    "name": "text",
}


def sql(expression: str) -> str:
    return translate(expression, COLUMNS, lambda n: f'"{n}"')


def value(expression: str, **row: object):
    """What the expression evaluates to over one row of given values.

    The SQL these build is NULL-aware and so no longer a short string worth
    pinning by eye - see test_stata_missing for why it has to be. What is worth
    pinning is what it answers, so these run it.
    """
    import duckdb

    names = list(COLUMNS)
    con = duckdb.connect()
    types = ", ".join(
        f'"{n}" {"VARCHAR" if COLUMNS[n] == "text" else "DOUBLE"}' for n in names
    )
    con.execute(f"create table one({types})")
    con.execute(
        f"insert into one values ({', '.join('?' for _ in names)})",
        [row.get(n) for n in names],
    )
    return con.execute(f"select ({sql(expression)}) from one").fetchone()[0]


def test_arithmetic_and_variables():
    assert value("age + 1", age=30) == 31
    assert value("income / 12", income=120) == 10


def test_stata_operators_become_sql_ones():
    assert value("age == 30", age=30) is True
    assert value("age == 30", age=31) is False
    assert value("sex != 1", sex=2) is True
    assert value("age > 18 & sex == 2", age=20, sex=2) is True
    assert value("age > 18 & sex == 2", age=20, sex=1) is False
    assert value("age < 18 | age > 65", age=70) is True
    assert value("age < 18 | age > 65", age=40) is False


def test_missing_is_null():
    """A dot is Stata's missing, and `== .` is how it is tested."""
    assert sql("income == .") == '("income" IS NULL)'
    assert sql("missing(income)") == '("income" IS NULL)'
    assert sql("mi(income)") == '("income" IS NULL)'
    assert value("income != .", income=None) is False
    assert value("income != .", income=5) is True


def test_the_helpers_people_actually_type():
    assert value("inlist(region, 1, 2, 3)", region=2) is True
    assert value("inlist(region, 1, 2, 3)", region=4) is False
    assert value("inrange(age, 18, 65)", age=30) is True
    assert value("inrange(age, 18, 65)", age=70) is False
    assert value("cond(age > 18, 1, 0)", age=20) == 1
    assert value("cond(age > 18, 1, 0)", age=10) == 0


def test_string_literals_are_re_emitted_not_pasted():
    """A quote inside a literal must not be able to end it early."""
    built = sql('name == "O\'Brien"')
    assert "'O''Brien'" in built
    assert value('name == "O\'Brien"', name="O'Brien") is True
    assert value('name == "O\'Brien"', name="Smith") is False


def test_casts():
    assert sql("string(age)") == 'CAST("age" AS VARCHAR)'
    assert sql("real(name)") == 'TRY_CAST("name" AS DOUBLE)'


def test_a_variable_that_does_not_exist_is_named():
    with pytest.raises(ExpressionError, match="'height' is not a variable"):
        sql("height + 1")


def test_an_unlisted_function_is_refused():
    with pytest.raises(ExpressionError, match="not a function"):
        sql("system(age)")


@pytest.mark.parametrize(
    "attempt",
    [
        "age; DROP TABLE users",
        "age) UNION SELECT * FROM users --",
        "age + (SELECT count(*) FROM users)",
        "age /* comment */ + 1",
        "read_csv('/etc/passwd')",
        "age' OR '1'='1",
    ],
)
def test_sql_that_is_not_an_expression_is_refused(attempt):
    """None of these are Stata, and none of them reach the database."""
    with pytest.raises(ExpressionError):
        sql(attempt)


def test_an_unclosed_bracket_is_reported():
    with pytest.raises(ExpressionError):
        sql("inlist(region, 1")


def test_a_sign_does_not_capture_the_exponent():
    """`-age^2` is `-(age^2)` in Stata, not `(-age)^2`.

    Exponentiation binds tighter than the sign in front of it, so for age 2
    this is -4. Worth pinning because the two differ only in sign and a chart
    of the wrong one looks plausible.
    """
    assert value("-age^2", age=2) == -4
    assert value("(-age)^2", age=2) == 4
    assert value("-age^3", age=2) == -8


def test_exponents_go_left_to_right_as_stata_does():
    """Stata evaluates operators of equal precedence left to right, so this is
    `(2^3)^2` and not `2^(3^2)`: 64, not 512."""
    assert value("age^3^2", age=2) == 64


def test_a_signed_exponent_still_parses():
    assert value("age^-1", age=2) == 0.5
    assert value("age^(-2)", age=2) == 0.25


def test_mixed_addition_is_a_type_mismatch_rather_than_a_join():
    """Stata refuses `name + age`, and so does this.

    Concatenating them would make "Alice30" out of an expression whose author
    meant arithmetic, which is exactly the silent coercion this module exists
    to avoid. The message says both ways to resolve it.
    """
    with pytest.raises(ExpressionError, match="one side of it is text"):
        sql("name + age")
    with pytest.raises(ExpressionError, match="string"):
        sql("name + age")
    # Two strings do join, as they do in Stata.
    assert value('name + "!"', name="hi") == "hi!"
    # And two numbers are still arithmetic.
    assert value("age + 1", age=30) == 31


def test_text_in_other_arithmetic_is_refused_too():
    for attempt in ("name * 2", "name - 1", "name / 2", "age * name"):
        with pytest.raises(ExpressionError, match="needs numbers"):
            sql(attempt)
