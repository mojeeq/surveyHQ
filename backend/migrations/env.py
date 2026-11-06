"""Use the same database configuration as the application."""

from alembic import context

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import engine


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    with engine.connect() as connection:
        run(connection)
