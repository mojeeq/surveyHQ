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


class KeyMatch(str, enum.Enum):
    """How to line the two keys up before comparing them.

    `exact` compares the columns as they are stored, which is right and is the
    only one that cannot quietly match the wrong rows. It is also refused
    outright when the two sides are stored differently, because a text key and
    a numeric one cannot be compared without deciding which to convert.

    The rest are that decision, said out loud on the relationship. A survey run
    twice writes the same household as "0041" and as 41, or as "H0041" against
    41, and nothing in the data says they are the same household - only the
    person who knows the survey does.

    Each is an intent rather than a step, which is why there is no way to
    combine them: "compare the numbers inside the ids" is a thing somebody means
    about their data, where "strip letters, then unpad, then cast" is a puzzle
    to be assembled and got wrong.
    """

    exact = "exact"
    text = "text"
    number = "number"
    # H0041 against 41: the digits are the id and the rest is decoration. Leading
    # zeros go with them, because what is compared is the number they spell.
    digits = "digits"
    # INT-2024/a1 against int2024a1: here the letters carry meaning and only the
    # punctuation and the capitalisation do not.
    alphanumeric = "alphanumeric"


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
    # Left at `exact` unless somebody says otherwise: a conversion that makes
    # two keys comparable can also make two different keys equal, so it is only
    # ever done because a person asked for it.
    key_match: Mapped[KeyMatch] = mapped_column(
        Enum(KeyMatch, name="relationship_key_match"),
        default=KeyMatch.exact,
        server_default=text("'exact'"),
    )
    # True until someone edits it, so the UI can say which links were guessed.
    detected: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
