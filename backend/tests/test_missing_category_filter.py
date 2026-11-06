"""Filtering on the category a chart draws for records with no answer.

A chart draws the blanks as a category of their own - "-" for an empty cell,
"(blank)" and ".a" for a column carrying Stata's tagged missings - and a click
on it filters the page by the text it was drawn with. Against a number column
DuckDB refused the comparison outright ("Could not convert string '-' to
DOUBLE") and every widget the click reached failed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.schemas.query import Condition, FilterGroup, FilterOperator
from app.services.query_engine import DatasetContext, SQLBuilder, VariableInfo, run_sql

#  water: 1, 2, blank, 1, tagged .a ("refused"), blank
ROWS = [
    ("h1", 1.0, None, "Well"),
    ("h2", 2.0, None, None),
    ("h3", None, None, "Pipe"),
    ("h4", 1.0, None, "-"),
    ("h5", None, ".a", "Well"),
    ("h6", None, None, None),
]


@pytest.fixture
def ctx(tmp_path) -> DatasetContext:
    frame = pd.DataFrame(ROWS, columns=["hh", "water", "water__mv", "source"])
    path = tmp_path / "water.parquet"
    frame.to_parquet(path, index=False)
    return DatasetContext(
        "water",
        str(path),
        {
            "hh": VariableInfo("hh", storage_type="VARCHAR"),
            "water": VariableInfo(
                "water",
                var_type="categorical",
                value_labels={"1": "Piped", "2": "Well"},
                missing_tags=[".a"],
                storage_type="DOUBLE",
            ),
            "water__mv": VariableInfo("water__mv", storage_type="VARCHAR"),
            "source": VariableInfo("source", storage_type="VARCHAR"),
        },
    )


def households(ctx: DatasetContext, *conditions: Condition) -> list[str]:
    builder = SQLBuilder(ctx)
    where = builder.filter_sql(FilterGroup(conditions=list(conditions)))
    _, rows = run_sql(
        f"SELECT hh FROM read_parquet('{ctx.parquet_path}') WHERE {where} ORDER BY hh",
        builder.params,
    )
    return [row[0] for row in rows]


def where(variable: str, operator: str, value, use_label: bool = True) -> Condition:
    return Condition(
        variable=variable, operator=FilterOperator(operator), value=value, use_label=use_label
    )


def test_clicking_the_dash_on_a_number_column_finds_the_blanks(ctx):
    # The fault itself: this failed the query rather than finding h3 and h6.
    assert households(ctx, where("water", "eq", "-")) == ["h3", "h6"]


def test_the_blank_category_of_a_tagged_column_is_the_plain_blanks(ctx):
    # The tagged ".a" is drawn as a category of its own beside "(blank)".
    assert households(ctx, where("water", "eq", "(blank)")) == ["h3", "h6"]
    assert households(ctx, where("water", "eq", ".a")) == ["h5"]


def test_a_label_and_a_blank_together(ctx):
    assert households(ctx, where("water", "in", ["Piped", "-"])) == ["h1", "h3", "h4", "h6"]


def test_leaving_the_blanks_out(ctx):
    # Everything with an answer, the tagged refusal included: it is not blank.
    assert households(ctx, where("water", "ne", "-")) == ["h1", "h2", "h4", "h5"]
    assert households(ctx, where("water", "not_in", ["Piped", ".a"])) == ["h2", "h3", "h6"]


def test_text_that_is_no_number_matches_nothing_rather_than_failing(ctx):
    assert households(ctx, where("water", "eq", "abc", use_label=False)) == []
    assert households(ctx, where("water", "in", ["abc", "2"], use_label=False)) == ["h2"]


def test_a_text_column_keeps_its_dash(ctx):
    # A dash typed into a text answer is an answer, not a blank.
    assert households(ctx, where("source", "eq", "-")) == ["h4"]


def test_ordinary_comparisons_are_unchanged(ctx):
    assert households(ctx, where("water", "eq", "Well")) == ["h2"]
    assert households(ctx, where("water", "eq", 1, use_label=False)) == ["h1", "h4"]
    # "is not" keeps the blanks, as it always has.
    assert households(ctx, where("water", "ne", "Piped")) == ["h2", "h3", "h5", "h6"]
    builder = SQLBuilder(ctx)
    builder.filter_sql(FilterGroup(conditions=[where("water", "eq", "Well")]))
    assert builder.params == [2]
