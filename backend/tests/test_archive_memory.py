"""What an archive import costs in memory.

A census export killed the worker: every member was read into a DataFrame up
front, all of them were alive at once, and the largest was then copied. The
machine had 9.7 GB and the import wanted more, so the kernel stopped it - and
because the process was killed rather than raising, the job behind it sat at
"running" for hours.

These pin the two properties that prevent it: one member in memory at a time,
and no copy of the one in hand.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from app.services.archives import ExtractedMember, extract_members
from app.services.ingest import IngestError


def _member(rows: int, columns: int = 6) -> bytes:
    frame = pd.DataFrame(
        {f"v{c}": range(rows) for c in range(columns)}
    )
    buffer = io.BytesIO()
    frame.to_stata(buffer, write_index=False, version=118)
    return buffer.getvalue()


def _archive(path, members: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as handle:
        for name, body in members.items():
            handle.writestr(name, body)
    return path


def test_extracting_an_archive_reads_none_of_it(tmp_path):
    """Unpacking is not reading.

    Reading every member to build the list is what put all of them in memory at
    once, before a single dataset had been written.
    """
    archive = _archive(
        tmp_path / "export.zip",
        {"interview.dta": _member(50), "roster.dta": _member(80)},
    )
    members = extract_members(archive, tmp_path / "work")

    assert [m.name for m in members] == ["interview.dta", "roster.dta"]
    assert all(m._loaded is None for m in members), "a member was read during extraction"


def test_a_member_holds_nothing_after_it_is_taken(tmp_path):
    """take() is what lets the loop drop one member before reading the next."""
    archive = _archive(tmp_path / "export.zip", {"interview.dta": _member(50)})
    member = extract_members(archive, tmp_path / "work")[0]

    frame, labels, values = member.take()
    assert len(frame) == 50
    assert member._loaded is None, "the member kept a reference to what it handed over"

    # Mutating what was taken must not be visible to a later read: it is the
    # caller's now, and the file on disk is unchanged.
    frame["stamped"] = "export.zip"
    assert "stamped" not in member.frame.columns


def test_releasing_a_member_frees_it(tmp_path):
    archive = _archive(tmp_path / "export.zip", {"interview.dta": _member(50)})
    member = extract_members(archive, tmp_path / "work")[0]

    assert len(member.frame) == 50
    assert member._loaded is not None
    member.release()
    assert member._loaded is None
    # Still readable afterwards: release forgets, it does not break the member.
    assert len(member.frame) == 50


def test_only_one_member_is_ever_resident_while_importing(tmp_path, monkeypatch):
    """The property the worker died for.

    Counted rather than reasoned about: every read is recorded along with how
    many members were holding a frame at that moment.
    """
    archive = _archive(
        tmp_path / "export.zip",
        {f"file{i}.dta": _member(40) for i in range(5)},
    )
    members = extract_members(archive, tmp_path / "work")

    highest = 0
    for member in members:
        frame, _, _ = member.take()
        resident = sum(1 for m in members if m._loaded is not None)
        # The one in hand was taken, so no member holds anything.
        highest = max(highest, resident + 1)
        del frame
    assert highest == 1, f"{highest} members were in memory at once"


def test_an_unreadable_member_is_found_when_it_is_read(tmp_path):
    """Extraction no longer reads, so a bad file surfaces at its first read.

    It must still be an IngestError, because the import loop catches that to
    skip the member rather than failing the whole archive.
    """
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("broken.dta", b"this is not a Stata file")

    member = extract_members(archive, tmp_path / "work")[0]
    with pytest.raises(IngestError):
        member.take()


def test_a_member_can_be_built_without_reading_anything(tmp_path):
    """The dataclass must not demand a frame it has not read yet."""
    path = tmp_path / "x.dta"
    path.write_bytes(_member(5))
    member = ExtractedMember(name="x.dta", path=path)
    assert member.name == "x.dta"
    assert member._loaded is None


def test_importing_an_archive_holds_one_member_at_a_time(tmp_path, client, db_session):
    """End to end, through load_archive_as_datasets itself.

    The unit tests above pin the member's own behaviour; this one pins that the
    import loop actually uses it that way, which is where the copy was.
    """
    from app.services import archives
    from app.services.datasets import load_archive_as_datasets

    archive = _archive(
        tmp_path / "census.zip",
        {f"level{i}.dta": _member(60) for i in range(4)},
    )

    peak = 0
    real_take = archives.ExtractedMember.take

    def counting_take(self):
        nonlocal peak
        result = real_take(self)
        # Counted at the moment of reading, which is when the previous member
        # would still be alive if the loop had not released it.
        peak = max(peak, sum(1 for m in seen if m._loaded is not None) + 1)
        return result

    seen: list = []
    real_extract = archives.extract_members

    def remembering_extract(path, destination):
        members = real_extract(path, destination)
        seen.extend(members)
        return members

    import app.services.datasets as datasets_module

    original = datasets_module.extract_members
    datasets_module.extract_members = remembering_extract
    archives.ExtractedMember.take = counting_take
    try:
        outcome = load_archive_as_datasets(
            db_session, archive_path=archive, archive_name="census.zip"
        )
    finally:
        datasets_module.extract_members = original
        archives.ExtractedMember.take = real_take

    assert len(outcome.datasets) == 4
    assert peak == 1, f"{peak} members were resident at once during the import"


def test_a_job_whose_worker_was_killed_is_marked_failed(client, db_session):
    """The worker is killed mid-task; nothing in the task runs again.

    Before this, the job stayed at "running" and the interface waited two hours
    on something that had already died. The message has to say what to do, not
    just that something went wrong.
    """
    from app.models import Job, JobStatus, JobType
    from app.workers.tasks import OUT_OF_MEMORY_HINT, record_task_failure

    job = Job(
        job_type=JobType.ingest,
        status=JobStatus.running,
        title="Import census.zip",
        celery_task_id="task-that-died",
    )
    db_session.add(job)
    db_session.commit()

    class WorkerLostError(Exception):
        pass

    record_task_failure(task_id="task-that-died", exception=WorkerLostError("signal 9"))

    db_session.expire_all()
    after = db_session.get(Job, job.id)
    assert after.status == JobStatus.failed
    assert "ran out of memory" in after.error
    assert after.error == OUT_OF_MEMORY_HINT


def test_a_job_that_already_failed_itself_is_left_alone(client, db_session):
    """A task that handled its own error wrote a specific message. Replacing it
    with a generic one would lose the reason."""
    from app.models import Job, JobStatus, JobType
    from app.workers.tasks import record_task_failure

    job = Job(
        job_type=JobType.ingest,
        status=JobStatus.failed,
        title="Import census.zip",
        celery_task_id="task-that-explained-itself",
        error="The files inside this archive expand to more than 64 GB.",
    )
    db_session.add(job)
    db_session.commit()

    record_task_failure(task_id="task-that-explained-itself", exception=RuntimeError("boom"))

    db_session.expire_all()
    assert "64 GB" in db_session.get(Job, job.id).error


def test_a_job_left_running_past_any_possible_limit_is_reaped(client, db_session):
    """For the case the signal cannot cover: the whole container went away.

    Nothing is left to fire a signal, so a job can claim to be running for ever.
    Celery will not let a task outlive its hard limit, so past that the job is
    finished one way or another.
    """
    import datetime as dt

    from app.db.base import utcnow
    from app.models import Job, JobStatus, JobType
    from app.workers.celery_app import celery_app
    from app.workers.tasks import reap_stale_jobs

    long_ago = utcnow() - dt.timedelta(seconds=celery_app.conf.task_time_limit + 3600)
    stale = Job(
        job_type=JobType.ingest,
        status=JobStatus.running,
        title="Import census.zip",
        started_at=long_ago,
    )
    fresh = Job(
        job_type=JobType.ingest,
        status=JobStatus.running,
        title="Import small.zip",
        started_at=utcnow(),
    )
    db_session.add_all([stale, fresh])
    db_session.commit()

    reap_stale_jobs()

    db_session.expire_all()
    assert db_session.get(Job, stale.id).status == JobStatus.failed
    # A job still within the limit may genuinely be working. Failing it would
    # throw away an import that was about to finish.
    assert db_session.get(Job, fresh.id).status == JobStatus.running


def test_the_previous_frame_is_gone_before_the_next_is_read(tmp_path, client, db_session):
    """Releasing the member is only half of it.

    take() stops the *member* holding the frame, but the loop's own local still
    points at it, so without dropping that too the previous member is alive
    while the next is read - two frames at the peak instead of one, which on a
    census roster is the difference that matters.

    Measured with weak references: if the object were still reachable the
    reference would still resolve.
    """
    import weakref

    from app.services import archives
    from app.services.datasets import load_archive_as_datasets

    archive = _archive(
        tmp_path / "census.zip",
        {f"level{i}.dta": _member(60) for i in range(4)},
    )

    alive: list[weakref.ref] = []
    still_reachable: list[int] = []
    real_take = archives.ExtractedMember.take

    def watching_take(self):
        # Anything handed out earlier should have been dropped by now.
        still_reachable.append(sum(1 for ref in alive if ref() is not None))
        frame, labels, values = real_take(self)
        alive.append(weakref.ref(frame))
        return frame, labels, values

    archives.ExtractedMember.take = watching_take
    try:
        outcome = load_archive_as_datasets(
            db_session, archive_path=archive, archive_name="census.zip"
        )
    finally:
        archives.ExtractedMember.take = real_take

    assert len(outcome.datasets) == 4
    assert still_reachable == [0, 0, 0, 0], (
        f"a previous member's frame was still in memory when the next was read: {still_reachable}"
    )
