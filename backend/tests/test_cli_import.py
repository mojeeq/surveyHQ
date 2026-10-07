"""Importing data files from the server's own disk.

A census round does not fit through a browser comfortably: the roster alone is
gigabytes, the transfer wants one connection held open for all of it, and every
proxy in the way has an opinion about request bodies. Copying the file to the
server and importing it there has none of those problems, and has to produce
exactly what an upload produces - anything less and there are two kinds of
dataset in the platform.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.cli import import_files
from app.models import AuditLog, Dataset, Project, Variable


def run(monkeypatch, *args: str) -> None:
    monkeypatch.setattr("sys.argv", ["app.cli", "import", *args])
    import_files()


def test_a_stata_file_lands_as_a_dataset_an_upload_would_have_made(
    monkeypatch, client, db_session, stata_file
):
    """The whole promise: indistinguishable from the upload route's output.

    Same parsing, same variables, same labels, same queryable Parquet, same
    audit action. If this drifts, the server-side path quietly becomes a second
    class of dataset and the interface starts lying about where things came
    from.
    """
    from app.services.datasets import dataset_directory

    run(monkeypatch, str(stata_file), "--name", "Census roster")

    dataset = db_session.scalar(select(Dataset).where(Dataset.name == "Census roster"))
    assert dataset is not None
    assert dataset.status.value == "ready"
    assert dataset.source.value == "upload"
    assert dataset.row_count == 200
    assert dataset.created_by, "nobody is recorded as having imported it"

    variables = db_session.scalars(
        select(Variable).where(Variable.dataset_id == dataset.id)
    ).all()
    assert {v.name for v in variables} >= {"interview__key", "age", "sex"}
    # The labels are the reason Stata is the preferred format: losing them here
    # would leave the interface showing bare variable names.
    assert {v.label for v in variables if v.name == "age"} == {"Age of respondent"}

    assert list(dataset_directory(dataset.id).glob("*.parquet")), "nothing to query"

    entry = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "upload_dataset").order_by(AuditLog.created_at.desc())
    )
    assert entry is not None and entry.detail.get("rows") == 200


def test_the_source_file_is_left_where_the_operator_put_it(
    monkeypatch, client, db_session, stata_file
):
    """The upload route deletes its copy because the copy is ours.

    Here the path is the operator's own file, very possibly the only copy on
    the server and one they spent an hour transferring. Deleting it would be
    taking it.
    """
    run(monkeypatch, str(stata_file), "--name", "Still there")
    assert Path(stata_file).is_file()


def test_an_archive_becomes_one_dataset_per_member(
    monkeypatch, client, tmp_path, db_session, stata_file
):
    """A Survey Solutions export is a zip of roster levels, not one table."""
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.write(stata_file, "interview.dta")
        handle.write(stata_file, "roster.dta")

    run(monkeypatch, str(archive))

    names = {d.name for d in db_session.scalars(select(Dataset)).all()}
    assert {"interview", "roster"} <= names


def test_it_imports_into_the_project_it_was_given(
    monkeypatch, client, db_session, stata_file
):
    """Census microdata belongs to a project, which is what restricts who sees it.

    Landing in the shared area instead would publish it to every user on the
    platform, which is the one mistake this command must not make quietly.
    """
    project = Project(name="Palau Census 2025", slug="palau-census-2025")
    db_session.add(project)
    db_session.commit()

    run(monkeypatch, str(stata_file), "--name", "Palau roster", "--project", "Palau Census 2025")

    dataset = db_session.scalar(select(Dataset).where(Dataset.name == "Palau roster"))
    assert dataset is not None and dataset.project_id == project.id


def test_an_unknown_project_stops_before_anything_is_read(
    monkeypatch, client, capsys, stata_file
):
    """Naming a project that does not exist is a typo, not an instruction to
    publish a census to the shared area."""
    with pytest.raises(SystemExit) as exit_code:
        run(monkeypatch, str(stata_file), "--project", "No Such Round")
    assert exit_code.value.code == 2
    assert "No project called" in capsys.readouterr().out


def test_an_unsupported_format_is_refused_by_name(monkeypatch, capsys, tmp_path):
    """Before reading, so a 4 GB file is not streamed to find out."""
    rubbish = tmp_path / "notes.docx"
    rubbish.write_bytes(b"not data")
    with pytest.raises(SystemExit) as exit_code:
        run(monkeypatch, str(rubbish))
    assert exit_code.value.code == 2
    assert ".docx" in capsys.readouterr().out


def test_a_missing_file_says_so_rather_than_half_importing(monkeypatch, capsys, tmp_path, stata_file):
    """Every path is checked before the first is read.

    Four files named and the third misspelled should import none of them, not
    two and then stop with a dataset half-made.
    """
    with pytest.raises(SystemExit) as exit_code:
        run(monkeypatch, str(stata_file), str(tmp_path / "typo.dta"))
    assert exit_code.value.code == 2
    assert "No such file" in capsys.readouterr().out


def test_naming_one_dataset_while_importing_several_is_refused(monkeypatch, capsys, stata_file):
    """--name names a dataset. Several files make several, so it cannot apply
    to all of them, and silently naming only the first would be worse."""
    with pytest.raises(SystemExit) as exit_code:
        run(monkeypatch, str(stata_file), str(stata_file), "--name", "One name")
    assert exit_code.value.code == 2
    assert "single data file" in capsys.readouterr().out
