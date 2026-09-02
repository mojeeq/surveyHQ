"""Stata tagged missing values must survive ingestion and show in tabulations.

Stata distinguishes system missing (.) from tagged missing (.a to .z), and
Survey Solutions uses the tags for answers like "don't know" or "refused".
Reading a .dta the naive way collapses all of them into NaN, so a frequency
table could only ever report one undifferentiated missing category, and the
difference between "never asked" and "asked and refused" was lost on import.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services.ingest import MISSING_TAG_SUFFIX, ingest_file
from app.services.query_engine import (
    DatasetContext,
    VariableInfo,
    execute_frequency,
)


@pytest.fixture(scope="module")
def tagged_stata(tmp_path_factory) -> Path:
    """A .dta carrying real tagged missings, written by pyreadstat."""
    pyreadstat = pytest.importorskip("pyreadstat")
    path = tmp_path_factory.mktemp("tagged") / "tagged.dta"
    frame = pd.DataFrame(
        {
            # 4 real ages, 2 blanks, 2 ".a" (don't know), 1 ".b" (refused)
            "age": [25.0, 40.0, 33.0, 51.0, np.nan, np.nan, "a", "a", "b"],
            "sex": [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0],
        }
    )
    pyreadstat.write_dta(
        frame,
        str(path),
        variable_value_labels={"sex": {1: "Male", 2: "Female"}},
        missing_user_values={"age": ["a", "b"]},
    )
    return path


def test_ingest_separates_tags_from_the_numeric_column(tagged_stata, tmp_path):
    result = ingest_file(tagged_stata, tmp_path / "out")
    frame = pd.read_parquet(result.parquet_path)

    # The numeric column stays numeric, so means and sums still work
    assert pd.api.types.is_numeric_dtype(frame["age"])
    assert frame["age"].sum() == 149.0  # 25 + 40 + 33 + 51
    assert frame["age"].isna().sum() == 5  # 2 blanks + 3 tagged

    # The tags live in a companion column rather than being thrown away
    companion = f"age{MISSING_TAG_SUFFIX}"
    assert companion in frame.columns
    assert sorted(frame[companion].dropna().unique()) == [".a", ".b"]


def test_variable_metadata_records_the_tags_and_hides_the_companion(
    tagged_stata, tmp_path
):
    result = ingest_file(tagged_stata, tmp_path / "out")
    by_name = {v.name: v for v in result.variables}

    assert by_name["age"].missing_tags == [".a", ".b"]
    assert by_name["age"].is_hidden is False
    # The companion column is an implementation detail, not something to offer
    # in a variable picker next to the variable it belongs to
    assert by_name[f"age{MISSING_TAG_SUFFIX}"].is_hidden is True


def test_frequency_reports_blanks_and_each_tag_separately(tagged_stata, tmp_path):
    result = ingest_file(tagged_stata, tmp_path / "out")
    ctx = DatasetContext(
        dataset_id="d",
        parquet_path=str(result.parquet_path),
        variables={
            v.name: VariableInfo(
                name=v.name,
                var_type=v.var_type,
                value_labels=v.value_labels,
                missing_tags=v.missing_tags,
            )
            for v in result.variables
        },
    )
    frequency = execute_frequency(ctx, "age")
    counts = {row.label: row.count for row in frequency.rows}

    # This is the whole point: three distinct kinds of missing, not one lump
    assert counts["(blank)"] == 2
    assert counts[".a"] == 2
    assert counts[".b"] == 1

    # Real answers are still reported, and still counted as valid
    assert counts["25"] == 1  # a whole number, not "25.0"
    assert frequency.total == 9
    assert frequency.missing == 5
    assert frequency.distinct == 4

    # Valid percentages are over the real answers only
    real = [row for row in frequency.rows if row.label == "25"][0]
    assert real.valid_percent == pytest.approx(25.0)

    # Blanks and tags carry no valid percentage
    for label in ("(blank)", ".a", ".b"):
        row = [r for r in frequency.rows if r.label == label][0]
        assert row.valid_percent == 0.0


def test_untagged_variables_are_unaffected(tagged_stata, tmp_path):
    """A variable with no tagged missings must behave exactly as before."""
    result = ingest_file(tagged_stata, tmp_path / "out")
    ctx = DatasetContext(
        dataset_id="d",
        parquet_path=str(result.parquet_path),
        variables={
            v.name: VariableInfo(
                name=v.name,
                var_type=v.var_type,
                value_labels=v.value_labels,
                missing_tags=v.missing_tags,
            )
            for v in result.variables
        },
    )
    frequency = execute_frequency(ctx, "sex")
    labels = {row.label for row in frequency.rows}
    assert labels == {"Male", "Female"}
    assert frequency.missing == 0


def test_value_labels_still_resolve_on_a_tagged_variable(tmp_path):
    """The tag path casts values to text, which must not break label lookup.

    Value label keys are written "1" and "2". Casting a numeric column to text
    naively yields "1.0", which matches no label, so a coded variable with
    tagged missings would silently lose every label it had.
    """
    pyreadstat = pytest.importorskip("pyreadstat")
    path = tmp_path / "coded.dta"
    frame = pd.DataFrame(
        {"sex": [1.0, 2.0, 1.0, np.nan, "a", 2.0]},
    )
    pyreadstat.write_dta(
        frame,
        str(path),
        variable_value_labels={"sex": {1: "Male", 2: "Female"}},
        missing_user_values={"sex": ["a"]},
    )
    result = ingest_file(path, tmp_path / "out")
    ctx = DatasetContext(
        dataset_id="d",
        parquet_path=str(result.parquet_path),
        variables={
            v.name: VariableInfo(
                name=v.name,
                var_type=v.var_type,
                value_labels=v.value_labels,
                missing_tags=v.missing_tags,
            )
            for v in result.variables
        },
    )
    counts = {row.label: row.count for row in execute_frequency(ctx, "sex").rows}
    assert counts["Male"] == 2
    assert counts["Female"] == 2
    assert counts["(blank)"] == 1
    assert counts[".a"] == 1
