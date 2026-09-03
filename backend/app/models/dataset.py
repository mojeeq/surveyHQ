"""Datasets and their variable metadata."""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class DatasetStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class DatasetSource(str, enum.Enum):
    upload = "upload"
    survey_solutions = "survey_solutions"
    derived = "derived"


class VariableType(str, enum.Enum):
    """Semantic type driving how the UI offers a variable for analysis."""

    numeric = "numeric"
    categorical = "categorical"
    text = "text"
    datetime = "datetime"
    boolean = "boolean"


class Dataset(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "datasets"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[DatasetSource] = mapped_column(
        Enum(DatasetSource, name="dataset_source"), default=DatasetSource.upload
    )
    source_ref: Mapped[str] = mapped_column(String(500), default="")
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Null means the shared area: visible to everyone, which is what every
    # dataset was before projects existed. Deleting a project releases its
    # datasets back there rather than destroying them.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[DatasetStatus] = mapped_column(
        Enum(DatasetStatus, name="dataset_status"), default=DatasetStatus.pending
    )
    error: Mapped[str] = mapped_column(Text, default="")
    storage_path: Mapped[str] = mapped_column(String(500), default="")
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    # How this dataset was derived from others, when it was not uploaded:
    # {"type": "merge", "relationship_id": ..., "how": "left", ...}. Empty for
    # an uploaded dataset. Holding the recipe rather than only the result is
    # what lets the merge be re-run when its sources change.
    derivation: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    # Variables the platform recognises as meaningful for monitoring
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    refreshed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    variables: Mapped[list[Variable]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="Variable.position",
    )


class Variable(UUIDMixin, Base):
    __tablename__ = "variables"

    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(300), index=True)
    label: Mapped[str] = mapped_column(Text, default="")
    var_type: Mapped[VariableType] = mapped_column(
        Enum(VariableType, name="variable_type"), default=VariableType.text
    )
    storage_type: Mapped[str] = mapped_column(String(50), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    n_missing: Mapped[int] = mapped_column(BigInteger, default=0)
    n_unique: Mapped[int] = mapped_column(BigInteger, default=0)
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    mean_value: Mapped[float | None] = mapped_column(Float)
    value_labels: Mapped[dict] = mapped_column(JSON, default=dict)
    # Stata tagged missings present on this variable, e.g. [".a", ".b"]
    missing_tags: Mapped[list] = mapped_column(JSON, default=list, nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    dataset: Mapped[Dataset] = relationship(back_populates="variables")
