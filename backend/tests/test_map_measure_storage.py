"""A pin's number goes through the same arithmetic as a table's.

The measure picker offers anything stored as a number, so a value-labelled
BIGINT or DECIMAL can now be what a map's pins count. The map compiles its own
SQL rather than going through SQLBuilder, and its compiler cast every measure
to DOUBLE on the way - the cast that exists for a column of numbers written as
text, where it is the only way to get a sum at all.

A double carries 53 bits, so the same rounding that was taken out of the table
compiler was still in this one: a sum of two BIGINTs either side of 2**53 two
short, a sum of DECIMAL(18,3) with a floating tail. On a map, where the number
on a pin is the whole point of the pin.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from app.services import geo
from app.services.query_engine import DatasetContext, VariableInfo

# Either side of 2**53, which is where a double stops counting in ones.
BIG = 9007199254740993
WIDE_SUM = BIG + 1


@pytest.fixture
def ctx(tmp_path: Path) -> DatasetContext:
    """Two households at one coordinate, so their measures are summed into
    one pin, and a third somewhere else."""
    path = tmp_path / "places.parquet"
    duckdb.connect().execute(
        f"""
        COPY (SELECT * FROM (VALUES
            (-17.73::DOUBLE, 168.31::DOUBLE, {BIG}::BIGINT, 0.1::DECIMAL(18,3), '7'),
            (-17.73::DOUBLE, 168.31::DOUBLE, 1::BIGINT,     0.2::DECIMAL(18,3), '9'),
            (-17.74::DOUBLE, 168.32::DOUBLE, 5::BIGINT,     0.3::DECIMAL(18,3), 'n/a')
        ) v(lat, lon, tenure, amount, written))
        TO '{path}' (FORMAT PARQUET)
        """
    )
    labels = {"0": "Owned", "1": "Rented"}
    return DatasetContext(
        dataset_id="map-storage",
        parquet_path=str(path),
        variables={
            "lat": VariableInfo("lat", "Latitude", "numeric", {}, [], "DOUBLE"),
            "lon": VariableInfo("lon", "Longitude", "numeric", {}, [], "DOUBLE"),
            # Labelled, so the importer reads them as code sets - correctly,
            # and not as a licence to round them.
            "tenure": VariableInfo("tenure", "Tenure", "categorical", labels, [], "BIGINT"),
            "amount": VariableInfo("amount", "Amount", "categorical", labels, [], "DECIMAL(18,3)"),
            # Numbers exported as text, which is what the cast is for.
            "written": VariableInfo("written", "Written", "text", {}, [], "VARCHAR"),
        },
    )


def _pin(ctx: DatasetContext, variable: str, agg: str = "sum"):
    """The value on the pin holding the two households at one coordinate."""
    found = geo.points(
        ctx, latitude="lat", longitude="lon", measure_agg=agg, measure_variable=variable
    )
    crowded = max(found["points"], key=lambda point: point["rows"])
    assert crowded["rows"] == 2, "the two at one coordinate are one pin"
    return crowded["value"]


def test_a_wide_integer_is_summed_as_an_integer(ctx):
    """Through a double this came back 9007199254740992: two short."""
    assert _pin(ctx, "tenure") == WIDE_SUM


def test_a_decimal_keeps_its_scale(ctx):
    """0.1 + 0.2 is 0.3, and through a double it is 0.30000000000000004."""
    assert float(_pin(ctx, "amount")) == 0.3


def test_numbers_written_as_text_are_still_cast(ctx):
    """The case the cast was put there for, which has to keep working."""
    assert _pin(ctx, "written") == 16


def test_the_other_aggregations_read_the_same_column(ctx):
    assert _pin(ctx, "tenure", agg="max") == BIG
    assert _pin(ctx, "tenure", agg="min") == 1


def test_counting_pins_needs_no_variable_at_all(ctx):
    found = geo.points(ctx, latitude="lat", longitude="lon", measure_agg="count")
    assert sum(point["rows"] for point in found["points"]) == 3
