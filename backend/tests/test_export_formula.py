"""A formula indicator read offline, and read the same way.

An exported board re-computes itself in the browser, so an indicator defined
as arithmetic over named parts needs that arithmetic twice: once in Python,
where the platform answers, and once in the file's JavaScript, where the
reader at a ministry with no network answers. Two readings of one rule drift -
over what a division by nothing means, over what a group a part matched
nothing in is worth - and nothing on either page would say so.

So the cases live here once and are run both ways: `services/formula` under
pytest, and the lifted template functions under node.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import formula

TEMPLATE = Path(__file__).resolve().parents[1] / "app/services/export_assets/dashboard.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed here")

#: (expression, parts) - the shapes a survey office actually writes, plus the
#: two that are easy to disagree about: no value, and nothing to divide by.
CASES: list[tuple[str, dict[str, float | None]]] = [
    ("done / issued * 100", {"done": 30, "issued": 40}),
    ("done / issued * 100", {"done": 0, "issued": 0}),
    ("refused / (done + refused) * 100", {"refused": 2, "done": 8}),
    ("visits / interviews", {"visits": 17, "interviews": 10}),
    ("a + b * c", {"a": 1, "b": 2, "c": 3}),
    ("(a + b) * c", {"a": 1, "b": 2, "c": 3}),
    ("a - b - c", {"a": 10, "b": 3, "c": 2}),
    ("a / b / c", {"a": 100, "b": 5, "c": 2}),
    ("-a + 10", {"a": 4}),
    ("-(a - b)", {"a": 1, "b": 4}),
    ("a * 0.5 + .5", {"a": 3}),
    ("a + b", {"a": 1, "b": None}),
    ("a / b", {"a": 1, "b": None}),
    ("100 - done / issued * 100", {"done": 1, "issued": 4}),
    ("gap", {"gap": -5}),
    ("done / issued", {"done": 3, "issued": 0}),
]


def _lifted(name: str) -> str:
    source = TEMPLATE.read_text(encoding="utf-8")
    found = re.search(rf"\n  function {name}\(.*?\n  \}}\n", source, re.S)
    assert found, f"{name} is no longer a plain function in the export template"
    return found.group(0)


def read_offline() -> list[float | None]:
    """Every case as the exported file would work it out."""
    program = _lifted("readFormula") + _lifted("runFormula")
    # An infinity and a nan both come back from JSON.stringify as null, which
    # is exactly what "no value" looks like - so a file that had quietly
    # dropped the guard against dividing by nothing would read as agreeing
    # with the platform. They are named here instead.
    program += f"""
      var cases = {json.dumps(CASES)}
      process.stdout.write(JSON.stringify(cases.map(function (one) {{
        try {{
          var got = runFormula(readFormula(one[0]), one[1])
          if (got === null) return null
          return isFinite(got) ? got : 'not a number: ' + got
        }} catch (e) {{ return 'error: ' + e.message }}
      }})))
    """
    run = subprocess.run(
        [str(NODE), "-e", program], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_the_file_works_every_formula_out_the_way_the_platform_does():
    here = [formula.compute(expression, parts) for expression, parts in CASES]
    there = read_offline()

    assert len(there) == len(CASES)
    for (expression, parts), mine, theirs in zip(CASES, here, there, strict=True):
        where = f"{expression} with {parts}: the platform says {mine}, the file says {theirs}"
        if mine is None:
            assert theirs is None, where
        else:
            assert theirs == pytest.approx(mine), where


def test_a_rate_with_nothing_issued_is_blank_on_both_sides():
    """Not nought, and not an infinity drawn as a full bar."""
    assert formula.compute("done / issued", {"done": 3, "issued": 0}) is None
    offline = read_offline()
    # Nought over nought, and three over nothing: neither is a number.
    assert offline[1] is None
    assert offline[-1] is None


def test_the_file_refuses_what_the_platform_refuses():
    """Neither evaluates the text; both parse it, so neither runs anything."""
    program = _lifted("readFormula")
    program += (
        "var bad = ['__import__(1)', 'a b', ')', 'a +', 'a @ b', 'a.b'];"
        "process.stdout.write(JSON.stringify(bad.map(function (one) {"
        "  try { readFormula(one); return 'read' } catch (e) { return 'refused' }"
        "})))"
    )
    run = subprocess.run(
        [str(NODE), "-e", program], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == ["refused"] * 6

    for one in ("__import__(1)", "a b", ")", "a +", "a @ b", "a.b"):
        with pytest.raises(formula.FormulaError):
            formula.parse(one)


# --- The same formula in the Word report -------------------------------------
#
# A board goes out three ways: as the page, as a standalone file, and as a
# document. The document is Python, so it does not need the parser lifted out
# of the template - but it does need to use the formula at all. Reading the
# indicator's leftover single measure instead would print the raw count of one
# part under the name of a rate, in a file nobody can correct afterwards.


def _cube(rows: list[list[object]], label: str = "value") -> dict:
    return {
        "columns": [
            {"name": "province", "label": "Province"},
            {"name": "value", "label": label},
        ],
        "dimensions": ["province"],
        "measures": [{"name": "value", "label": label, "how": "sum", "parts": ["value"]}],
        "rows": rows,
        "sort": [],
    }


def _formula_widget() -> dict:
    """A formula tile as the export payload carries one.

    Women interviewed as a share of interviews: 140 of 300 overall, and the
    three provinces differing from that and from each other.
    """
    return {
        "kind": "indicator",
        "type": "indicator",
        "title": "Women interviewed",
        "indicator": {
            "name": "Women interviewed",
            "unit": "",
            "value_format": "percent",
            "target_value": 50,
            "breakdown_variable": "province",
            "breakdown_targets": {},
            "percent_of": "",
        },
        # Left in place and not read: a file made before the formula was
        # written still opens, and this must not be what the document prints.
        "cube": _cube([["Northern", 103], ["Highland", 100], ["Southern", 97]]),
        "formula": {
            "expression": "women / interviews * 100",
            "parts": [
                {"name": "women", "counted": True},
                {"name": "interviews", "counted": True},
            ],
        },
        "parts": {
            "women": _cube([["Northern", 50], ["Highland", 51], ["Southern", 39]]),
            "interviews": _cube([["Northern", 103], ["Highland", 100], ["Southern", 97]]),
        },
    }


def test_the_document_prints_the_formula_and_not_the_leftover_count():
    from app.services import export_tables

    _, rows = export_tables.widget_table(_formula_widget())

    assert rows[0][0] == "Northern"
    assert rows[0][1] == pytest.approx(48.5436, abs=0.001)
    assert rows[1][1] == pytest.approx(51.0)
    assert rows[2][1] == pytest.approx(40.2061, abs=0.001)


def test_the_documents_total_line_is_the_sum_asked_of_the_whole():
    """140 women over 300 interviews, not the average of three percentages."""
    from app.services import export_tables

    _, rows = export_tables.widget_table(_formula_widget())

    total = next(row for row in rows if row[0] == "Total")
    assert total[1] == pytest.approx(140 / 300 * 100)
    # And the indicator's own target stays under it, as on any other tile.
    assert rows[-1] == ["Target", 50]


def test_a_group_with_nothing_to_divide_by_is_left_out_of_the_document():
    from app.services import export_tables

    widget = _formula_widget()
    widget["parts"]["interviews"] = _cube([["Northern", 103], ["Highland", 100], ["Southern", 0]])

    _, rows = export_tables.widget_table(widget)

    assert [row[0] for row in rows] == ["Northern", "Highland", "Total", "Target"]
