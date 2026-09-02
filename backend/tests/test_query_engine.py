"""The SQL compiler and its safety guarantees."""

from __future__ import annotations

import pytest

from app.schemas.query import (
    Aggregation,
    Condition,
    Dimension,
    FilterGroup,
    FilterOperator,
    Measure,
    QuerySpec,
    SortSpec,
)
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    SQLBuilder,
    VariableInfo,
    quote_ident,
)


@pytest.fixture
def ctx() -> DatasetContext:
    return DatasetContext(
        dataset_id="d1",
        parquet_path="/data/d1/data.parquet",
        variables={
            "region": VariableInfo("region", "Region", "categorical", {"1": "North"}),
            "age": VariableInfo("age", "Age", "numeric"),
            "income": VariableInfo("income", "Income", "numeric"),
            "weight": VariableInfo("weight", "Weight", "numeric"),
            "visited_at": VariableInfo("visited_at", "Visit date", "datetime"),
        },
    )


def test_unknown_variable_is_rejected(ctx):
    spec = QuerySpec(dimensions=[Dimension(variable="does_not_exist")])
    with pytest.raises(QueryError, match="Unknown variable"):
        SQLBuilder(ctx).build_aggregate(spec)


def test_injection_via_variable_name_is_blocked(ctx):
    spec = QuerySpec(dimensions=[Dimension(variable='region"; DROP TABLE users; --')])
    with pytest.raises(QueryError, match="Unknown variable"):
        SQLBuilder(ctx).build_aggregate(spec)


def test_identifier_quoting_escapes_double_quotes():
    assert quote_ident('we"ird') == '"we""ird"'


def test_filter_values_are_parameterised(ctx):
    spec = QuerySpec(
        dimensions=[Dimension(variable="region")],
        filters=FilterGroup(
            conditions=[
                Condition(
                    variable="age", operator=FilterOperator.gte, value="'; DELETE FROM x --"
                )
            ]
        ),
    )
    sql, params = SQLBuilder(ctx).build_aggregate(spec)
    assert "DELETE" not in sql
    assert params == ["'; DELETE FROM x --"]


def test_aggregate_sql_shape(ctx):
    spec = QuerySpec(
        dimensions=[Dimension(variable="region")],
        measures=[
            Measure(agg=Aggregation.count, alias="n"),
            Measure(agg=Aggregation.mean, variable="income", alias="avg_income"),
        ],
        sort=[SortSpec(field="n", direction="desc")],
        limit=25,
    )
    sql, _ = SQLBuilder(ctx).build_aggregate(spec)
    assert 'COUNT(*) AS "n"' in sql
    assert 'AVG("income") AS "avg_income"' in sql
    assert "GROUP BY 1" in sql
    assert 'ORDER BY "n" DESC NULLS LAST' in sql
    assert "LIMIT 25" in sql


def test_weighted_mean_uses_weight_column(ctx):
    spec = QuerySpec(
        measures=[Measure(agg=Aggregation.mean, variable="income", weight="weight")]
    )
    sql, _ = SQLBuilder(ctx).build_aggregate(spec)
    assert 'SUM("income" * "weight")' in sql
    assert 'NULLIF' in sql


def test_weighted_count_sums_the_weight(ctx):
    spec = QuerySpec(measures=[Measure(agg=Aggregation.count, weight="weight", alias="n")])
    sql, _ = SQLBuilder(ctx).build_aggregate(spec)
    assert 'SUM("weight")' in sql


def test_date_grain_truncates(ctx):
    spec = QuerySpec(dimensions=[Dimension(variable="visited_at", grain="month")])
    sql, _ = SQLBuilder(ctx).build_aggregate(spec)
    assert "date_trunc('month', \"visited_at\")" in sql


def test_binning_requires_numeric(ctx):
    spec = QuerySpec(dimensions=[Dimension(variable="region", bin_width=10)])
    with pytest.raises(QueryError, match="not numeric"):
        SQLBuilder(ctx).build_aggregate(spec)


def test_binning_numeric_variable(ctx):
    spec = QuerySpec(dimensions=[Dimension(variable="age", bin_width=10)])
    sql, _ = SQLBuilder(ctx).build_aggregate(spec)
    assert 'floor("age" / 10.0) * 10.0' in sql


def test_sorting_by_unknown_field_is_rejected(ctx):
    spec = QuerySpec(
        dimensions=[Dimension(variable="region")],
        sort=[SortSpec(field="not_selected", direction="asc")],
    )
    with pytest.raises(QueryError, match="Cannot sort by unknown field"):
        SQLBuilder(ctx).build_aggregate(spec)


def test_in_filter_expands_placeholders(ctx):
    spec = QuerySpec(
        filters=FilterGroup(
            conditions=[
                Condition(variable="region", operator=FilterOperator.in_, value=["a", "b", "c"])
            ]
        )
    )
    sql, params = SQLBuilder(ctx).build_aggregate(spec)
    assert "IN (?, ?, ?)" in sql
    assert params == ["a", "b", "c"]


def test_between_requires_two_values(ctx):
    spec = QuerySpec(
        filters=FilterGroup(
            conditions=[Condition(variable="age", operator=FilterOperator.between, value=[5])]
        )
    )
    with pytest.raises(QueryError, match="two element list"):
        SQLBuilder(ctx).build_aggregate(spec)


def test_contains_escapes_wildcards(ctx):
    spec = QuerySpec(
        filters=FilterGroup(
            conditions=[
                Condition(variable="region", operator=FilterOperator.contains, value="50%_x")
            ]
        )
    )
    _, params = SQLBuilder(ctx).build_aggregate(spec)
    assert params == [r"%50\%\_x%"]


def test_not_equal_keeps_null_rows(ctx):
    spec = QuerySpec(
        filters=FilterGroup(
            conditions=[Condition(variable="region", operator=FilterOperator.ne, value="North")]
        )
    )
    sql, _ = SQLBuilder(ctx).build_aggregate(spec)
    assert '"region" IS NULL OR "region" != ?' in sql


def test_nested_filter_groups(ctx):
    spec = QuerySpec(
        filters=FilterGroup(
            op="and",
            conditions=[Condition(variable="age", operator=FilterOperator.gte, value=18)],
            groups=[
                FilterGroup(
                    op="or",
                    conditions=[
                        Condition(variable="region", operator=FilterOperator.eq, value="N"),
                        Condition(variable="region", operator=FilterOperator.eq, value="S"),
                    ],
                )
            ],
        )
    )
    sql, params = SQLBuilder(ctx).build_aggregate(spec)
    assert " OR " in sql and " AND " in sql
    assert params == [18.0, "N", "S"]


def test_measure_requiring_a_variable_is_validated():
    with pytest.raises(ValueError, match="requires a variable"):
        Measure(agg=Aggregation.mean)


def test_label_filter_translates_to_stored_code(ctx):
    spec = QuerySpec(
        filters=FilterGroup(
            conditions=[
                Condition(
                    variable="region",
                    operator=FilterOperator.eq,
                    value="North",
                    use_label=True,
                )
            ]
        )
    )
    _, params = SQLBuilder(ctx).build_aggregate(spec)
    assert params == ["1"]


def test_default_measure_is_a_count():
    assert QuerySpec().measures[0].agg == Aggregation.count
