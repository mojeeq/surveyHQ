"""Judging each group of a broken-down indicator against its own target.

A survey's quota is rarely one number. "6,000 interviews" is really 3,500 in
one province and 2,500 in another, or a set number of men and of women, and
the headline is what those add up to. Read against the single headline target,
a group well behind its own quota reported as on track simply because the
headline is the sum of several unequal quotas - which is the opposite of what
a monitoring platform is for.

The headline is nobody's own target, so a group that has not been given one is
not judged at all. An enumeration area of two hundred households shown at one
per cent of a national fifteen thousand is a red tile about nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.models import Indicator
from app.models.monitoring import Direction
from app.services import export_tables
from app.services.monitoring import (
    IndicatorStatus,
    breakdown_progress,
    target_for,
    targets_total,
)


def make(**kwargs) -> Indicator:
    defaults = {
        "name": "Completed interviews",
        "target_value": 1000.0,
        "warning_threshold": 800.0,
        "critical_threshold": 500.0,
        "direction": Direction.higher_is_better,
        "breakdown_variable": "region",
        "breakdown_targets": {},
    }
    return Indicator(**{**defaults, **kwargs})


def test_a_category_uses_its_own_target():
    indicator = make(breakdown_targets={"North": 400, "South": 600})
    assert target_for(indicator, "North") == 400
    assert target_for(indicator, "South") == 600


def test_a_category_without_one_has_no_target_rather_than_the_headline():
    """The headline belongs to every group together, so it is nobody's own."""
    indicator = make(breakdown_targets={"North": 400})
    assert target_for(indicator, "South") is None


def test_a_group_with_no_quota_is_not_judged():
    """Unknown, rather than critical against a number that was never its own."""
    indicator = make(breakdown_targets={"North": 400})
    report = breakdown_progress(indicator, {"South": 180.0})

    assert report["South"]["target"] is None
    assert report["South"]["percent"] is None
    assert report["South"]["status"] == IndicatorStatus.unknown


def test_the_quotas_add_up_to_what_the_headline_should_be():
    """What the form shows under the list, so a typo is visible."""
    indicator = make(breakdown_targets={"North": 400, "South": 600})
    assert targets_total(indicator) == 1000.0

    assert targets_total(make(breakdown_targets={"North": 400, "South": "junk"})) == 400.0
    assert targets_total(make()) == 0.0


def test_progress_is_measured_against_the_category_target():
    indicator = make(breakdown_targets={"North": 400, "South": 600})
    report = breakdown_progress(indicator, {"North": 200.0, "South": 300.0})
    # Both are half of their own quota, though they are different counts.
    assert report["North"]["percent"] == 50.0
    assert report["South"]["percent"] == 50.0
    assert report["North"]["target"] == 400
    assert report["South"]["target"] == 600


def test_thresholds_scale_with_the_category_target():
    """The whole point, and the thing that is wrong if this is left out.

    North's quota is 400 against a headline of 1000, so its warning threshold
    is 800 x 0.4 = 320 rather than 800. At 350 interviews North is comfortably
    ahead of its own pace. Judged against the headline's 800 it would be
    reported critical, and somebody would be sent to fix a province that is
    doing fine.
    """
    indicator = make(breakdown_targets={"North": 400})
    report = breakdown_progress(indicator, {"North": 350.0})
    assert report["North"]["status"] == IndicatorStatus.ok


def test_a_category_genuinely_behind_is_still_flagged():
    """Scaling must not turn the thresholds off."""
    indicator = make(breakdown_targets={"North": 400})
    # 150 is below North's scaled critical threshold of 500 x 0.4 = 200.
    report = breakdown_progress(indicator, {"North": 150.0})
    assert report["North"]["status"] == IndicatorStatus.critical


def test_an_indicator_with_no_quotas_judges_none_of_its_groups():
    """Broken down for interest: the groups are reported, not marked."""
    indicator = make()
    report = breakdown_progress(indicator, {"North": 900.0, "South": 400.0})

    assert report["North"]["target"] is None
    assert report["South"]["target"] is None
    assert report["North"]["status"] == IndicatorStatus.unknown
    assert report["South"]["status"] == IndicatorStatus.unknown
    # The values themselves are still reported; it is the judgement that goes.
    assert report["North"]["value"] == 900.0


def test_lower_is_better_scales_the_same_way():
    """A rejection rate has quotas too, and the direction must survive scaling."""
    indicator = make(
        direction=Direction.lower_is_better,
        target_value=100.0,
        warning_threshold=120.0,
        critical_threshold=200.0,
        breakdown_targets={"North": 50},
    )
    # North's scaled warning is 60; 70 is past it but short of the 100 critical.
    assert breakdown_progress(indicator, {"North": 70.0})["North"]["status"] == (
        IndicatorStatus.warning
    )


@pytest.mark.parametrize("junk", ["", "not a number", None, {}])
def test_a_junk_target_is_no_target_rather_than_a_failure(junk):
    """breakdown_targets is JSON, so it can hold anything that got past a form."""
    indicator = make(breakdown_targets={"North": junk})
    assert target_for(indicator, "North") is None


def test_no_headline_target_leaves_percent_unset():
    indicator = make(target_value=None, breakdown_targets={})
    report = breakdown_progress(indicator, {"North": 120.0})
    assert report["North"]["percent"] is None
    assert report["North"]["value"] == 120.0


# --- Where the quotas are read ----------------------------------------------
#
# A quota that is only right inside the platform is half a feature: the board
# goes out as a Word report and as a standalone page, and a group drawn there
# against the headline is the same wrong comparison in a file nobody can
# correct afterwards.


def _indicator_widget(targets: dict[str, Any]) -> dict[str, Any]:
    """An indicator tile as the export payload carries one."""
    return {
        "kind": "indicator",
        "type": "indicator",
        "title": "Interviews",
        "indicator": {
            "name": "Interviews",
            "unit": "",
            "value_format": "number",
            "target_value": 1000,
            "breakdown_variable": "region",
            "breakdown_targets": targets,
            "percent_of": "",
        },
        "cube": {
            "columns": [
                {"name": "region", "label": "Region"},
                {"name": "value", "label": "Interviews"},
            ],
            "dimensions": ["region"],
            "measures": [
                {"name": "value", "label": "Interviews", "how": "sum", "parts": ["value"]}
            ],
            "rows": [["North", 200], ["South", 300]],
            "sort": [],
        },
    }


def test_the_word_report_gives_each_group_its_own_target():
    heading, rows = export_tables.widget_table(_indicator_widget({"North": 400, "South": 600}))

    assert heading[2] == "Its own target"
    assert rows[0] == ["North", 200.0, 400]
    assert rows[1] == ["South", 300.0, 600]
    # The headline belongs on the Total line, which is the only place it is
    # the right number to compare with.
    assert rows[2] == ["Total", 500.0, 1000]


def test_a_group_without_a_quota_leaves_the_column_empty():
    heading, rows = export_tables.widget_table(_indicator_widget({"North": 400}))

    assert heading[2] == "Its own target"
    assert rows[1] == ["South", 300.0, None]


def test_an_indicator_with_no_quotas_keeps_the_old_two_columns():
    heading, rows = export_tables.widget_table(_indicator_widget({}))

    assert heading == ["region", "Interviews"]
    assert rows[-1] == ["Target", 1000]


def test_the_exported_page_draws_a_group_against_its_own_quota():
    """The file is read offline, so this is checked in the script it carries."""
    script = (
        Path(__file__).resolve().parents[1]
        / "app/services/export_assets/dashboard.html"
    ).read_text(encoding="utf-8")
    drawing = script[script.index("function drawIndicator"):script.index("function drawMap")]

    assert "spec.breakdown_targets" in drawing, (
        "the exported page ignores the per-group quotas and draws bare values"
    )
    # The headline is still the tile's own progress bar, and must not be the
    # thing a breakdown bar is measured against.
    chart = drawing[drawing.index("if (breakdown.length && window.echarts)"):]
    assert "spec.target_value" not in chart


# --- A labelled breakdown ----------------------------------------------------
#
# A labelled variable is reported by its label and the quotas were offered by
# the code behind it, so an enumeration area labelled "0405" over the code 405
# carried a quota that was never applied - and nothing said so. The bars that
# worked were the ones whose label happens to be their code written out, which
# is why a board could look as though quotas were only set for some areas.


def test_a_quota_stored_against_the_code_answers_to_the_label():
    indicator = make(breakdown_targets={"405": 10, "4302": 5})
    labels = {"405": "0405", "4302": "4302"}

    assert target_for(indicator, "0405", labels) == 10
    assert target_for(indicator, "4302", labels) == 5


def test_the_label_keeps_its_own_quota_where_it_has_one():
    """A quota keyed the way quotas are keyed now wins over the code's."""
    indicator = make(breakdown_targets={"405": 10, "0405": 7})

    assert target_for(indicator, "0405", {"405": "0405"}) == 7


def test_the_breakdown_judges_a_labelled_variable_by_its_quotas():
    indicator = make(breakdown_targets={"405": 10, "902": 8})
    labels = {"405": "0405", "902": "0902"}

    report = breakdown_progress(indicator, {"0405": 4.0, "0902": 8.0}, labels)

    assert report["0405"]["target"] == 10
    assert report["0405"]["percent"] == 40.0
    assert report["0902"]["percent"] == 100.0


def test_the_quotas_still_add_up_to_what_was_entered():
    """The aliases are for looking up, not for counting: the sum is the list."""
    indicator = make(breakdown_targets={"405": 10, "902": 8})

    assert targets_total(indicator) == 18.0


def test_an_unlabelled_variable_is_unaffected():
    indicator = make(breakdown_targets={"North": 400})

    assert target_for(indicator, "North", {}) == 400
    assert target_for(indicator, "South", {}) is None


def test_the_exported_page_orders_its_breakdown_the_way_the_board_does():
    """A file that sorted its own way would be a different chart of the same
    numbers, and a reader holding both could not tell which was the board."""
    script = (
        Path(__file__).resolve().parents[1]
        / "app/services/export_assets/dashboard.html"
    ).read_text(encoding="utf-8")
    ordering = script[script.index("function ordered("):script.index("function drawIndicator")]

    # The four orders lib/breakdown-order offers, and the two rules that are
    # easy to drop: a group with no quota goes last, and with no quotas at all
    # the fallback is the largest first.
    for how in ("name", "largest", "done"):
        assert f"'{how}'" in ordering, how
    assert "!quoted" in ordering
    assert "return 1" in ordering and "return -1" in ordering
    assert "widget.config && widget.config.breakdown_order" in script
