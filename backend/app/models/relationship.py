"""Declared links between the datasets in a project.

A survey export arrives as several tables that mean nothing apart: the
interview, the household members, the people abroad. What connects them is
already in the data - every Survey Solutions level carries interview__id, and a
roster adds its own row index - so these links can be proposed by looking at the
data rather than drawn by hand, and then corrected where the guess is wrong.

A relationship is a statement about the data, not a query. It is what makes a
merge expressible ("join the persons to their interview") and what the model
view draws.
"""

from __future__ import annotations

import enum

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Cardinality(str, enum.Enum):
    """How many rows on each side share a key value."""

    one_to_one = "one_to_one"
    one_to_many = "one_to_many"
    many_to_one = "many_to_one"
    many_to_many = "many_to_many"


class DatasetRelationship(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "dataset_relationships"
    __table_args__ = (
        UniqueConstraint(
            "left_dataset_id",
            "right_dataset_id",
            "left_variable",
            "right_variable",
            name="uq_dataset_relationship",
        ),
    )

    # Null means the shared area, the same rule as everywhere else. Both
    # datasets must be in the same place for a relationship to be proposed.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    left_dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    right_dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    left_variable: Mapped[str] = mapped_column(String(300))
    right_variable: Mapped[str] = mapped_column(String(300))
    cardinality: Mapped[Cardinality] = mapped_column(
        Enum(Cardinality, name="relationship_cardinality"),
        default=Cardinality.one_to_many,
    )
    # False keeps a relationship on the diagram without offering it for merging,
    # which is how you disagree with a detected one without deleting it.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    # True until someone edits it, so the UI can say which links were guessed.
    detected: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
