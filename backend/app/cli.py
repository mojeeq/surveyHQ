"""Small operational commands: python -m app.cli <command>."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.crypto import generate_key
from app.core.security import hash_password
from app.db.init_db import initialise
from app.db.session import SessionLocal
from app.models import Role, User
from app.services.accounts import next_available_username


def gen_encryption_key() -> None:
    print(generate_key())


def init_database() -> None:
    from app.db.migrations import upgrade
    upgrade()
    initialise()
    print("Database initialised.")


def create_admin() -> None:
    if len(sys.argv) < 4:
        print("Usage: python -m app.cli create-admin <email> <password> [full name]")
        raise SystemExit(2)
    email, password = sys.argv[2].lower(), sys.argv[3]
    full_name = sys.argv[4] if len(sys.argv) > 4 else "Administrator"
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            existing.hashed_password = hash_password(password)
            existing.role = Role.admin
            existing.is_active = True
            if not existing.username:
                existing.username = next_available_username(db, email)
            db.commit()
            print(f"Updated existing user {email} to administrator with a new password.")
            return
        db.add(
            User(
                email=email,
                username=next_available_username(db, email),
                full_name=full_name,
                role=Role.admin,
                hashed_password=hash_password(password),
            )
        )
        db.commit()
        print(f"Created administrator {email}.")


def reset_password() -> None:
    if len(sys.argv) < 4:
        print("Usage: python -m app.cli reset-password <email> <new password>")
        raise SystemExit(2)
    email, password = sys.argv[2].lower(), sys.argv[3]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"No user found with the email {email}.")
            raise SystemExit(1)
        user.hashed_password = hash_password(password)
        db.commit()
        print(f"Password reset for {email}.")


def migrate() -> None:
    from app.db.migrations import upgrade
    upgrade()
    print("Database migrated.")




def _said_in_bytes(count: int) -> str:
    """A file size as a person would say it, so a roster is not "2,445 MB"."""
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def import_files() -> None:
    """Import data files straight from the server's disk.

    The upload route exists for files a person can reasonably put through a
    browser. A census round is not that: a 2.3 GB roster export wants a single
    multipart POST held open for the whole transfer, roughly twice its size in
    transient disk, and any proxy in the way under its own body limit - and
    losing the connection at 90% means starting again. Copying the file to the
    server with scp or rsync, which resume, and importing it from there skips
    every one of those problems.

    The ingest path is the same one the upload route uses, so what lands is
    indistinguishable from an uploaded dataset: same parsing, same labels and
    value labels, same Parquet, same dataset record, same audit entry.
    """
    import argparse

    from app.models import Dataset, Project
    from app.services import archive as archiving
    from app.services import stata
    from app.services.audit import record
    from app.services.datasets import (
        ArchiveImport,
        create_dataset_record,
        load_archive_as_datasets,
        load_file_into_dataset,
        merge_imports,
    )
    from app.services.derived import rebuild_dependents
    from app.services.ingest import SUPPORTED_EXTENSIONS, IngestError

    parser = argparse.ArgumentParser(
        prog="python -m app.cli import",
        description="Import data files from the server's own disk.",
    )
    parser.add_argument("paths", nargs="+", help="Files to import (.dta, .sav, .csv, .xlsx, .zip)")
    parser.add_argument(
        "--project", default="", help="Project name or id. Omitted: the shared area"
    )
    parser.add_argument(
        "--user", default="", help="Email to record as the importer. Omitted: an administrator"
    )
    parser.add_argument("--name", default="", help="Dataset name. Only with a single data file")
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="", help="Comma separated")
    parser.add_argument(
        "--mode",
        default="replace",
        choices=("replace", "append"),
        help="For a .zip whose member files match datasets that already exist",
    )
    options = parser.parse_args(sys.argv[2:])

    files = [Path(one).expanduser() for one in options.paths]
    for path in files:
        if not path.is_file():
            print(f"No such file: {path}")
            raise SystemExit(2)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS and path.suffix.lower() != ".zip":
            print(
                f"'{path.suffix or path.name}' is not a supported format. Use a .zip "
                "archive, or one of: " + ", ".join(sorted(SUPPORTED_EXTENSIONS))
            )
            raise SystemExit(2)
    data_files = [one for one in files if one.suffix.lower() != ".zip"]
    if options.name and len(data_files) > 1:
        print("--name names one dataset, so give it with a single data file.")
        raise SystemExit(2)

    settings.ensure_directories()
    with SessionLocal() as db:
        # Somebody has to own the import: the dataset records who created it and
        # the audit log records who imported it. An administrator is the honest
        # default for a command only somebody with a shell on the server can run.
        if options.user:
            user = db.scalar(select(User).where(User.email == options.user.lower()))
            if user is None:
                print(f"No user with the email {options.user}")
                raise SystemExit(2)
        else:
            user = db.scalar(
                select(User)
                .where(User.role == Role.admin, User.is_active)
                .order_by(User.created_at)
            )
            if user is None:
                print("No administrator to attribute this to. Pass --user.")
                raise SystemExit(2)

        project = None
        if options.project:
            project = db.scalar(
                select(Project).where(
                    or_(Project.id == options.project, Project.name == options.project)
                )
            )
            if project is None:
                print(f"No project called {options.project!r}. Its name or its id.")
                raise SystemExit(2)
            # Importing into an archived project would un-archive half of it:
            # some datasets holding rows again, the project still saying none.
            try:
                archiving.refuse_if_archived(project, "importing data")
            except ValueError as exc:
                print(str(exc))
                raise SystemExit(2) from exc

        project_id = project.id if project else None
        tags = [one.strip() for one in options.tags.split(",") if one.strip()]
        where = f"project {project.name}" if project else "the shared area"
        print(f"Importing {len(files)} file(s) into {where} as {user.email}.")

        made: list[Dataset] = []
        try:
            for path in files:
                # A whole line at a time. Written with end="" the loaders' own
                # log lines land in the middle of it, and the result of one file
                # ends up on the same line as the name of the next.
                print(f"  {path.name} ({_said_in_bytes(path.stat().st_size)})", flush=True)
                if path.suffix.lower() == ".zip":
                    outcome: ArchiveImport = merge_imports(
                        ArchiveImport(),
                        load_archive_as_datasets(
                            db,
                            archive_path=path,
                            archive_name=path.name,
                            project_id=project_id,
                            created_by=user.id,
                            name_prefix=options.name,
                            mode=options.mode,
                            # A variable somebody generated is not in the export
                            # that just landed, so the commands recorded on each
                            # replaced dataset are run again over the new data.
                            after_replace=stata.replay,
                        ),
                    )
                    rebuild_dependents(db, outcome.replaced_ids)
                    made.extend(outcome.datasets)
                    print(f"    {len(outcome.datasets)} dataset(s)")
                    record(
                        db,
                        user=user,
                        action="upload_archive",
                        entity_type="dataset",
                        detail={"filename": path.name, "datasets": len(outcome.datasets)},
                    )
                else:
                    dataset = create_dataset_record(
                        db,
                        name=options.name.strip() or path.stem,
                        description=options.description,
                        source_ref=path.name,
                        tags=tags,
                        created_by=user.id,
                        project_id=project_id,
                    )
                    load_file_into_dataset(db, dataset, path)
                    made.append(dataset)
                    print(
                        f"    {dataset.row_count:,} rows, "
                        f"{dataset.column_count} columns"
                    )
                    record(
                        db,
                        user=user,
                        action="upload_dataset",
                        entity_type="dataset",
                        entity_id=dataset.id,
                        detail={"filename": path.name, "rows": dataset.row_count},
                    )
        except IngestError as exc:
            # Commit rather than roll back, the way the upload route does: the
            # dataset record carries the reason it failed, and seeing it in the
            # interface beats a dataset that silently never appeared.
            db.commit()
            print("    failed")
            print(f"\n{exc}")
            raise SystemExit(1) from exc

        db.commit()
        print(f"\nImported {len(made)} dataset(s):")
        for dataset in made:
            db.refresh(dataset)
            print(f"  {dataset.name}  {dataset.row_count:,} rows")
        # The file is the operator's, sitting where they put it. The upload
        # route deletes its copy because the copy was ours; deleting theirs
        # would be taking their only one.
        print("\nThe source files were left where they are.")


COMMANDS = {
    "migrate": migrate,
    "gen-encryption-key": gen_encryption_key,
    "init-db": init_database,
    "create-admin": create_admin,
    "reset-password": reset_password,
    "import": import_files,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Available commands:")
        for name in COMMANDS:
            print(f"  {name}")
        raise SystemExit(2)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
