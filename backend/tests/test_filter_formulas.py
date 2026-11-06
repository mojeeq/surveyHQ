"""Arithmetic in a filter: `inc2020 - inc2019 > 100`, `total != boys + girls`.

A condition compared one column with a value or with one other column, so a
change between two rounds, or a total that should equal its parts, could not
be asked at all. A condition can now carry a sum on either side, read by the
indicator formula reader and compiled with names quoted and numbers bound.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.dashboards import Allowance, _applicable, _ignored
from app.schemas.query import Condition, FilterGroup
from app.services.quality import logic_condition
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    SQLBuilder,
    VariableInfo,
    run_sql,
)


@pytest.fixture
def ctx(tmp_path) -> DatasetContext:
    path = tmp_path / "households.parquet"
    pd.DataFrame(
        {
            "hh": ["a", "b", "c", "d", "e"],
            "inc2019": [100.0, 300.0, 250.0, np.nan, 0.0],
            "inc2020": [250.0, 350.0, 500.0, 400.0, 50.0],
            "total": [3, 4, 5, 2, 0],
            "boys": [1, 2, 2, 1, 0],
            "girls": [2, 2, 2, np.nan, 0],
            # A count kept as text, as a CSV sometimes arrives.
            "rooms": ["2", "3", "x", "1", "1"],
        }
    ).to_parquet(path)
    names = {
        "hh": "object",
        "inc2019": "float64",
        "inc2020": "float64",
        "total": "int64",
        "boys": "int64",
        "girls": "float64",
        "rooms": "object",
    }
    return DatasetContext(
        dataset_id="d",
        parquet_path=str(path),
        variables={
            name: VariableInfo(
                name=name,
                var_type="text" if kind == "object" else "numeric",
                storage_type=kind,
            )
            for name, kind in names.items()
        },
    )


def matching(ctx: DatasetContext, *conditions: Condition, op: str = "and") -> list[str]:
    builder = SQLBuilder(ctx)
    where = builder.filter_sql(FilterGroup(op=op, conditions=list(conditions)))
    _, rows = run_sql(
        f"SELECT hh FROM read_parquet('{ctx.parquet_path}') WHERE {where} ORDER BY hh",
        builder.params,
    )
    return [row[0] for row in rows]


def sum_(formula: str, operator: str, value=None, **extra) -> Condition:
    return Condition(variable="inc2020", formula=formula, operator=operator, value=value, **extra)


def test_a_difference_against_a_number(ctx):
    # a +150, b +50, c +250, d unknown (no 2019 income), e +50
    assert matching(ctx, sum_("inc2020 - inc2019", "gt", "100")) == ["a", "c"]
    assert matching(ctx, sum_("inc2020 - inc2019", "lte", 50)) == ["b", "e"]


def test_a_row_missing_a_value_is_judged_neither_way(ctx):
    # d has no 2019 income, so it is in neither the rows above 100 nor the
    # rows at or below it - which is what keeps a logic check from reporting
    # every household with a blank as breaking the rule.
    above = matching(ctx, sum_("inc2020 - inc2019", "gt", 100))
    below = matching(ctx, sum_("inc2020 - inc2019", "lte", 100))
    assert "d" not in above + below


def test_a_total_against_the_sum_of_its_parts(ctx):
    condition = Condition(variable="total", operator="ne", other_formula="boys + girls")
    assert matching(ctx, condition) == ["c"]


def test_brackets_a_leading_minus_and_division(ctx):
    growth = sum_("(inc2020 - inc2019) / inc2019 * 100", "gte", 100)
    assert matching(ctx, growth) == ["a", "c"]
    # e earned nothing in 2019: no growth rate, rather than a failed query.
    assert "e" not in matching(ctx, sum_("inc2020 / inc2019", "gte", 0))
    assert matching(ctx, sum_("-inc2019 + inc2020", "gt", 200)) == ["c"]


def test_sum_against_another_column_and_a_column_kept_as_text(ctx):
    assert matching(
        ctx,
        Condition(variable="boys", operator="lt", formula="boys * 2", other_variable="total"),
    ) == ["a", "c"]
    # "x" is not a number and drops out; the rest are read as numbers.
    assert matching(ctx, Condition(variable="rooms", operator="gte", formula="rooms + 1", value=3)) == [
        "a",
        "b",
    ]


def test_a_logic_check_flags_the_rows_that_break_the_rule(ctx):
    config = {
        "flag": "no_match",
        "condition": {
            "op": "and",
            "conditions": [{"variable": "total", "operator": "eq", "other_formula": "boys + girls"}],
            "groups": [],
        },
    }
    where, params = logic_condition(ctx, config)
    _, rows = run_sql(
        f"SELECT hh FROM read_parquet('{ctx.parquet_path}') WHERE {where} ORDER BY hh", params
    )
    # c says 5 people and lists 4; d has no count of girls, so is not judged.
    assert [row[0] for row in rows] == ["c"]


def test_only_the_six_comparisons_and_readable_sums_are_accepted():
    with pytest.raises(ValidationError, match="cannot compare a sum"):
        Condition(variable="a", formula="a + b", operator="in", value=[1])
    with pytest.raises(ValidationError, match="Cannot read"):
        Condition(variable="a", formula="a + * b", operator="gt", value=1)


def test_the_sql_is_built_from_the_tree_not_the_text(ctx):
    # Anything that is not a number, a name, an operator or a bracket is
    # refused before it is near SQL; a name is looked up and quoted.
    with pytest.raises(ValidationError):
        Condition(variable="inc2020", formula="inc2020; DROP TABLE x", operator="gt", value=1)
    with pytest.raises(QueryError, match="Unknown variable|not found|unknown"):
        matching(ctx, sum_("inc2020 - secret", "gt", 1))
    with pytest.raises(QueryError, match="compared with a number"):
        matching(ctx, sum_("inc2020 - inc2019", "gt", "lots"))


def test_every_column_a_condition_reads():
    condition = Condition(
        variable="total",
        operator="ne",
        formula="total * 2",
        other_formula="boys + girls - adults",
    )
    assert condition.variables() == ["total", "adults", "boys", "girls"]
    assert Condition(variable="a", operator="lt", other_variable="b").variables() == ["a", "b"]


def test_a_dashboard_filter_from_outside_may_only_name_what_the_page_shows():
    allowed = Allowance(anything=frozenset({"province", "inc2020"}), ticked_only=frozenset({"q__1"}))
    assert allowed.admits(Condition(variable="province", operator="eq", value="North"))
    # The condition is filed under a column on the page, but the sum and the
    # second variable read columns that are not.
    assert not allowed.admits(sum_("inc2020 - phone", "gt", 0))
    assert not allowed.admits(Condition(variable="province", operator="eq", other_variable="phone"))
    assert allowed.admits(Condition(variable="q__1", operator="selected"))
    assert not allowed.admits(
        Condition(variable="q__1", operator="gt", formula="q__1 + province", value=0)
    )


def test_a_dataset_without_a_column_in_the_sum_drops_the_condition(ctx):
    filters = FilterGroup(
        conditions=[
            sum_("inc2020 - inc2019", "gt", 0),
            sum_("inc2020 - inc2018", "gt", 0),
        ]
    )
    kept = _applicable(filters, ctx)
    assert kept is not None and [c.formula for c in kept.conditions] == ["inc2020 - inc2019"]
    assert _ignored(filters, ctx) == ["inc2018"]
