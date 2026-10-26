"""How an indicator has moved, and when it gets where it is going.

A tile showed the number, how far it was from target and a sparkline, and left
"how many since yesterday" and "when do we finish at this rate" to arithmetic
on the sparkline. These fix the arithmetic: which stored value counts as
yesterday's, what the pace is averaged over, when a projection is made and
when it is honestly left out.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.models import Indicator, IndicatorSnapshot
from app.models.monitoring import Direction
from app.services.monitoring import movement
from tests.test_indicator_formulas import fieldwork, make  # noqa: F401 - a fixture
from tests.test_indicator_widget_filter import (  # noqa: F401 - surveyed is a fixture
    make_indicator,
    only,
    place_tile,
    render,
    surveyed,
)

NOW = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def indicator(client, auth_headers, db_session, fieldwork) -> Indicator:  # noqa: F811
    made = make(client, auth_headers, fieldwork["dataset_id"], target_value=1000)
    db_session.expire_all()
    return db_session.get(Indicator, made["id"])


def stored(db_session, indicator: Indicator, *points: tuple[dt.timedelta, float]) -> None:
    """Values as the scheduled runs would have kept them, so long before now."""
    db_session.query(IndicatorSnapshot).filter_by(indicator_id=indicator.id).delete()
    for ago, value in points:
        db_session.add(
            IndicatorSnapshot(indicator_id=indicator.id, value=value, breakdown={},
                              computed_at=NOW - ago)
        )
    db_session.flush()


DAY = dt.timedelta(days=1)


def test_a_new_indicator_says_nothing_it_cannot_know(db_session, indicator):
    stored(db_session, indicator)
    moved = movement(db_session, indicator, 500, now=NOW)
    assert moved["change_day"] is None
    assert moved["change_week"] is None
    assert moved["pace_per_day"] is None
    assert "projected_at" not in moved


def test_since_yesterday_and_last_week(db_session, indicator):
    stored(db_session, indicator, (8 * DAY, 100), (6 * DAY, 200), (DAY + dt.timedelta(hours=2), 450))
    moved = movement(db_session, indicator, 500, now=NOW)
    # The last value kept at least a day ago, and at least a week ago.
    assert moved["change_day"] == pytest.approx(50)
    assert moved["change_week"] == pytest.approx(400)


def test_the_pace_is_the_last_weeks_rise_over_the_days_it_took(db_session, indicator):
    stored(db_session, indicator, (6 * DAY, 200), (DAY, 450))
    moved = movement(db_session, indicator, 500, now=NOW)
    assert moved["pace_per_day"] == pytest.approx(50)
    assert moved["pace_days"] == pytest.approx(6.0)
    # 500 to go at 50 a day.
    assert dt.datetime.fromisoformat(moved["projected_at"]) == NOW + 10 * DAY


def test_with_a_date_it_says_what_it_takes_and_whether_it_will(db_session, indicator):
    indicator.target_date = (NOW + 4 * DAY).date()
    stored(db_session, indicator, (6 * DAY, 200))
    moved = movement(db_session, indicator, 500, now=NOW)
    # Today and the four days after it, the last one included.
    assert moved["days_left"] == 5
    assert moved["needed_per_day"] == pytest.approx(100)
    assert moved["on_course"] is False


def test_less_than_a_day_of_history_is_not_a_pace(db_session, indicator):
    stored(db_session, indicator, (dt.timedelta(hours=5), 300))
    moved = movement(db_session, indicator, 500, now=NOW)
    assert moved["pace_per_day"] is None
    assert "projected_at" not in moved


def test_a_pace_going_the_wrong_way_finishes_never(db_session, indicator):
    stored(db_session, indicator, (3 * DAY, 600))
    moved = movement(db_session, indicator, 500, now=NOW)
    assert moved["pace_per_day"] < 0
    assert "projected_at" not in moved


def test_a_target_met_is_said_and_not_projected(db_session, indicator):
    stored(db_session, indicator, (3 * DAY, 800))
    moved = movement(db_session, indicator, 1200, now=NOW)
    assert moved["reached"] is True
    assert "projected_at" not in moved and "needed_per_day" not in moved


def test_lower_is_better_comes_down_to_its_target(db_session, indicator):
    """A refusal rate of 30% heading for a ceiling of 20%: it reaches it by
    falling, and falling is the pace that counts."""
    indicator.direction = Direction.lower_is_better
    indicator.target_value = 20
    stored(db_session, indicator, (5 * DAY, 40))
    moved = movement(db_session, indicator, 30, now=NOW)
    assert moved["pace_per_day"] == pytest.approx(-2)
    assert dt.datetime.fromisoformat(moved["projected_at"]) == NOW + 5 * DAY


def test_a_neutral_indicator_has_nowhere_to_get_to(db_session, indicator):
    indicator.direction = Direction.neutral
    stored(db_session, indicator, (3 * DAY, 200))
    moved = movement(db_session, indicator, 500, now=NOW)
    assert moved["pace_per_day"] == pytest.approx(100)
    assert "projected_at" not in moved


def test_the_target_date_is_kept_and_served(client, auth_headers, fieldwork):  # noqa: F811
    made = make(client, auth_headers, fieldwork["dataset_id"], target_value=1000,
                target_date="2026-11-30")
    assert made["target_date"] == "2026-11-30"
    changed = client.patch(
        f"/api/v1/monitoring/indicators/{made['id']}", headers=auth_headers,
        json={"target_date": None},
    ).json()
    assert changed["target_date"] is None
    values = client.get("/api/v1/monitoring/indicators/values", headers=auth_headers).json()
    mine = next(one for one in values if one["indicator_id"] == made["id"])
    assert "change_day" in mine["movement"]


def test_a_filtered_tile_leaves_the_movement_out(client, auth_headers, surveyed):  # noqa: F811
    """The stored values were counted over the whole dataset; "+50 since
    yesterday" under a number for one province would be two questions in one
    tile, as the sparkline would be."""
    made = make_indicator(client, auth_headers, surveyed["dataset_id"], target_value=20.0)
    place_tile(client, auth_headers, surveyed["board"], made["id"])
    assert "change_day" in render(client, auth_headers, surveyed["board"])["movement"]
    assert render(client, auth_headers, surveyed["board"], only("Northern"))["movement"] == {}
