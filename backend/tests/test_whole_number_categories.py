"""A whole number heads a row as "1", not "1.0".

An age or a code column is stored as a double as soon as one interview leaves
it blank. A value with a label of its own was always shown by its label, but
one without - most ages - was printed as the double, so an age-by-sex table
read "Less than one year", then "1.0", "2.0", "3.0" down the side.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.schemas.query import CrosstabRequest
from app.services.export_tables import _text
from app.services.query_engine import (
    DatasetContext,
    VariableInfo,
    category_text,
    distinct_values,
    execute_crosstab,
    execute_frequency,
)


@pytest.fixture
def ctx(tmp_path) -> DatasetContext:
    path = tmp_path / "people.parquet"
    pd.DataFrame(
        {
            # The blank is what makes the column a double.
            "age": [0.0, 1.0, 1.0, 2.0, 12.0, np.nan, 2.5],
            "sex": [1, 2, 1, 2, 1, 2, 1],
        }
    ).to_parquet(path)
    return DatasetContext(
        dataset_id="d",
        parquet_path=str(path),
        variables={
            "age": VariableInfo(
                name="age",
                var_type="numeric",
                value_labels={"0": "Less than one year"},
                storage_type="float64",
            ),
            "sex": VariableInfo(
                name="sex",
                var_type="categorical",
                value_labels={"1": "Male", "2": "Female"},
                storage_type="int64",
            ),
        },
    )


def test_a_crosstab_heads_its_rows_with_whole_numbers(ctx):
    table = execute_crosstab(ctx, CrosstabRequest(row_variable="age", column_variable="sex"))
    assert table.row_labels[:5] == ["Less than one year", "1", "2", "2.5", "12"]
    assert table.column_labels == ["Male", "Female"]


def test_codes_shown_without_labels_are_whole_numbers_too(ctx):
    table = execute_crosstab(
        ctx, CrosstabRequest(row_variable="age", column_variable="sex", use_labels=False)
    )
    assert table.row_labels[:5] == ["0", "1", "2", "2.5", "12"]


def test_a_frequency_table_and_a_filter_dropdown_read_the_same(ctx):
    labels = [row.label for row in execute_frequency(ctx, "age").rows]
    assert "1" in labels and "12" in labels and "1.0" not in labels
    dropdown = {item["label"] for item in distinct_values(ctx, "age")}
    assert dropdown == {"Less than one year", "1", "2", "2.5", "12"}


def test_the_text_a_category_is_written_as():
    info = VariableInfo(name="age", value_labels={"0": "Less than one year"})
    assert category_text(info, 0.0) == "Less than one year"
    assert category_text(info, 3.0) == "3"
    assert category_text(info, 3.25) == "3.25"
    assert category_text(info, 3.0, use_labels=False) == "3"
    assert category_text(None, "Rented") == "Rented"


def test_a_document_export_writes_them_the_same_way():
    assert _text(4.0) == "4"
    assert _text(4.5) == "4.5"
    assert _text("Less than one year") == "Less than one year"
