"""How the exported page sets out a chart, run as the reader's browser runs it.

A bar chart lying on its side gave its category names whatever width they
asked for. Nine long answers to "main activity" - "Working in own farming or
raising animals or fishing or noddy bird hunting or handicrafts" among them -
took the whole card and left the bars a sliver at its right edge, with half
the names cut off by the card. The platform holds them to a third of the
chart, cut with an ellipsis or wrapped onto two lines; so does the file now.

These run the template's own functions under node, lifted from it by source.
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from tests.test_export_filters import NODE, TEMPLATE, lifted

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed here")

LONG = "Working in own farming or raising animals or fishing or noddy bird hunting or handicrafts"
NAMES = [LONG, "Studying", "Working for someone else for pay"]


def furniture() -> str:
    """The chart furniture the functions read, out of the template too. Only
    the colours are stood in for: the template takes them from the board."""
    source = TEMPLATE.read_text(encoding="utf-8")
    out = ["var PALETTE = ['#2f6fd0', '#ed6a32'];\n"]
    for name in ("INK", "FACE"):
        out.append(re.search(rf"\n  var {name} = .*?\n", source).group(0))
    out.append(re.search(r"\n  var TOOLTIP = \{.*?\n  \}\n", source, re.S).group(0))
    return "".join(out)


def run(program: str):
    done = subprocess.run([str(NODE), "-e", program], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def axes(kind: str, display: dict, width: int) -> dict:
    result = {
        "columns": [
            {"name": "activity", "label": "Main activity", "type": "dimension"},
            {"name": "people", "label": "People", "type": "measure"},
        ],
        "rows": [[name, 10 * (at + 1)] for at, name in enumerate(NAMES)],
    }
    program = (
        furniture()
        + lifted("num", "text", "categoryAxis", "twoLines", "sideLabel", "valueAxis", "shape",
                 "chartOption")
        + f"var o = chartOption({json.dumps(kind)}, {json.dumps(result)}, "
        f"{json.dumps(display)}, {width});\n"
        "var side = o.yAxis.axisLabel;\n"
        "process.stdout.write(JSON.stringify({side: side, across: o.xAxis.axisLabel,"
        f" drawn: side.formatter ? side.formatter({json.dumps(LONG)}) : null}}))"
    )
    return run(program)


@pytest.mark.parametrize("kind", ["horizontal_bar", "horizontal_stacked_bar"])
def test_names_down_the_side_get_a_third_of_the_chart(kind):
    found = axes(kind, {}, 600)
    assert found["side"]["width"] == 200
    assert found["side"]["overflow"] == "truncate"


def test_a_widget_set_to_wrap_names_gets_them_on_two_lines():
    found = axes("horizontal_bar", {"wrapLabels": True}, 600)
    assert found["side"]["width"] == 200
    lines = found["drawn"].split("\n")
    assert len(lines) == 2
    assert lines[1].endswith("…"), "a third line would run into the next name"


def test_upright_bars_keep_their_own_rule():
    """Under upright bars the bound is each bar's slot, not a third."""
    found = axes("bar", {}, 600)
    assert found["across"]["width"] != 200
    assert "width" not in found["side"]


def test_a_chart_not_yet_measured_is_left_unbounded():
    """It is drawn again from its real width once the page is laid out."""
    assert "width" not in axes("horizontal_bar", {}, 0)["side"]


@pytest.mark.parametrize(
    ("name", "per_line", "expected"),
    [
        # The platform's own cases for its twoLines, held to the same answers.
        ("None", 20, "None"),
        ("Soap and single lever type tap", 18, "Soap and single\nlever type tap"),
    ],
)
def test_a_long_name_wraps_as_the_platform_wraps_it(name, per_line, expected):
    program = lifted("twoLines") + (
        f"process.stdout.write(JSON.stringify(twoLines({json.dumps(name)}, {per_line})))"
    )
    assert run(program) == expected


def test_a_name_past_two_lines_is_cut():
    program = lifted("twoLines") + (
        "process.stdout.write(JSON.stringify(twoLines("
        "'Soap and single lever type tap + Liquid soap contained in a dispenser', 20)))"
    )
    shown = run(program)
    assert len(shown.split("\n")) == 2
    assert shown.endswith("…")
