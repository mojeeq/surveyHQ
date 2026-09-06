"""Judging each group of a broken-down indicator against its own target.

A survey's quota is rarely one number. "6,000 interviews" is really 3,500 in
one province and 2,500 in another, or a set number of men and of women. Read
against the single headline target, a group that is well behind its own quota
reported as on track simply because the headline is the sum of several unequal
quotas - which is the opposite of what a monitoring platform is for.
"""

from __future__ import annotations

import pytest

from app.models import Indicator
from app.models.monitoring import Direction
from app.services.monitoring import IndicatorStatus, breakdown_progress, target_for


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


def test_a_category_without_one_falls_back_to_the_headline():
    """An indicator broken down for interest, not against a quota."""
    indicator = make(breakdown_targets={"North": 400})
    assert target_for(indicator, "South") == 1000.0


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


def test_without_per_category_targets_nothing_changes():
    """The existing behaviour, for every indicator that has no quotas set."""
    indicator = make()
    report = breakdown_progress(indicator, {"North": 900.0, "South": 400.0})
    assert report["North"]["status"] == IndicatorStatus.ok
    assert report["South"]["status"] == IndicatorStatus.critical
    assert report["North"]["target"] == 1000.0


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
def test_a_junk_target_falls_back_rather_than_failing(junk):
    """breakdown_targets is JSON, so it can hold anything that got past a form."""
    indicator = make(breakdown_targets={"North": junk})
    assert target_for(indicator, "North") == 1000.0


def test_no_headline_target_leaves_percent_unset():
    indicator = make(target_value=None, breakdown_targets={})
    report = breakdown_progress(indicator, {"North": 120.0})
    assert report["North"]["percent"] is None
    assert report["North"]["value"] == 120.0
