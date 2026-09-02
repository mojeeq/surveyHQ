"""Users, roles and API keys."""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Role(str, enum.Enum):
    """Roles are hierarchical: admin > manager > analyst > viewer."""

    admin = "admin"
    manager = "manager"
    analyst = "analyst"
    viewer = "viewer"


ROLE_RANK: dict[Role, int] = {
    Role.viewer: 0,
    Role.analyst: 1,
    Role.manager: 2,
    Role.admin: 3,
}


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), default=Role.viewer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # When set, this user sees only the projects they belong to - not the shared
    # area. This is what makes "a user who can view only certain projects"
    # possible without giving every existing user a membership first.
    restricted_to_projects: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def has_role(self, minimum: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[minimum]


class ApiKey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="")
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    hashed_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="api_keys")
