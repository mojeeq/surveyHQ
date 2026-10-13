"""A breakdown read as a table, and the colours its figures carry.

A tile can show its groups as lines of figures rather than as a chart - sixty
bars in a tile the size of a postcard is a smear, and a reader who wants to
quote a figure wants to read it. The exported file has to be the board rather
than a tidier relative of it, which means the same groups in the same order,
and each group's share of its own quota coloured the same way.

The colouring is the part that quietly drifts: the thresholds are set against
the headline, so a region carrying a tenth of the quota has them scaled to a
tenth as well. Python does that in services/monitoring._status_against and the
exported page has to do it in JavaScript, so this runs both and compares them
rather than trusting that the two readings of one rule agree.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models import Indicator
from app.models.monitoring import Direction
from app.services.monitoring import _status_against

TEMPLATE = Path(__file__).resolve().parents[1] / "app/services/export_assets/dashboard.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed here")


def _lifted(name: str) -> str:
    """One top level function out of the template, by source."""
    source = TEMPLATE.read_text(encoding="utf-8")
    found = re.search(rf"\n  function {name}\(.*?\n  \}}\n", source, re.S)
    assert found, f"{name} is no longer a plain function in the export template"
    return found.group(0)


def exported_status(spec: dict, cases: list[tuple[float, float | None]]) -> list[str]:
    """What the exported page would colour each (value, target) pair."""
    program = "".join(_lifted(name) for name in ("indicatorStatus", "groupStatus"))
    program += (
        f"var spec = {json.dumps(spec)};"
        f"process.stdout.write(JSON.stringify({json.dumps(cases)}"
        ".map(function (pair) { return groupStatus(spec, pair[0], pair[1]) })))"
    )
    run = subprocess.run(
        [str(NODE), "-e", program], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def both(spec: dict, cases: list[tuple[float, float | None]]) -> tuple[list[str], list[str]]:
    """The same cases read by the export and by the platform."""
    indicator = Indicator(
        name="Interviews",
        target_value=spec.get("target_value"),
        warning_threshold=spec.get("warning_threshold"),
        critical_threshold=spec.get("critical_threshold"),
        direction=Direction(spec.get("direction") or "higher_is_better"),
    )
    here = [str(_status_against(indicator, value, target)) for value, target in cases]
    return exported_status(spec, cases), here


HIGHER = {
    "target_value": 1000,
    "warning_threshold": 800,
    "critical_threshold": 500,
    "direction": "higher_is_better",
}


def test_a_group_carrying_a_tenth_of_the_quota_is_judged_against_a_tenth():
    """80 of 100 is the same reading as 800 of 1000, and must colour the same."""
    there, here = both(HIGHER, [(90, 100), (80, 100), (60, 100), (40, 100)])

    assert there == here
    assert there == ["ok", "warning", "warning", "critical"]


def test_a_group_with_no_quota_of_its_own_is_not_judged():
    there, here = both(HIGHER, [(900, None)])

    assert there == here == ["unknown"]


def test_a_group_whose_quota_is_the_headline_reads_as_the_headline_does():
    there, here = both(HIGHER, [(900, 1000), (700, 1000), (100, 1000)])

    assert there == here == ["ok", "warning", "critical"]


def test_an_indicator_with_no_thresholds_colours_nothing_red():
    plain = {"target_value": 1000, "warning_threshold": None,
             "critical_threshold": None, "direction": "higher_is_better"}
    there, here = both(plain, [(1, 100), (99, 100)])

    assert there == here == ["ok", "ok"]


def test_a_limit_is_read_the_other_way_round():
    """A ceiling scaled to the group: 6 of a limit of 50 is 120 of 1000."""
    lower = {
        "target_value": 1000,
        "warning_threshold": 100,
        "critical_threshold": 200,
        "direction": "lower_is_better",
    }
    there, here = both(lower, [(2, 50), (6, 50), (12, 50)])

    assert there == here == ["ok", "warning", "critical"]


def test_no_headline_quota_leaves_the_group_on_the_headline_thresholds():
    """Nothing to scale by, so the group is read as the indicator is."""
    free = {"target_value": None, "warning_threshold": 800,
            "critical_threshold": 500, "direction": "higher_is_better"}
    there, here = both(free, [(900, 100), (700, 100)])

    assert there == here == ["ok", "warning"]
