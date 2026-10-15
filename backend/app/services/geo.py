"""Interview locations for the map widget.

A monitoring map answers two questions: where has the fieldwork been, and what
happened at this spot. So points are grouped by coordinate rather than drawn one
per row - several interviews at one household, or a roster's many people at one
address, are one pin carrying a number rather than a pile of pins hiding each
other.

A census makes that grouping do very little, because every household has its
own GPS reading: a hundred thousand interviews are a hundred thousand places,
which measured four megabytes of JSON to the browser on every filter change
and fifty thousand markers to draw at the other end. So when there are more
places than a map can be read at, the coordinates are rounded until the pins
fit and each pin says how many records stand behind it. The rounding is in the
grouping key, so the number at a pin is still aggregated over the interviews
themselves.
"""

from __future__ import annotations

from typing import Any

from app.schemas.query import FilterGroup
from app.services.boundaries import Areas, normalise_code, same_code
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    SQLBuilder,
    _label_value,
    _quote_path,
    quote_ident,
    run_sql,
)

# A dashboard map is read at a glance; past a few thousand pins it is a smear,
# and the browser is doing the work of drawing them. Points are grouped by
# coordinate before this applies, so it counts distinct places rather than
# interviews - but a census enumerates every household at its own GPS reading,
# and a hundred thousand of those was measured at four megabytes of JSON
# travelling to the browser on every filter change, every view switch and
# every page load, with fifty thousand markers to build at the other end.
# Every other widget on the same board came to ten kilobytes together.
#
# So past this many places the coordinates are rounded until the pins fit, and
# each pin says how many records stand behind it - which is what a pin has
# always said, because several interviews at one household were always one pin
# carrying a number.
TARGET_PLACES = 4_000

# The ceiling that still applies after rounding, for coordinates spread so
# thin that even eleven-kilometre cells do not group them: scattered noise
# from broken devices is not something the Null Island check can catch.
MAX_POINTS = 50_000

#: How far the coordinates may be rounded, finest first. In degrees of
#: latitude 4 decimals is about 11 m, 3 about 110 m, 2 about 1.1 km and 1
#: about 11 km. Coarser than that and a pin says nothing about where anybody
#: actually went.
PLACE_DECIMALS = (4, 3, 2, 1)

#: What a rounding step comes to on the ground, for the widget to say.
PLACE_METRES = {4: 11, 3: 110, 2: 1_100, 1: 11_000}

#: Worst first. A pin standing for several places takes the worst verdict
#: among them, because a map of this kind is read for its findings: a cell
#: holding one disagreement and nine agreements is somewhere to go and look.
VERDICT_ORDER = ("mismatch", "outside", "unrecorded", "match")

AGGREGATIONS = {
    "count": None,
    "sum": "SUM",
    "mean": "AVG",
    "min": "MIN",
    "max": "MAX",
}


def _rounding(
    ctx: DatasetContext,
    lat: str,
    lon: str,
    conditions: list[str],
    params: list[Any],
    steps: tuple[int, ...],
) -> int | None:
    """How far to round the coordinates so the pins fit, or None to leave them.

    One pass over the two columns, asking what each rounding step would leave.
    Asked rather than worked out from the bounding box, because fieldwork is
    not spread evenly over the ground it covers: an island's households sit
    along its roads, and a cell size that suited the frame would leave most of
    the pins in one cell and the rest of the map empty.

    Counted approximately, which is the whole reason this is cheap: an exact
    COUNT(DISTINCT) builds a hash table of every coordinate in the survey, and
    all this decides is a cell size. Being a few dozen out either side of the
    threshold chooses the same cell.
    """
    counted = ", ".join(
        f"approx_count_distinct(ROUND({lat}, {step})::VARCHAR || ',' || "
        f"ROUND({lon}, {step})::VARCHAR) AS step{step}"
        for step in steps
    )
    sql = (
        f"SELECT approx_count_distinct({lat}::VARCHAR || ',' || {lon}::VARCHAR) AS exact, "
        f"{counted} FROM read_parquet({_quote_path(ctx.parquet_path)}) "
        f"WHERE {' AND '.join(conditions)}"
    )
    columns, rows = run_sql(sql, params)
    if not rows:
        return None
    counts = dict(zip(columns, rows[0], strict=False))
    if int(counts.get("exact") or 0) <= TARGET_PLACES:
        return None
    for step in steps:
        if int(counts.get(f"step{step}") or 0) <= TARGET_PLACES:
            return step
    # Nothing fits: the coarsest step still groups more than the coordinates
    # as recorded would, and the limit below catches whatever is left.
    return steps[-1]


def points(
    ctx: DatasetContext,
    latitude: str,
    longitude: str,
    detail: list[str] | None = None,
    measure_agg: str = "count",
    measure_variable: str = "",
    filters: FilterGroup | None = None,
    limit: int = MAX_POINTS,
    area_variable: str = "",
    areas: Areas | None = None,
    boundary_key: str = "",
) -> dict[str, Any]:
    """Grouped coordinates, each with a value and the details to show on click.

    Pass `areas` and `boundary_key` to check what each record says about where
    it was against where its coordinates put it. The checking happens here,
    between reading the points and grouping them, because the order is the
    whole correctness of it - see the comment on the rounding below.
    """
    for name in (latitude, longitude):
        if name not in ctx.variables:
            raise QueryError(f"'{name}' is not a variable in this dataset")
    if measure_agg not in AGGREGATIONS:
        raise QueryError(f"'{measure_agg}' is not an aggregation this map can show")
    if area_variable and area_variable not in ctx.variables:
        raise QueryError(f"'{area_variable}' is not a variable in this dataset")

    lat = quote_ident(ctx.require(latitude).name)
    lon = quote_ident(ctx.require(longitude).name)

    function = AGGREGATIONS[measure_agg]
    if function and measure_variable:
        if measure_variable not in ctx.variables:
            raise QueryError(f"'{measure_variable}' is not a variable in this dataset")
        info = ctx.require(measure_variable)
        column = quote_ident(info.name)
        # The cast is for a column of numbers written as text, where it is the
        # only way to get a sum at all. A stored number was never that case,
        # and sending one through a double rounds it: a sum of two BIGINTs
        # either side of 2**53 comes back two short, and a DECIMAL(18,3) grows
        # a floating tail. A map compiles its own SQL, so the same question
        # SQLBuilder asks has to be asked again here.
        value = f"{function}({column if info.holds_numbers else f'try_cast({column} AS DOUBLE)'})"
    else:
        # No variable to aggregate is not an error: how many interviews are at
        # this spot is the question a map is usually asked first.
        measure_agg, measure_variable = "count", ""
        value = "COUNT(*)"

    # One row of each group carries the details, which is what a popup shows.
    # ANY_VALUE rather than MIN so a text column is not silently alphabetised
    # into a value from a different row than the rest.
    details = [name for name in (detail or []) if name in ctx.variables]
    selected = "".join(
        f", ANY_VALUE({quote_ident(name)}) AS {quote_ident(name)}" for name in details
    )

    # The area a record says it was in is part of what makes a place distinct
    # when the map is checking that claim. Two households at one coordinate
    # naming different enumeration areas is itself the finding, and grouping
    # them into one pin would average the disagreement away.
    grouping = ["1", "2"]
    area_select = ""
    if area_variable:
        area_select = f", {quote_ident(area_variable)} AS recorded_area"
        grouping.append("3")

    builder = SQLBuilder(ctx)
    where = builder.filter_sql(filters) if filters else ""
    params = list(builder.params)
    conditions = [
        f"{lat} IS NOT NULL",
        f"{lon} IS NOT NULL",
        f"{lat} BETWEEN -90 AND 90",
        f"{lon} BETWEEN -180 AND 180",
        # Null Island is what a device with no fix records, not a place anybody
        # interviewed anyone.
        f"NOT ({lat} = 0 AND {lon} = 0)",
    ]
    if where:
        conditions.append(f"({where})")

    decimals = _rounding(ctx, lat, lon, conditions, params, PLACE_DECIMALS)
    # Rounded in the grouping key, so every value is still aggregated over the
    # records themselves: the mean at a pin is the mean of the interviews
    # behind it, not an average of averages.
    #
    # Except while checking recorded areas, where the coordinates are read as
    # recorded and the pins are grouped afterwards, by into_cells below. The
    # verdict is a comparison between a point and a boundary, so rounding it
    # first could put a household on the wrong side of a line and invent or
    # hide the finding this mode exists for.
    checking = areas is not None and bool(area_variable)
    at_lat = f"ROUND({lat}, {decimals})" if decimals is not None and not checking else lat
    at_lon = f"ROUND({lon}, {decimals})" if decimals is not None and not checking else lon

    sql = (
        f"SELECT {at_lat} AS lat, {at_lon} AS lon{area_select}, {value} AS value, "
        f"COUNT(*) AS rows{selected} "
        f"FROM read_parquet({_quote_path(ctx.parquet_path)}) "
        f"WHERE {' AND '.join(conditions)} "
        f"GROUP BY {', '.join(grouping)} ORDER BY value DESC LIMIT {int(limit) + 1}"
    )
    columns, rows = run_sql(sql, params)
    found = [dict(zip(columns, row, strict=False)) for row in rows]
    # A popup reading "province: 3" is the code, not the answer.
    if area_variable:
        info = ctx.variables.get(area_variable)
        for point in found:
            point["recorded_area_label"] = (
                _label_value(info, point["recorded_area"])
                if info and info.value_labels
                else point["recorded_area"]
            )
    for name in details:
        info = ctx.variables.get(name)
        if not info or not info.value_labels:
            continue
        for point in found:
            point[name] = _label_value(info, point[name])
    truncated = len(found) > limit
    found = found[:limit]

    area_counts: dict[str, int] | None = None
    if checking:
        # Every point as recorded, against the boundaries.
        area_counts = check_areas(found, areas, boundary_key)
        if decimals is not None:
            found = into_cells(found, decimals, measure_agg, details)

    return {
        "points": found,
        "detail": details,
        "measure": {"agg": measure_agg, "variable": measure_variable},
        "truncated": truncated,
        # The verdicts over every point the map read, counted before the pins
        # were grouped, so the legend is the finding rather than a count of
        # pins that happen to carry one.
        "area_counts": area_counts,
        # Set only when the coordinates were rounded, so a map drawn exactly
        # where things were recorded says nothing and a grouped one can say
        # what a pin stands for. The records are counted from the pins rather
        # than asked for separately: every row behind the map is behind one of
        # them.
        "grouped": (
            {
                "decimals": decimals,
                "metres": PLACE_METRES.get(decimals),
                "records": sum(int(point["rows"] or 0) for point in found),
            }
            if decimals is not None
            else None
        ),
    }


def _worst(verdicts: dict[str, int]) -> str:
    """The verdict a pin takes from the places it stands for."""
    for verdict in VERDICT_ORDER:
        if verdicts.get(verdict):
            return verdict
    return "match"


def into_cells(
    found: list[dict[str, Any]],
    decimals: int,
    measure_agg: str,
    details: list[str],
) -> list[dict[str, Any]]:
    """Group checked points into cells of ground, for drawing.

    Only ever after the areas have been checked. The verdict is a comparison
    between one coordinate and a boundary, and a cell a kilometre across could
    put a household on the wrong side of a ward line: grouped first, the
    finding this mode exists for becomes an artefact of the drawing. Grouped
    afterwards, every verdict is the one its own coordinates earned and what a
    cell loses is only where inside it the household stood.

    The arithmetic is exact rather than an average of averages. A count or a
    sum adds up; a mean is weighted by the records behind each point, which is
    the same number the mean was taken over; a minimum and a maximum are the
    extremes of the extremes.
    """
    cells: dict[tuple[float, float], dict[str, Any]] = {}
    for point in found:
        key = (round(float(point["lat"]), decimals), round(float(point["lon"]), decimals))
        rows = int(point.get("rows") or 0)
        value = float(point.get("value") or 0)
        cell = cells.get(key)
        if cell is None:
            cell = {
                "lat": key[0],
                "lon": key[1],
                "rows": 0,
                "value": 0.0,
                # Carried from the first point in the cell, as ANY_VALUE
                # carries them in the query: a popup shows an example of what
                # is here, not a summary of it.
                **{name: point.get(name) for name in details},
                "_verdicts": {},
                "_areas": set(),
                "_weighted": 0.0,
                "_values": [],
            }
            cells[key] = cell
        cell["rows"] += rows
        cell["_weighted"] += value * rows
        cell["_values"].append(value)
        cell["_verdicts"][point["area_status"]] = (
            cell["_verdicts"].get(point["area_status"], 0) + 1
        )
        cell["_areas"].add(
            (point.get("recorded_area"), point.get("recorded_area_label"))
        )

    grouped: list[dict[str, Any]] = []
    for cell in cells.values():
        verdicts = cell.pop("_verdicts")
        recorded = cell.pop("_areas")
        weighted = cell.pop("_weighted")
        values = cell.pop("_values")
        if measure_agg == "mean":
            cell["value"] = weighted / cell["rows"] if cell["rows"] else 0.0
        elif measure_agg == "min":
            cell["value"] = min(values)
        elif measure_agg == "max":
            cell["value"] = max(values)
        else:
            cell["value"] = sum(values)
        cell["area_status"] = _worst(verdicts)
        # What the popup needs to say why the pin is the colour it is: one
        # place's verdict, or a cell where several places disagree with each
        # other as well as with the frame.
        cell["places"] = sum(verdicts.values())
        cell["area_verdicts"] = verdicts
        if len(recorded) == 1:
            code, label = next(iter(recorded))
            cell["recorded_area"], cell["recorded_area_label"] = code, label
        else:
            cell["recorded_area"] = None
            cell["recorded_area_label"] = f"{len(recorded)} different areas"
        grouped.append(cell)
    grouped.sort(key=lambda cell: cell["value"], reverse=True)
    return grouped


def check_areas(
    found: list[dict[str, Any]],
    areas: Areas,
    boundary_key: str,
) -> dict[str, int]:
    """Say, for each point, whether it fell in the area its record claims.

    Three answers, not two. "Agrees" and "disagrees" are the interesting ones,
    but a point outside every boundary in the layer is a third thing entirely -
    usually a frame that does not cover this island yet, or a coordinate in the
    wrong hemisphere - and calling it a mismatch would bury the real ones.
    """
    counts = {"match": 0, "mismatch": 0, "outside": 0, "unrecorded": 0}
    for point in found:
        index = areas.locate(_number(point.get("lon")), _number(point.get("lat")))
        expected = areas.value(index, boundary_key)
        point["area_expected"] = expected
        if index is None:
            point["area_status"] = "outside"
        elif normalise_code(point.get("recorded_area")) is None:
            point["area_status"] = "unrecorded"
        elif same_code(point.get("recorded_area"), expected):
            point["area_status"] = "match"
        else:
            point["area_status"] = "mismatch"
        counts[point["area_status"]] += 1
    return counts


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
