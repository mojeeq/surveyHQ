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
from app.services.boundaries import Areas
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
            "province": rng.choice(["Northern", "Southern"], rows),
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
    northern = _points(
        spread,
        filters=FilterGroup(
            conditions=[
                Condition(variable="province", operator=FilterOperator.eq, value="Northern")
            ]
        ),
    )
    frame = pd.read_parquet(spread.parquet_path)
    expected = int((frame["province"] == "Northern").sum())
    assert sum(point["rows"] for point in northern["points"]) == expected
    assert northern["grouped"]["records"] == expected


# --- Checking recorded areas, where the order is the correctness -----------
#
# A household listing records the enumeration area the interviewer says they
# were in and the device records where they actually were; those disagreeing is
# the most useful thing this map can say. The verdict is a comparison between
# one coordinate and a boundary, so a cell a kilometre across could put a
# household on the wrong side of a ward line. Checked first and grouped
# afterwards, that cannot happen - which is the property worth testing, not
# the grouping.


def _wards() -> Areas:
    """Two adjacent wards, as the boundary tests use them."""
    return Areas(
        [
            {
                "type": "Feature",
                "properties": {"code": "001"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [167.9, -18.1],
                            [168.3, -18.1],
                            [168.3, -17.3],
                            [167.9, -17.3],
                            [167.9, -18.1],
                        ]
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"code": "002"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [168.3, -18.1],
                            [168.7, -18.1],
                            [168.7, -17.3],
                            [168.3, -17.3],
                            [168.3, -18.1],
                        ]
                    ],
                },
            },
        ]
    )


@pytest.fixture
def listed(tmp_path) -> DatasetContext:
    """Twelve thousand households, each naming the ward it believes it is in.

    The claim is right either side of the line for most of them and wrong for
    a deliberate few, so there is a real finding for the grouping to lose.
    """
    rng = np.random.default_rng(5)
    rows = 12_000
    lat = (-17.7 + rng.normal(0, 0.15, rows)).round(6)
    lon = (168.3 + rng.normal(0, 0.15, rows)).round(6)
    # Every fifth record is at the house before it - a second interview at one
    # address, or a roster's people - so the places behind the pins carry
    # different numbers of records. A mean that ignored those numbers would
    # otherwise come out right here by accident.
    for index in range(1, rows):
        if index % 5 == 0:
            lat[index], lon[index] = lat[index - 1], lon[index - 1]
    frame = pd.DataFrame(
        {
            "lat": lat,
            "lon": lon,
            # What each household says: the truth, except every hundredth.
            "ward": [
                ("002" if value > 168.3 else "001")
                if index % 100
                else ("001" if value > 168.3 else "002")
                for index, value in enumerate(lon)
            ],
            "people": rng.integers(1, 9, rows).astype(float),
        }
    )
    path = tmp_path / "listing.parquet"
    frame.to_parquet(path, index=False)
    return _ctx(path, frame)


def _checked(ctx: DatasetContext, **extra) -> dict:
    return geo.points(
        ctx,
        latitude="lat",
        longitude="lon",
        area_variable="ward",
        areas=_wards(),
        boundary_key="code",
        **extra,
    )


def test_grouping_the_pins_cannot_invent_or_hide_a_disagreement(listed):
    """The counts come out the same grouped as they do one pin per household."""
    grouped = _checked(listed)
    assert grouped["grouped"] is not None, "a census-sized listing is grouped"
    assert len(grouped["points"]) <= geo.TARGET_PLACES

    exact = geo.TARGET_PLACES
    try:
        geo.TARGET_PLACES = 10**9
        one_by_one = _checked(listed)
    finally:
        geo.TARGET_PLACES = exact

    assert one_by_one["grouped"] is None
    assert grouped["area_counts"] == one_by_one["area_counts"]
    assert grouped["area_counts"]["mismatch"] > 0, "there is a finding to keep"
    # Counted over places, as they always were, and every place is in a pin.
    assert sum(
        point["places"] for point in grouped["points"]
    ) == sum(grouped["area_counts"].values())


def test_a_pin_takes_the_worst_verdict_among_the_places_it_stands_for(listed):
    """A cell with one disagreement in it is somewhere to go and look."""
    grouped = _checked(listed)
    mixed = [
        point
        for point in grouped["points"]
        if point["area_verdicts"].get("mismatch") and len(point["area_verdicts"]) > 1
    ]
    assert mixed, "the fixture puts agreeing and disagreeing households together"
    assert all(point["area_status"] == "mismatch" for point in mixed)
    # And the popup can say why the pin is that colour rather than implying
    # every household under it disagrees.
    assert all(point["places"] > point["area_verdicts"]["mismatch"] for point in mixed)


def test_what_a_checked_pin_reports_is_still_counted_from_the_records(listed):
    grouped = _checked(listed, measure_agg="mean", measure_variable="people")
    frame = pd.read_parquet(listed.parquet_path)

    assert sum(point["rows"] for point in grouped["points"]) == 12_000
    weighted = sum(
        point["value"] * point["rows"] for point in grouped["points"]
    ) / sum(point["rows"] for point in grouped["points"])
    assert weighted == pytest.approx(frame["people"].mean())


def test_a_cell_where_the_households_disagree_with_each_other_says_so(listed):
    grouped = _checked(listed)
    several = [
        point for point in grouped["points"] if len(point["area_verdicts"]) > 1
    ]
    assert several
    # Two neighbours naming different wards is itself a finding, so the popup
    # does not pick one of them to show.
    mixed_areas = [
        point for point in grouped["points"] if point["recorded_area"] is None
    ]
    assert mixed_areas
    assert all(
        "different areas" in point["recorded_area_label"] for point in mixed_areas
    )


def test_a_listing_small_enough_to_draw_is_checked_and_left_alone(tmp_path):
    frame = pd.DataFrame(
        {
            "lat": [-17.7, -17.7, -17.8],
            "lon": [168.1, 168.5, 168.5],
            "ward": ["001", "002", "001"],
        }
    )
    path = tmp_path / "small.parquet"
    frame.to_parquet(path, index=False)
    found = _checked(_ctx(path, frame))

    assert found["grouped"] is None
    assert found["area_counts"] == {
        "match": 2,
        "mismatch": 1,
        "outside": 0,
        "unrecorded": 0,
    }
    # Exactly where each one was recorded, and no cell bookkeeping on them.
    assert sorted(point["lon"] for point in found["points"]) == [168.1, 168.5, 168.5]
    assert all("places" not in point for point in found["points"])
