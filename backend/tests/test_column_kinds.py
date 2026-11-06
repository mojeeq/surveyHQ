"""What a stored type is called, and what will go with what.

Two copies of this judgement existed - one in the Stata engine for `append`,
one in the query engine for a merge key - and they did not agree. Three types
came out differently, and in each case the merge engine's copy was the wrong
one:

    BOOLEAN    called "true or false" and so refused against a number, which
               DuckDB joins and stacks perfectly happily
    TIME       called text, because it is not DATE and has no TIMESTAMP in it
    INTERVAL   called a number, because INT is a substring of INTERVAL

So there is one copy now, and these are the cases worth writing down: the ones
that were wrong, and the distinction that replaced the wrongest of them.
"""

from __future__ import annotations

import duckdb
import pytest

from app.services.query_engine import compatible, kind_of


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("VARCHAR", "text"),
        ("BLOB", "text"),
        ("UUID", "text"),
        ("BIGINT", "a number"),
        ("DOUBLE", "a number"),
        ("DECIMAL(18,3)", "a number"),
        ("HUGEINT", "a number"),
        ("DATE", "a date"),
        ("TIMESTAMP", "a date"),
        # Matched on the start of the name and not anywhere in it. INTERVAL
        # contains INT and is not a number; TIME is neither DATE nor TIMESTAMP
        # and is not text.
        ("TIME", "a date"),
        ("INTERVAL", "a date"),
        ("BOOLEAN", "true or false"),
        # Opaque, and text is the safer thing to call it: it stops the column
        # being silently stacked onto a number.
        ("STRUCT(a INTEGER)", "text"),
    ],
)
def test_a_stored_type_is_called_what_it_is(stored, expected):
    assert kind_of(stored) == expected


def test_a_number_and_a_true_false_go_together():
    """0/1 and true/false are the same information.

    Called different things, because a message saying "a number" about a column
    of trues would be a lie, and treated as the same thing, because refusing
    them would stop a join and an append that both work. That is the whole
    reason `compatible` is not `==`.
    """
    assert compatible("a number", "true or false")
    assert compatible("true or false", "a number")


@pytest.mark.parametrize(
    ("one", "other"),
    [("a number", "text"), ("a date", "a number"), ("a date", "text"),
     ("text", "true or false")],
)
def test_the_rest_do_not(one, other):
    assert not compatible(one, other)


def test_duckdb_agrees_that_a_boolean_and_a_number_go_together():
    """The claim above, asked of the thing that would have to do the work.

    Pinned rather than asserted, because the whole grouping is a statement about
    what DuckDB will accept, and if that ever stopped being true this would be
    refusing nothing while the join failed underneath.
    """
    con = duckdb.connect()
    try:
        assert con.execute("SELECT true = 1").fetchall() == [(True,)]
        stacked = con.execute(
            "SELECT * FROM (SELECT true AS f) "
            "UNION ALL BY NAME SELECT * FROM (SELECT 1 AS f)"
        ).fetchall()
        assert len(stacked) == 2
    finally:
        con.close()


def test_a_boolean_is_not_offered_for_arithmetic():
    """Why BOOLEAN is not simply called "a number".

    Callers build SQL from this - the merge's key conversion renders a whole
    number whole with floor() - and floor(BOOLEAN) is not a function DuckDB has.
    Calling a boolean a number would write a query it refuses to bind.
    """
    assert kind_of("BOOLEAN") != "a number"
    con = duckdb.connect()
    try:
        with pytest.raises(duckdb.Error):
            con.execute("SELECT floor(true)").fetchall()
    finally:
        con.close()
