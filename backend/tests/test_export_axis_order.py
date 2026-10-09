"""The order an exported chart puts its axis in, run as the browser runs it.

A standalone export re-filters itself offline, so it has to re-sort what is
left, and that sorting is JavaScript inside the template rather than Python.
It cannot be reached from the test suite, so the test lifts the functions out
of the template and runs them under node.

The fault that prompted it: anything that was not a date got sorted biggest
first, so a bar chart of age in ten year bands came out 10, 80, 30, 60, 40 -
the shape of the distribution gone, and nothing on the chart saying so. The
same page drawn in the platform was in age order, because the server sends the
rows ordered and only the export re-sorts them.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "app/services/export_assets/dashboard.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed here")


def _lifted(name: str) -> str:
    """One top level function out of the template, by source.

    By source rather than by a copy kept here, so the test cannot pass against
    an ordering the shipped file no longer has.
    """
    source = TEMPLATE.read_text(encoding="utf-8")
    found = re.search(rf"\n  function {name}\(.*?\n  \}}\n", source, re.S)
    assert found, f"{name} is no longer a plain function in the export template"
    return found.group(0)


def order(rows: list[list], cube: dict) -> list[list]:
    """`rows` as the exported page's own sorted() leaves them."""
    cube = {"sort": [], "columns": [], **cube}
    program = "".join(_lifted(name) for name in ("text", "typeOf", "sorted"))
    program += (
        f"process.stdout.write(JSON.stringify(sorted({json.dumps(rows)}, {json.dumps(cube)})))"
    )
    run = subprocess.run(
        [str(NODE), "-e", program], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def cube(data_type: str) -> dict:
    """One grouping, one count, and nothing the chart was saved sorted by."""
    return {
        "dimensions": ["band"],
        "measures": [{"name": "count", "label": "Responses", "how": "sum"}],
        "columns": [
            {"name": "band", "label": "Age", "type": "dimension", "data_type": data_type},
            {"name": "count", "label": "Responses", "type": "measure", "data_type": "number"},
        ],
    }


# Deliberately not in any order: ascending by band and descending by count are
# different answers here, and so is leaving the rows alone.
BANDS = [[30.0, 60], [0.0, 116], [80.0, 12], [10.0, 141], [20.0, 95]]


def test_a_number_axis_reads_low_to_high():
    """The histogram. Ten year bands belong in age order whatever their heights."""
    assert [row[0] for row in order(BANDS, cube("numeric"))] == [0.0, 10.0, 20.0, 30.0, 80.0]


def test_a_date_axis_reads_left_to_right_in_time():
    days = [["2026-03-02", 4], ["2026-01-05", 9], ["2026-02-01", 2]]
    assert [row[0] for row in order(days, cube("datetime"))] == [
        "2026-01-05",
        "2026-02-01",
        "2026-03-02",
    ]


def test_a_category_axis_still_reads_biggest_first():
    """The ordering the platform draws a grouping in when nothing sorted it.

    Provinces are stored as codes with value labels, which arrive as
    `categorical`: a number on the axis, and still not a quantity.
    """
    provinces = [["Malampa", 40], ["Sanma", 90], ["Shefa", 65]]
    assert [row[1] for row in order(provinces, cube("categorical"))] == [90, 65, 40]


def test_a_type_the_export_does_not_know_reads_biggest_first():
    """Unknown falls to the old behaviour rather than to the row order."""
    assert [row[1] for row in order(BANDS, cube(""))] == [141, 116, 95, 60, 12]


def test_the_sort_a_chart_was_saved_with_wins():
    """The axis rule is only for a chart that was saved with no sort of its own."""
    saved = {**cube("numeric"), "sort": [{"field": "count", "direction": "desc"}]}
    assert [row[0] for row in order(BANDS, saved)] == [10.0, 0.0, 20.0, 30.0, 80.0]
