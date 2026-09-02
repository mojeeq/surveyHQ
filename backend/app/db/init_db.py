"""Schema creation and first-boot bootstrapping."""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Role, User  # noqa: F401 - registers every table

logger = get_logger(__name__)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema is up to date")


def create_first_admin() -> None:
    """Create the bootstrap administrator, but only when no users exist."""
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)) is not None:
            return
        email = settings.first_admin_email.lower()
        admin = User(
            email=email,
            full_name=settings.first_admin_name,
            role=Role.admin,
            is_active=True,
            hashed_password=hash_password(settings.first_admin_password),
        )
        db.add(admin)
        db.commit()
        logger.info("Created the first administrator account: %s", email)
        if settings.first_admin_password in ("changeme", "CHANGE-ME-strong-password"):
            logger.warning(
                "The bootstrap administrator is using the default password. "
                "Sign in and change it immediately."
            )


def initialise() -> None:
    settings.ensure_directories()
    create_tables()
    create_first_admin()
