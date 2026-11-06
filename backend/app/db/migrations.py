"""Explicit upgrade and read-only startup schema check."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db.session import engine


def config() -> Config:
    return Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


def upgrade(bind=engine) -> None:
    cfg = config()
    with bind.connect() as connection:
        # Serialize migration processes even when multiple deployments start.
        postgres = connection.dialect.name == "postgresql"
        if postgres:
            connection.execute(text("SELECT pg_advisory_lock(7349182026)"))
            connection.commit()
        try:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
            connection.commit()
        finally:
            if postgres:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(7349182026)"))
                connection.commit()


def require_current(bind=engine) -> None:
    with bind.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
    wanted = set(ScriptDirectory.from_config(config()).get_heads())
    if current != wanted:
        raise RuntimeError("Database migration required. Run: python -m app.cli migrate")
