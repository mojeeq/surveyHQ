"""When an automatic import is due.

The awkward cases are the ones worth writing down: midnight, the day before,
and a zone that is most of a day away from UTC - which Vanuatu, at UTC+11, very
nearly is.
"""

from __future__ import annotations

import datetime as dt

from app.services.scheduling import is_due, last_occurrence, valid_time, valid_timezone

VANUATU = "Pacific/Efate"  # UTC+11, no daylight saving


def utc(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC)


def test_a_time_has_to_look_like_one():
    assert valid_time("06:00")
    assert valid_time("23:59")
    assert not valid_time("24:00")
    assert not valid_time("6:00")
    assert not valid_time("noon")


def test_a_zone_has_to_be_a_real_one():
    assert valid_timezone("Pacific/Efate")
    assert valid_timezone("UTC")
    assert not valid_timezone("Middle/Earth")


def test_the_time_is_read_where_the_fieldwork_is():
    """06:00 in Vanuatu is 19:00 the previous day in UTC.

    Reading it as UTC would run the import thirteen hours out, which on a daily
    schedule is the difference between "before the office opens" and "in the
    middle of the afternoon".
    """
    # 2026-03-10 20:00 UTC is 2026-03-11 07:00 in Vanuatu, so the 06:00 slot
    # for the 11th has just passed.
    occurrence = last_occurrence(["06:00"], utc("2026-03-10T20:00"), VANUATU)
    assert occurrence is not None
    assert occurrence.isoformat() == "2026-03-11T06:00:00+11:00"
    assert occurrence == utc("2026-03-10T19:00")


def test_just_before_the_slot_the_answer_is_yesterday_s():
    occurrence = last_occurrence(["06:00"], utc("2026-03-10T18:59"), VANUATU)
    assert occurrence == utc("2026-03-09T19:00")


def test_two_slots_a_day_are_both_honoured():
    morning = last_occurrence(["06:00", "18:00"], utc("2026-03-10T20:00"), VANUATU)
    assert morning == utc("2026-03-10T19:00")  # 06:00 local on the 11th
    evening = last_occurrence(["06:00", "18:00"], utc("2026-03-11T08:00"), VANUATU)
    assert evening == utc("2026-03-11T07:00")  # 18:00 local on the 11th


def test_no_times_means_nothing_is_due():
    assert last_occurrence([], utc("2026-03-10T20:00"), VANUATU) is None
    assert not is_due(
        mode="daily",
        times=[],
        timezone=VANUATU,
        interval_minutes=60,
        last_sync_at=None,
        now=utc("2026-03-10T20:00"),
    )


def test_a_daily_slot_runs_once_and_not_again_until_the_next():
    args = {
        "mode": "daily",
        "times": ["06:00"],
        "timezone": VANUATU,
        "interval_minutes": 60,
    }
    just_after = utc("2026-03-10T19:02")

    # Never run: the slot has passed, so it is due
    assert is_due(**args, last_sync_at=None, now=just_after)
    # Ran at the slot: not due again on the next tick
    assert not is_due(**args, last_sync_at=utc("2026-03-10T19:01"), now=just_after)
    assert not is_due(**args, last_sync_at=utc("2026-03-10T19:01"), now=utc("2026-03-11T05:00"))
    # Tomorrow's slot opens, and it is due again
    assert is_due(**args, last_sync_at=utc("2026-03-10T19:01"), now=utc("2026-03-11T19:01"))


def test_a_run_before_the_slot_does_not_count_as_the_slot():
    """Someone importing by hand at midnight must not cancel the 06:00 run."""
    assert is_due(
        mode="daily",
        times=["06:00"],
        timezone=VANUATU,
        interval_minutes=60,
        last_sync_at=utc("2026-03-10T13:00"),  # 00:00 local on the 11th
        now=utc("2026-03-10T19:05"),  # just after 06:00 local
    )


def test_the_interval_mode_still_counts_from_the_last_run():
    args = {"mode": "interval", "times": [], "timezone": "UTC", "interval_minutes": 360}
    assert is_due(**args, last_sync_at=None, now=utc("2026-03-10T20:00"))
    assert not is_due(
        **args, last_sync_at=utc("2026-03-10T18:00"), now=utc("2026-03-10T20:00")
    )
    assert is_due(**args, last_sync_at=utc("2026-03-10T13:00"), now=utc("2026-03-10T20:00"))


def test_a_zone_that_no_longer_exists_falls_back_rather_than_failing():
    """Wrong by hours beats an import that never runs at all."""
    occurrence = last_occurrence(["06:00"], utc("2026-03-10T20:00"), "Middle/Earth")
    assert occurrence == utc("2026-03-10T06:00")
