"""Translating a Stata expression into SQL, and refusing everything else.

The expression is typed by a user and ends up in a query, so what is not
recognised has to be refused rather than passed along. These cover both halves:
the idioms that should work, and the things that must not.
"""

from __future__ import annotations

import pytest

from app.services.stata_expr import ExpressionError, translate

COLUMNS = {"age", "sex", "income", "region", "name"}


def sql(expression: str) -> str:
    return translate(expression, COLUMNS, lambda n: f'"{n}"')


def test_arithmetic_and_variables():
    assert sql("age + 1") == '"age"+1'
    assert sql("income / 12") == '"income"/12'


def test_stata_operators_become_sql_ones():
    assert sql("age == 30") == '"age"=30'
    assert sql("sex != 1") == '"sex"<>1'
    assert sql("age > 18 & sex == 2") == '"age">18 AND "sex"=2'
    assert sql("age < 18 | age > 65") == '"age"<18 OR "age">65'


def test_missing_is_null():
    """A dot is Stata's missing, and `== .` is how it is tested."""
    assert sql("income == .") == '"income" IS NULL'
    assert sql("income != .") == '"income" IS NOT NULL'
    assert sql("missing(income)") == '("income" IS NULL)'
    assert sql("mi(income)") == '("income" IS NULL)'


def test_the_helpers_people_actually_type():
    assert sql("inlist(region, 1, 2, 3)") == '("region" IN (1, 2, 3))'
    assert sql("inrange(age, 18, 65)") == '("age" BETWEEN 18 AND 65)'
    assert sql("cond(age > 18, 1, 0)") == '(CASE WHEN "age">18 THEN 1 ELSE 0 END)'


def test_string_literals_are_re_emitted_not_pasted():
    """A quote inside a literal must not be able to end it early."""
    assert sql('name == "O\'Brien"') == '"name"=\'O\'\'Brien\''


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
