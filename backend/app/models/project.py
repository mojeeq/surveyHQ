"""Projects: the container that scopes data and who may see it.

A project owns datasets and dashboards directly. Everything else - charts,
indicators, quality rules, alert rules - reaches a project through the dataset
it already references, so there is exactly one place a resource's project is
recorded and no way for the two to disagree.

Resources with no project belong to the shared area every user can reach. That
is what the whole platform looked like before projects existed, so an upgraded
deployment keeps working unchanged and a project is something you opt into.
"""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.user import Role


class ProjectStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    closed = "closed"


class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), default=ProjectStatus.active
    )
    # The field period, used for progress against the calendar
    starts_on: Mapped[dt.date | None] = mapped_column(Date)
    ends_on: Mapped[dt.date | None] = mapped_column(Date)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(UUIDMixin, TimestampMixin, Base):
    """One user's access to one project.

    The role here grants access within the project but never beyond the user's
    own role, so making someone a project manager cannot turn a viewer into an
    editor of anything. See services.projects.effective_role.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Reuses the global role vocabulary rather than inventing a parallel one.
    # "admin" is not offered here: administration is global, not per project.
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role"), default=Role.viewer
    )

    project: Mapped[Project] = relationship(back_populates="members")


class ProjectScript(UUIDMixin, TimestampMixin, Base):
    """An R script kept in a project's workspace.

    A project is an environment, not a folder of files. The scripts that
    prepare its data belong to it rather than to any one dataset: a recode
    usually reads the household file and writes the person file, and pinning it
    to one of the two was always a fiction. Keeping them here also means the
    order they run in is a property of the project, which is what makes "run
    everything again on the new export" mean something.
    """

    __tablename__ = "project_scripts"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    code: Mapped[str] = mapped_column(Text, default="")
    # Run after a new export lands in this project. A variable somebody derived
    # is not in the file that arrives, so without this it disappears on exactly
    # the upload the platform exists to make routine.
    run_on_import: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Where it sits in the order they are run in. Scripts build on each other,
    # so "all of them again" has to mean something more than "in some order".
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    # What the last run printed, so opening the project shows how it went
    # without running it again.
    last_output: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
