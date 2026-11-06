"""A widget's text size, carried into the downloaded or published file.

The platform had a text size for a widget and the file ignored it: every
chart in the file was drawn at 12px, and an indicator's number at 30, however
big the board had been made to be read across a room.
"""

from __future__ import annotations

import json

import pytest

from app.services.static_export import _carried_style
from tests.test_export_filters import NODE, lifted
from tests.test_export_side_labels import NAMES, furniture, run


def test_the_size_travels_with_the_widgets_look():
    style = _carried_style({"chart_font_size": 20, "background": "#0b2545", "query": {}})
    assert style == {"chart_font_size": 20, "background": "#0b2545"}


@pytest.mark.parametrize(
    ("stored", "carried"),
    [(None, None), (0, None), ("big", None), (float("nan"), None), (300, 48), (3, 8), (17.6, 18)],
)
def test_a_size_from_the_json_column_is_one_a_page_can_be_drawn_at(stored, carried):
    """It is written into the page's styles, and arrives through a column an
    editor can PATCH."""
    assert _carried_style({"chart_font_size": stored}).get("chart_font_size") == carried


@pytest.mark.skipif(NODE is None, reason="node is not installed here")
def test_a_chart_is_drawn_at_its_widgets_size_and_no_other():
    result = {
        "columns": [
            {"name": "activity", "label": "Main activity", "type": "dimension"},
            {"name": "people", "label": "People", "type": "measure"},
        ],
        "rows": [[name, 10] for name in NAMES],
    }
    program = (
        furniture()
        + lifted("atSize", "num", "text", "categoryAxis", "twoLines", "sideLabel", "valueAxis",
                 "shape", "chartOption")
        + f"var result = {json.dumps(result)};\n"
        "var big = atSize(20, function () { return chartOption('bar', result, {}, 600) });\n"
        "var after = chartOption('bar', result, {}, 600);\n"
        "process.stdout.write(JSON.stringify({\n"
        "  big: [big.xAxis.axisLabel.fontSize, big.yAxis.axisLabel.fontSize],\n"
        "  after: [after.xAxis.axisLabel.fontSize, after.yAxis.axisLabel.fontSize],\n"
        "  face: FACE.fontSize}))"
    )
    found = run(program)
    assert found["big"] == [20, 20]
    assert found["after"] == [12, 12], "the next chart on the page kept the size"
    assert found["face"] == 12
