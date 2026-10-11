"""A map of a census cannot send one pin per household.

Points have always been grouped by coordinate - several interviews at one
address are one pin carrying a number - which does almost nothing for a census,
where every household has its own GPS reading. A hundred thousand interviews
measured at four megabytes of JSON for the map widget alone, against ten
kilobytes for every other widget on the board together, and it travels again on
every filter change, every view switch and every page load. Nothing caches it.

So past a few thousand places the coordinates are rounded until the pins fit.
What a pin says has to survive that: the number on it is still computed over
the interviews behind it, and nothing is dropped.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.schemas.query import Condition, FilterGroup, FilterOperator
from app.services import geo
from app.services.query_engine import DatasetContext, VariableInfo


@pytest.fixture
def spread(tmp_path) -> DatasetContext:
    """Twelve thousand households, each at its own reading, over about 60 km."""
    rng = np.random.default_rng(11)
    rows = 12_000
    frame = pd.DataFrame(
        {
            # Six decimals, as a device records them: no two the same.
            "lat": (-17.7 + rng.normal(0, 0.15, rows)).round(6),
            "lon": (168.3 + rng.normal(0, 0.15, rows)).round(6),
            "people": rng.integers(1, 9, rows).astype(float),
            "province": rng.choice(["Shefa", "Tafea"], rows),
        }
    )
    path = tmp_path / "households.parquet"
    frame.to_parquet(path, index=False)
    return _ctx(path, frame)


def _ctx(path: Path, frame: pd.DataFrame) -> DatasetContext:
    """A context over a parquet file, without the database a dataset needs."""
    kinds = {
        name: "numeric" if pd.api.types.is_numeric_dtype(frame[name]) else "categorical"
        for name in frame.columns
    }
    return DatasetContext(
        dataset_id="map-test",
        parquet_path=str(path),
        variables={
            name: VariableInfo(name, name.title(), kind) for name, kind in kinds.items()
        },
    )


def _points(ctx: DatasetContext, **extra) -> dict:
    return geo.points(ctx, latitude="lat", longitude="lon", **extra)


def test_a_census_comes_back_as_a_map_rather_than_a_megabyte(spread):
    found = _points(spread)

    assert len(found["points"]) <= geo.TARGET_PLACES
    grouped = found["grouped"]
    assert grouped is not None
    assert grouped["records"] == 12_000, "what the pins stand for, so the map can say"
    assert grouped["decimals"] in geo.PLACE_DECIMALS
    assert grouped["metres"] == geo.PLACE_METRES[grouped["decimals"]]
    # Nothing was dropped on the way: every interview is behind some pin.
    assert sum(point["rows"] for point in found["points"]) == 12_000
    assert found["truncated"] is False


def test_the_number_on_a_pin_is_still_counted_from_the_interviews(spread):
    """Not an average of averages: the rounding is in the grouping key."""
    counted = _points(spread, measure_agg="count")
    assert sum(point["value"] for point in counted["points"]) == 12_000

    totals = _points(spread, measure_agg="sum", measure_variable="people")
    frame = pd.read_parquet(spread.parquet_path)
    assert sum(point["value"] for point in totals["points"]) == pytest.approx(
        frame["people"].sum()
    )

    averaged = _points(spread, measure_agg="mean", measure_variable="people")
    # A mean of the whole dataset weighted back out of the pins: each pin's
    # mean is over its own records, so the weights are the records.
    weighted = sum(
        point["value"] * point["rows"] for point in averaged["points"]
    ) / sum(point["rows"] for point in averaged["points"])
    assert weighted == pytest.approx(frame["people"].mean())


def test_a_village_is_drawn_exactly_where_it_was_recorded(tmp_path):
    """The rounding is for maps that need it, and nothing else pays for it."""
    frame = pd.DataFrame(
        {
            "lat": [-17.712345, -17.712345, -17.798765],
            "lon": [168.312345, 168.312345, 168.398765],
            "people": [4.0, 2.0, 5.0],
        }
    )
    path = tmp_path / "village.parquet"
    frame.to_parquet(path, index=False)
    found = geo.points(_ctx(path, frame), latitude="lat", longitude="lon")

    assert found["grouped"] is None
    # Two readings at one house are one pin, as they always were.
    assert len(found["points"]) == 2
    assert {point["lat"] for point in found["points"]} == {-17.712345, -17.798765}
    assert sorted(point["rows"] for point in found["points"]) == [1, 2]


def test_a_filter_is_applied_before_anything_is_grouped(spread):
    shefa = _points(
        spread,
        filters=FilterGroup(
            conditions=[
                Condition(variable="province", operator=FilterOperator.eq, value="Shefa")
            ]
        ),
    )
    frame = pd.read_parquet(spread.parquet_path)
    expected = int((frame["province"] == "Shefa").sum())
    assert sum(point["rows"] for point in shefa["points"]) == expected
    assert shefa["grouped"]["records"] == expected


def test_checking_recorded_areas_is_not_rounded_past_a_garden(spread):
    """The verdict is read off the pin, so the cell cannot cross a boundary.

    A kilometre-wide cell would put a household on the wrong side of a ward
    line and turn the finding this mode exists for into an artefact of the
    grouping, so this mode rounds no further than about 110 m - and keeps the
    recorded area in the key, because two neighbours naming different areas is
    itself the finding.
    """
    checked = _points(spread, area_variable="province")
    grouped = checked["grouped"]
    assert grouped is None or grouped["decimals"] in geo.AREA_CHECK_DECIMALS
    assert sum(point["rows"] for point in checked["points"]) == 12_000
    assert all("recorded_area" in point for point in checked["points"])
