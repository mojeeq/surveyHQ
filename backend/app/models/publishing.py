"""Dashboards put on a web server somewhere else, and the places they go.

A share link needs this platform running and reachable from wherever the
reader is. A ministry's website, a GitHub Pages site, a donor's portal - those
want the board itself, sitting on their server, and they want it to stay there
when this platform is a laptop on an office network that is switched off at
night.

So a dashboard can be published: the same self-contained file the HTML export
makes, carrying the numbers behind every widget at the grain its filters need
and none of the rows, pushed to a destination and kept up to date there.
"""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class PublishKind(str, enum.Enum):
    """How a destination is reached.

    Kept as text in the table rather than as a database enum: a fourth kind is
    a new class in the service and nothing else, not a migration that has to
    alter a type on PostgreSQL.
    """

    github = "github"
    sftp = "sftp"
    ftp = "ftp"


class PublishTarget(UUIDMixin, TimestampMixin, Base):
    """A web server dashboards can be published to.

    Set up by an administrator, because it holds the credentials for somebody
    else's server: a GitHub token, an SSH key, an FTP password. Anybody who may
    share a dashboard may publish to it, as anybody who may share one can make
    a link that opens it for the whole internet.
    """

    __tablename__ = "publish_targets"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # What is not secret: the repository and branch, the host and folder, the
    # address the folder is served at. See `services.publishing` for each
    # kind's keys.
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    # The token, password or private key, encrypted with ENCRYPTION_KEY as a
    # connection's password is, and never sent back out.
    secret_encrypted: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Publication(UUIDMixin, TimestampMixin, Base):
    """One dashboard at one address on one destination."""

    __tablename__ = "publications"
    # Two boards at one address would each overwrite the other, and which one
    # a reader got would depend on which was published last.
    __table_args__ = (UniqueConstraint("target_id", "path", name="uq_publication_address"),)

    dashboard_id: Mapped[str] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("publish_targets.id", ondelete="CASCADE"), index=True
    )
    # The folder on the site, under the destination's own folder, e.g.
    # "census-2017". Empty is the site's front page.
    path: Mapped[str] = mapped_column(String(200), default="")
    # A saved view to publish instead of the whole board: that view's
    # selection, fixed, with those filters gone. Not a foreign key: a view
    # that is deleted should make the next publish say so, not quietly turn
    # one province's page into the whole country's.
    view_id: Mapped[str] = mapped_column(String(36), default="")
    # Published again whenever an import changes what the board shows.
    auto_republish: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # "published" or "failed". A failed republish leaves the last good page
    # online, so the address keeps working while the fault is fixed.
    status: Mapped[str] = mapped_column(String(20), default="published")
    url: Mapped[str] = mapped_column(Text, default="")
    last_published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str] = mapped_column(Text, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # What the destination said about this publish that is worth showing,
    # e.g. that GitHub Pages had to be switched on by hand.
    notes: Mapped[list] = mapped_column(JSON, default=list)
    published_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
