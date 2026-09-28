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
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.user import Role


class ProjectStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    closed = "closed"
    # The survey data has been removed to reclaim the disk, and everything built
    # on it kept: the datasets' names and variables, the dashboards, charts,
    # indicators, quality rules, relationships and the project's script. A round
    # that is finished with should not have to be deleted to stop costing
    # storage, and deleting it threw away months of somebody's work along with
    # the microdata.
    archived = "archived"


class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), default=ProjectStatus.active
    )
    # When the data was removed, which is what the interface dates the archive
    # by. Held rather than derived from updated_at, which moves whenever anybody
    # renames anything.
    archived_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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


class ProjectScript(UUIDMixin, TimestampMixin, Base):
    """The project's do-file: one script, written once and re-run.

    One per project rather than a library of them. A project's data preparation
    is a single sequence - read these files, put them together, write those out
    - and splitting it across several scripts only raises the question of which
    order they run in, which is a question the script itself already answers by
    being written top to bottom.

    `reads` and `writes` are what the last run actually touched, recorded
    rather than parsed out of the text. That is what lets a newer export of one
    dataset re-run the scripts that stand on it, and only those: parsing would
    have to resolve names the way `use` does, and would count a line that never
    ran because the one above it failed.
    """

    __tablename__ = "project_scripts"
    __table_args__ = (UniqueConstraint("project_id", name="uq_project_script"),)

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # The datasets the last run read and the ones it wrote, by id.
    reads: Mapped[list] = mapped_column(JSON, default=list)
    writes: Mapped[list] = mapped_column(JSON, default=list)

    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Empty when the last run finished. Otherwise what stopped it, kept so the
    # project page can say a nightly re-run failed without anybody watching.
    last_error: Mapped[str] = mapped_column(Text, default="")


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
