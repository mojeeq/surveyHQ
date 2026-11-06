"""A report burst writes a zip, and something has to delete it afterwards.

Each burst is one HTML report per value of a filter - fourteen provinces, every
widget on the board rendered fourteen times - zipped under `reports/` and named
for the job that wrote it. A board burst weekly therefore left a zip a week on
the disk the platform runs on, for ever, and nobody downloads last month's.

Two rules, because there are two ways a zip stops being wanted. A board keeps
the last few runs and loses the rest. And a run pruned out of the jobs table by
age takes its file with it, because the download route reads the path off that
row: once the row is gone the file is unreachable and is only occupying disk.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.core.config import settings
from app.models import Job, JobStatus, JobType
from app.services import reports

BASE = dt.datetime(2026, 4, 1, tzinfo=dt.UTC)


@pytest.fixture
def place(tmp_path, monkeypatch, client) -> Path:
    """A reports directory belonging to this test alone.

    `sweep_bursts` reads the whole directory, so sharing the suite's storage
    with the other tests would make it answer differently depending on what
    had run before it. The client comes along for the schema: these tests write
    job rows directly, and it is starting the app that creates the tables.
    """
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    return reports.directory()


def _finished_run(db, dashboard_id: str, *, days_ago: int, place: Path) -> tuple[Job, Path]:
    """A successful burst, as the worker leaves one: a job row and a zip."""
    job = Job(
        job_type=JobType.export,
        status=JobStatus.success,
        title="reports by province",
        params={"dashboard_id": dashboard_id, "variable": "province"},
        created_at=BASE - dt.timedelta(days=days_ago),
    )
    db.add(job)
    db.flush()
    file = place / f"{job.id}.zip"
    file.write_bytes(b"PK\x03\x04 pretend this is fourteen reports")
    job.result = {
        "variable": "province",
        "written": ["Northern"],
        "skipped": [],
        "path": str(file),
        "bytes": file.stat().st_size,
    }
    return job, file


def test_a_board_keeps_the_newest_runs_and_loses_the_rest(db_session, place):
    runs = [
        _finished_run(db_session, "board-a", days_ago=days, place=place)
        for days in range(7)
    ]
    db_session.flush()

    dropped = reports.prune_bursts(db_session, "board-a", keep=5)

    assert dropped == 2
    kept = [file for _, file in runs[:5]]
    gone = [file for _, file in runs[5:]]
    assert all(file.exists() for file in kept), "the five newest runs are the downloadable ones"
    assert not any(file.exists() for file in gone)
    # The row stays and stops claiming a file: the run is still in the history
    # with what it wrote, and the download can say the zip is no longer there.
    assert [job.result["path"] for job, _ in runs[5:]] == ["", ""]
    assert all(job.result["written"] == ["Northern"] for job, _ in runs[5:])
    assert [job.result["path"] for job, file in runs[:5]] == [str(file) for _, file in runs[:5]]


def test_one_boards_pruning_leaves_another_boards_reports_alone(db_session, place):
    mine = [
        _finished_run(db_session, "board-a", days_ago=days, place=place)
        for days in range(6)
    ]
    theirs = [
        _finished_run(db_session, "board-b", days_ago=days, place=place)
        for days in range(6)
    ]
    db_session.flush()

    assert reports.prune_bursts(db_session, "board-a", keep=2) == 4
    assert [file.exists() for _, file in mine] == [True, True, False, False, False, False]
    assert all(file.exists() for _, file in theirs)


def test_keeping_none_still_only_reaches_this_modules_own_files(db_session, place, tmp_path):
    """A recorded path outside `reports/` is not a burst zip and is not ours."""
    stray = tmp_path / "elsewhere" / "quarterly-report.zip"
    stray.parent.mkdir()
    stray.write_bytes(b"somebody else's file")
    job = Job(
        job_type=JobType.export,
        status=JobStatus.success,
        params={"dashboard_id": "board-a"},
        result={"path": str(stray)},
        created_at=BASE,
    )
    db_session.add(job)
    db_session.flush()

    assert reports.prune_bursts(db_session, "board-a", keep=0) == 0
    assert stray.exists()
    assert job.result["path"] == str(stray)


def test_a_run_that_recorded_no_file_is_not_counted_as_one_of_the_kept(db_session, place):
    """Or `keep` would be spent on rows holding nothing."""
    empty = Job(
        job_type=JobType.export,
        status=JobStatus.success,
        params={"dashboard_id": "board-a"},
        result={"path": ""},
        created_at=BASE,
    )
    db_session.add(empty)
    older = [
        _finished_run(db_session, "board-a", days_ago=days, place=place)
        for days in range(1, 3)
    ]
    db_session.flush()

    assert reports.prune_bursts(db_session, "board-a", keep=1) == 1
    assert older[0][1].exists()
    assert not older[1][1].exists()


def test_the_sweep_takes_the_files_no_job_accounts_for(db_session, place):
    _, kept = _finished_run(db_session, "board-a", days_ago=0, place=place)
    live = kept.with_suffix(".part")
    live.write_bytes(b"a burst part way through")
    orphan = place / "11111111-1111-1111-1111-111111111111.zip"
    orphan.write_bytes(b"the job this belonged to was pruned by age")
    half = place / "22222222-2222-2222-2222-222222222222.part"
    half.write_bytes(b"a burst whose worker was killed")
    db_session.commit()

    assert reports.sweep_bursts(db_session) == 2
    assert kept.exists()
    # Named for a job that is still there, so it is a burst in flight rather
    # than a leftover - deleting it would break the run that is writing it.
    assert live.exists()
    assert not orphan.exists()
    assert not half.exists()


def test_the_sweep_leaves_anything_that_is_not_a_burst_file(db_session, place):
    note = place / "README.txt"
    note.write_text("reports land here")
    # Named exactly like a burst zip, so it is the check that this is a file
    # rather than the one on the suffix that has to spare it.
    folder = place / "44444444-4444-4444-4444-444444444444.zip"
    folder.mkdir()
    db_session.commit()

    assert reports.sweep_bursts(db_session) == 0
    assert note.exists()
    assert folder.is_dir()


def test_a_finished_burst_prunes_the_runs_behind_it(client, auth_headers, place, monkeypatch):
    """The rule has to be wired into the worker, not merely written.

    Run through the task rather than asserted about it, because the part that
    goes wrong is the ordering: the prune counts the runs whose zips are on
    disk, and the run that has just this moment finished is one of them.
    """
    from app.db.session import session_scope
    from app.workers import tasks

    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Bursting board"}
    ).json()
    with session_scope() as db:
        before = [
            _finished_run(db, board["id"], days_ago=days, place=place)[1]
            for days in range(1, 7)
        ]
        queued = Job(
            job_type=JobType.export,
            status=JobStatus.queued,
            params={"dashboard_id": board["id"], "variable": "province"},
            created_at=BASE,
        )
        db.add(queued)
        db.flush()
        job_id = queued.id

    def fake_burst(db, dashboard, variable, render, destination, on_progress=None):
        """The zip without the minutes of rendering, which is not what is under test."""
        destination.write_bytes(b"PK\x03\x04 the newest run")
        return {
            "variable": variable,
            "written": ["Northern"],
            "skipped": [],
            "path": str(destination),
            "bytes": destination.stat().st_size,
        }

    monkeypatch.setattr(reports, "burst", fake_burst)
    outcome = tasks.run_report_burst.apply(args=[job_id])
    assert outcome.successful(), outcome.result
    assert outcome.result == {"written": 1, "skipped": 0}

    newest = place / f"{job_id}.zip"
    assert newest.exists()
    # Seven runs, five kept: the two oldest go, and the run that just finished
    # is counted as the newest rather than as a seventh nobody has reckoned
    # with - which is what it would be if the prune ran before the row did.
    assert [file.exists() for file in before] == [True, True, True, True, False, False]


def test_the_nightly_prune_sweeps_the_files_left_behind(client, auth_headers, place):
    """Wired at the other end: the task that deletes the rows takes the zips."""
    from app.workers import tasks

    orphan = place / "33333333-3333-3333-3333-333333333333.zip"
    orphan.write_bytes(b"the job this belonged to was pruned by age")

    outcome = tasks.prune_history.apply()
    assert outcome.successful(), outcome.result
    assert outcome.result["report_bursts"] == 1
    assert not orphan.exists()


def test_downloading_a_pruned_run_says_so_rather_than_failing(
    client, auth_headers, db_session, place
):
    """The row outlives the file, so the route has to answer for one."""
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Pruned reports"}
    ).json()
    job, file = _finished_run(db_session, board["id"], days_ago=0, place=place)
    db_session.commit()

    served = client.get(
        f"/api/v1/dashboards/{board['id']}/reports/{job.id}.zip", headers=auth_headers
    )
    assert served.status_code == 200
    assert served.content == file.read_bytes()

    assert reports.prune_bursts(db_session, board["id"], keep=0) == 1
    db_session.commit()

    gone = client.get(
        f"/api/v1/dashboards/{board['id']}/reports/{job.id}.zip", headers=auth_headers
    )
    # 410, and not the 500 it would be if the file were tested without the
    # path: a pruned run records an empty string, and `Path("")` is the
    # working directory, which exists and is not a zip.
    assert gone.status_code == 410, gone.text
    assert "no longer on disk" in gone.json()["detail"]
