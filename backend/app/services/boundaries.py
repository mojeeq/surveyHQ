"""Which area a coordinate falls in, and whether that is the area recorded.

This is the question the whole boundary feature exists to answer. A household
listing records the enumeration area its interviewer says they were in; the
device records where they actually were. Those two disagreeing is the single
most useful thing a monitoring map can show, because it is either an EA code
typed wrong, an interviewer working the wrong area, or a boundary the field
staff read differently from the office - and all three cost a census dearly if
they are found after fieldwork rather than during it.

Answering it needs point-in-polygon and nothing else: no projection, no
topology, no spatial database. Ray casting over WGS84 degrees is exact for
this, because "inside this ring" does not care what the coordinates mean.
"""

from __future__ import annotations

from typing import Any

# The grid the areas are bucketed into before any point is tested. A national
# frame is thousands of enumeration areas and a map is tens of thousands of
# places; testing every point against every area is the product of those two
# and takes minutes. Bucketing makes each point a lookup and a handful of
# tests. Sized from the count so a small layer is not carrying a large grid.
MIN_CELLS = 16
MAX_CELLS = 256


def _ring_bbox(ring: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _polygons(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    """Every polygon in a geometry, each as a list of rings, outer ring first."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [coordinates]
    if kind == "MultiPolygon":
        return list(coordinates)
    return []


def _in_ring(ring: list[list[float]], x: float, y: float) -> bool:
    """Ray casting: count the ring's crossings of the ray running east from the point.

    An odd count means inside. Points exactly on an edge fall whichever way the
    arithmetic lands, which is correct enough for a boundary check: a household
    on the line between two areas is a finding either way.
    """
    inside = False
    count = len(ring)
    if count < 3:
        return False
    j = count - 1
    for i in range(count):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        # Only edges the ray's latitude actually passes between can cross it.
        if (yi > y) != (yj > y):
            crossing = xi + (y - yi) * (xj - xi) / (yj - yi)
            if crossing > x:
                inside = not inside
        j = i
    return inside


class Areas:
    """A boundary layer prepared for asking which area a point is in."""

    def __init__(self, features: list[dict[str, Any]]):
        self.features = features
        self.boxes: list[tuple[float, float, float, float]] = []
        self.shapes: list[list[list[list[list[float]]]]] = []

        for feature in features:
            polygons = _polygons(feature.get("geometry") or {})
            self.shapes.append(polygons)
            if not polygons:
                self.boxes.append((1.0, 1.0, -1.0, -1.0))  # empty: matches nothing
                continue
            boxes = [_ring_bbox(polygon[0]) for polygon in polygons if polygon]
            self.boxes.append(
                (
                    min(box[0] for box in boxes),
                    min(box[1] for box in boxes),
                    max(box[2] for box in boxes),
                    max(box[3] for box in boxes),
                )
                if boxes
                else (1.0, 1.0, -1.0, -1.0)
            )

        live = [box for box in self.boxes if box[0] <= box[2]]
        if live:
            self.min_x = min(box[0] for box in live)
            self.min_y = min(box[1] for box in live)
            self.max_x = max(box[2] for box in live)
            self.max_y = max(box[3] for box in live)
        else:
            self.min_x = self.min_y = 0.0
            self.max_x = self.max_y = 0.0

        side = max(MIN_CELLS, min(MAX_CELLS, int(len(live) ** 0.5) * 4 or MIN_CELLS))
        self.side = side
        self.width = (self.max_x - self.min_x) / side or 1.0
        self.height = (self.max_y - self.min_y) / side or 1.0
        self.grid: dict[tuple[int, int], list[int]] = {}
        for index, box in enumerate(self.boxes):
            if box[0] > box[2]:
                continue
            for column in range(self._column(box[0]), self._column(box[2]) + 1):
                for row in range(self._row(box[1]), self._row(box[3]) + 1):
                    self.grid.setdefault((column, row), []).append(index)

    def _column(self, x: float) -> int:
        return max(0, min(self.side - 1, int((x - self.min_x) / self.width)))

    def _row(self, y: float) -> int:
        return max(0, min(self.side - 1, int((y - self.min_y) / self.height)))

    def locate(self, longitude: float, latitude: float) -> int | None:
        """The index of the area holding this point, or None if it is outside them all."""
        if not (self.min_x <= longitude <= self.max_x and self.min_y <= latitude <= self.max_y):
            return None
        for index in self.grid.get((self._column(longitude), self._row(latitude)), ()):
            box = self.boxes[index]
            if not (box[0] <= longitude <= box[2] and box[1] <= latitude <= box[3]):
                continue
            for polygon in self.shapes[index]:
                if not polygon or not _in_ring(polygon[0], longitude, latitude):
                    continue
                # A ring after the first is a hole: a point in it is in the
                # rectangle and in the outer ring, and still outside the area.
                if any(_in_ring(hole, longitude, latitude) for hole in polygon[1:]):
                    continue
                return index
        return None

    def value(self, index: int | None, prop: str) -> Any:
        """One property of the located area, for comparing against what was recorded."""
        if index is None:
            return None
        return (self.features[index].get("properties") or {}).get(prop)


def same_code(recorded: Any, expected: Any) -> bool:
    """Whether a recorded area code means the same as the boundary's own.

    Codes cross the gap between a questionnaire and a GIS file as text on one
    side and a number on the other, and with leading zeros on whichever side
    was written by someone who knew they mattered. "07", 7 and "007" are one
    enumeration area, and treating them as three would report every record in
    the country as a mismatch.
    """
    left, right = normalise_code(recorded), normalise_code(expected)
    return left is not None and left == right


def normalise_code(value: Any) -> str | None:
    """A code reduced to what identifies it, or None when nothing was recorded."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if not text:
        return None
    # Leading zeros are formatting, not identity - but only on something that
    # is entirely digits, so a code like "0A1" is left alone.
    stripped = text.lstrip("0")
    return (stripped or "0") if text.isdigit() else text.casefold()
