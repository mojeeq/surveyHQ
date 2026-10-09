"""The snapshot loop, end to end against a real board."""
import datetime as dt

from sqlalchemy import select

from app.services import snapshots


def test_due_respects_weekday_time_and_last_run():
    class Board:
        snapshot_enabled = True
        snapshot_times = ["08:00"]
        snapshot_days = [0]          # Monday
        snapshot_timezone = "Pacific/Efate"
        last_snapshot_at = None

    # 2026-03-09 08:00 in Vanuatu == 2026-03-08T21:00Z
    after = dt.datetime(2026, 3, 8, 21, 5, tzinfo=dt.UTC)
    assert snapshots.due(Board(), after)

    taken = Board()
    taken.last_snapshot_at = dt.datetime(2026, 3, 8, 21, 1, tzinfo=dt.UTC)
    assert not snapshots.due(taken, after)
    assert snapshots.due(taken, dt.datetime(2026, 3, 15, 21, 5, tzinfo=dt.UTC))


def test_a_board_with_the_schedule_off_is_never_due():
    class Off:
        snapshot_enabled = False
        snapshot_times = ["08:00"]
        snapshot_days = []
        snapshot_timezone = "UTC"
        last_snapshot_at = None
    assert not snapshots.due(Off(), dt.datetime(2026, 3, 9, 9, 0, tzinfo=dt.UTC))


def test_enabled_with_no_time_is_never_due():
    # Otherwise "on" with nothing set would fire on every tick.
    class NoTime:
        snapshot_enabled = True
        snapshot_times = []
        snapshot_days = []
        snapshot_timezone = "UTC"
        last_snapshot_at = None
    assert not snapshots.due(NoTime(), dt.datetime(2026, 3, 9, 9, 0, tzinfo=dt.UTC))


def test_the_label_is_written_in_the_boards_zone():
    moment = dt.datetime(2026, 10, 12, 21, 0, tzinfo=dt.UTC)
    assert snapshots.describe(moment, "Pacific/Efate") == "Tuesday 13 October 2026, 08:00"
    assert snapshots.describe(moment, "UTC") == "Monday 12 October 2026, 21:00"


# --- through the API --------------------------------------------------------


def _board(client, auth_headers, name="Snapshot board"):
    return client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": name}
    ).json()


def test_schedule_round_trips(client, auth_headers):
    board = _board(client, auth_headers, "Scheduled")
    sent = {
        "enabled": True,
        "times": ["08:00"],
        "days": [2, 0, 0],
        "timezone": "Pacific/Efate",
        "keep": 8,
    }
    put = client.put(
        f"/api/v1/dashboards/{board['id']}/snapshot-schedule",
        headers=auth_headers,
        json=sent,
    )
    assert put.status_code == 200
    got = client.get(
        f"/api/v1/dashboards/{board['id']}/snapshot-schedule", headers=auth_headers
    ).json()
    assert got["enabled"] is True
    assert got["times"] == ["08:00"]
    # Deduplicated and sorted on the way in, so one schedule has one spelling.
    assert got["days"] == [0, 2]
    assert got["timezone"] == "Pacific/Efate"
    assert got["keep"] == 8


def test_turning_it_on_with_no_time_is_refused(client, auth_headers):
    board = _board(client, auth_headers, "No time")
    response = client.put(
        f"/api/v1/dashboards/{board['id']}/snapshot-schedule",
        headers=auth_headers,
        json={"enabled": True, "times": [], "days": [], "timezone": "UTC", "keep": 4},
    )
    # A schedule that is on and can never fire is worse than one that is off,
    # because the board says it is being kept.
    assert response.status_code == 422


def test_a_snapshot_is_taken_listed_and_served(client, auth_headers):
    board = _board(client, auth_headers, "Captured")
    made = client.post(
        f"/api/v1/dashboards/{board['id']}/snapshots", headers=auth_headers
    )
    assert made.status_code == 201, made.text
    snapshot = made.json()
    assert snapshot["size_bytes"] > 0
    assert snapshot["is_automatic"] is False

    listed = client.get(
        f"/api/v1/dashboards/{board['id']}/snapshots", headers=auth_headers
    ).json()
    assert [row["id"] for row in listed] == [snapshot["id"]]

    page = client.get(
        f"/api/v1/dashboards/{board['id']}/snapshots/{snapshot['id']}.html",
        headers=auth_headers,
    )
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert b"<html" in page.content.lower()


def test_a_snapshot_belongs_to_its_own_board(client, auth_headers):
    mine = _board(client, auth_headers, "Mine")
    theirs = _board(client, auth_headers, "Theirs")
    snapshot = client.post(
        f"/api/v1/dashboards/{mine['id']}/snapshots", headers=auth_headers
    ).json()
    # Asking the wrong board for it is a 404, not somebody else's data.
    stray = client.get(
        f"/api/v1/dashboards/{theirs['id']}/snapshots/{snapshot['id']}.html",
        headers=auth_headers,
    )
    assert stray.status_code == 404


def test_deleting_a_snapshot_takes_its_file(client, auth_headers):
    from pathlib import Path

    from app.db.session import session_scope
    from app.models import DashboardSnapshot

    board = _board(client, auth_headers, "Deleted")
    snapshot = client.post(
        f"/api/v1/dashboards/{board['id']}/snapshots", headers=auth_headers
    ).json()
    with session_scope() as db:
        path = Path(db.get(DashboardSnapshot, snapshot["id"]).storage_path)
    assert path.exists()

    gone = client.delete(
        f"/api/v1/dashboards/{board['id']}/snapshots/{snapshot['id']}",
        headers=auth_headers,
    )
    assert gone.status_code == 200
    # The row and the file go together: a file nobody can reach is just disk.
    assert not path.exists()


def test_pruning_keeps_the_newest_and_spares_hand_taken_ones(client, auth_headers):
    import datetime as dt

    from app.db.session import session_scope
    from app.models import Dashboard, DashboardSnapshot
    from app.services import snapshots as service

    board = _board(client, auth_headers, "Pruned")
    with session_scope() as db:
        dashboard = db.get(Dashboard, board["id"])
        dashboard.snapshot_keep = 2
        base = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
        for index in range(4):
            db.add(
                DashboardSnapshot(
                    dashboard_id=dashboard.id,
                    label=f"auto {index}",
                    taken_at=base + dt.timedelta(days=index),
                    is_automatic=True,
                )
            )
        # Older than every automatic one, and taken by a person.
        db.add(
            DashboardSnapshot(
                dashboard_id=dashboard.id,
                label="by hand",
                taken_at=base - dt.timedelta(days=30),
                is_automatic=False,
            )
        )
        db.commit()

        dropped = service.prune(db, dashboard)
        db.commit()
        left = sorted(
            row.label for row in db.scalars(
                select(DashboardSnapshot).where(
                    DashboardSnapshot.dashboard_id == dashboard.id
                )
            ).all()
        )

    assert dropped == 2
    # The two newest automatic ones, and the hand-taken one whatever its age:
    # somebody kept that on purpose and a schedule should not bin it.
    assert left == ["auto 2", "auto 3", "by hand"]


def test_keep_is_never_zero(client, auth_headers):
    from app.db.session import session_scope
    from app.models import Dashboard
    from app.services import snapshots as service

    board = _board(client, auth_headers, "Zero keep")
    with session_scope() as db:
        dashboard = db.get(Dashboard, board["id"])
        dashboard.snapshot_keep = 0
        db.commit()
        snapshot = service.take(
            db, dashboard, render=lambda widget, filters: None, automatic=True
        )
        db.commit()
        service.prune(db, dashboard)
        db.commit()
        # A board set to keep nothing still keeps the one just taken, rather
        # than capturing and deleting in the same breath.
        assert db.get(type(snapshot), snapshot.id) is not None
