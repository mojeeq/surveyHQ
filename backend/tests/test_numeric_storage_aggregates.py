"""What a measure is allowed to do to a number on its way to being summed.

Offering a value-labelled BIGINT for a mean was the point of the change that
made numbers measurable, and it arrived at a compiler that decided how to
aggregate by asking `is_numeric` - the analytical judgement. A labelled code
set answers no to that, so the column went through `try_cast(... AS DOUBLE)`,
which exists for the other case entirely: a column of numbers written as text,
where a cast is the only way to get a mean at all.

A double carries 53 bits. A sum of two BIGINTs either side of 2**53 comes back
two short, and a sum of three DECIMAL(18,3) comes back 0.6000000000000001.
Silently, with no error anywhere, on exactly the variables that were newly
offered.

So the cast asks whether the column is stored as a number, which is the
question it always meant. The same question settles a survey weight: the
picker offers what can be measured, and the compiler used to refuse what the
picker had just offered.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from app.schemas.query import Aggregation, Measure, QuerySpec
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    SQLBuilder,
    VariableInfo,
    execute_query,
    execute_summary,
)

# Either side of 2**53, which is where a double stops counting in ones.
BIG = 9007199254740993
WIDE_SUM = BIG + 1


@pytest.fixture
def ctx(tmp_path: Path) -> DatasetContext:
    """A dataset whose numbers are stored as numbers and read as code sets.

    `tenure` and `amount` carry value labels, so the importer calls them
    categorical however they are stored. That is the right reading - somebody
    named the codes - and it is not a licence to round them.
    """
    path = tmp_path / "data.parquet"
    duckdb.connect().execute(
        f"""
        COPY (SELECT * FROM (VALUES
            ({BIG}::BIGINT, 0.1::DECIMAL(18,3), 'North', 2.0::DOUBLE, '7'),
            (1::BIGINT,     0.2::DECIMAL(18,3), 'North', 3.0::DOUBLE, '9'),
            (0::BIGINT,     0.3::DECIMAL(18,3), 'South', 5.0::DOUBLE, 'n/a')
        ) v(tenure, amount, region, weight, written))
        TO '{path}' (FORMAT PARQUET)
        """
    )
    labels = {"0": "Owned", "1": "Rented"}
    return DatasetContext(
        dataset_id="d1",
        parquet_path=str(path),
        variables={
            "tenure": VariableInfo("tenure", "Tenure", "categorical", labels, [], "BIGINT"),
            "amount": VariableInfo("amount", "Amount", "categorical", labels, [], "DECIMAL(18,3)"),
            "region": VariableInfo("region", "Region", "categorical", {}, [], "VARCHAR"),
            "weight": VariableInfo("weight", "Weight", "categorical", labels, [], "DOUBLE"),
            # Numbers that were exported as text, which is what the cast is for.
            "written": VariableInfo("written", "Written", "text", {}, [], "VARCHAR"),
        },
    )


def _sum(ctx: DatasetContext, variable: str):
    spec = QuerySpec(
        measures=[Measure(agg=Aggregation.sum, variable=variable, alias="total")]
    )
    return execute_query(ctx, spec).rows[0][0]


# --- the rounding ------------------------------------------------------------


def test_a_wide_integer_is_summed_as_an_integer(ctx):
    """Through a double this came back 9007199254740992: two short, no error."""
    assert _sum(ctx, "tenure") == WIDE_SUM


def test_a_decimal_keeps_its_scale(ctx):
    """0.1 + 0.2 + 0.3 is 0.6, and through a double it is 0.6000000000000001."""
    assert float(_sum(ctx, "amount")) == 0.6


def test_the_same_holds_for_descriptive_statistics(ctx):
    """execute_summary compiles its own cast and had the same bug."""
    stats = execute_summary(ctx, ["tenure"])
    assert stats[0].sum == WIDE_SUM


def test_numbers_written_as_text_are_still_cast(ctx):
    """The case the cast was put there for, which has to keep working: two
    readable numbers and an "n/a" that becomes a null rather than an error."""
    assert _sum(ctx, "written") == 16


def test_text_that_is_not_a_number_is_null_rather_than_an_error(ctx):
    assert _sum(ctx, "region") is None


# --- what the compiler writes ------------------------------------------------


@pytest.mark.parametrize("variable", ["tenure", "amount", "weight"])
def test_a_stored_number_is_not_wrapped(ctx, variable):
    sql, _ = SQLBuilder(ctx).build_aggregate(
        QuerySpec(measures=[Measure(agg=Aggregation.mean, variable=variable, alias="m")])
    )
    assert "try_cast" not in sql


def test_text_is_wrapped(ctx):
    sql, _ = SQLBuilder(ctx).build_aggregate(
        QuerySpec(measures=[Measure(agg=Aggregation.mean, variable="written", alias="m")])
    )
    assert "try_cast" in sql


# --- survey weights ----------------------------------------------------------


def test_a_weight_stored_as_a_number_is_accepted(ctx):
    """The picker offers what can be measured. A labelled DOUBLE is on that
    list, and choosing it used to fail the query outright."""
    spec = QuerySpec(
        measures=[
            Measure(agg=Aggregation.sum, variable="tenure", weight="weight", alias="total")
        ]
    )
    sql, _ = SQLBuilder(ctx).build_aggregate(spec)
    assert '"weight"' in sql


def test_a_weight_that_is_not_stored_as_a_number_is_still_refused(ctx):
    """Multiplying by a province name is not an opinion anyone can hold."""
    spec = QuerySpec(
        measures=[
            Measure(agg=Aggregation.sum, variable="tenure", weight="region", alias="total")
        ]
    )
    with pytest.raises(QueryError, match="must be stored as a number"):
        SQLBuilder(ctx).build_aggregate(spec)


def test_an_old_dataset_without_a_recorded_storage_type_is_unchanged(tmp_path: Path):
    """Ingested before storage types were written, so the only thing left to go
    on is the judgement - which is what this decision used on its own before."""
    path = tmp_path / "old.parquet"
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES (1.5::DOUBLE), (2.5::DOUBLE)) v(x)) "
        f"TO '{path}' (FORMAT PARQUET)"
    )
    ctx = DatasetContext(
        dataset_id="old",
        parquet_path=str(path),
        variables={"x": VariableInfo("x", "X", "numeric", {}, [], "")},
    )
    assert _sum(ctx, "x") == 4.0
