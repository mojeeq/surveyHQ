from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.relationship import Cardinality


class RelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None = None
    left_dataset_id: str
    right_dataset_id: str
    left_variable: str
    right_variable: str
    cardinality: Cardinality
    is_active: bool
    detected: bool
    created_at: dt.datetime
    # Filled in by the endpoint so the diagram can label itself without a
    # second request per dataset.
    left_name: str = ""
    right_name: str = ""


class RelationshipIn(BaseModel):
    left_dataset_id: str
    right_dataset_id: str
    left_variable: str
    right_variable: str
    cardinality: Cardinality = Cardinality.one_to_many


class RelationshipUpdate(BaseModel):
    left_variable: str | None = None
    right_variable: str | None = None
    cardinality: Cardinality | None = None
    is_active: bool | None = None


class DetectedRelationship(BaseModel):
    """A proposal, before anyone decides whether to keep it."""

    left_dataset_id: str
    right_dataset_id: str
    left_name: str
    right_name: str
    left_variable: str
    right_variable: str
    cardinality: Cardinality
    # Share of the right side's key values that exist on the left. A low number
    # is not wrong - only 18% of interviews have someone living abroad - but it
    # is worth seeing before trusting a link.
    overlap: float


class DetectionResult(BaseModel):
    proposed: list[DetectedRelationship] = Field(default_factory=list)
    created: int = 0


class MergeIn(BaseModel):
    """Build a new dataset by joining two that are already related."""

    name: str = Field(min_length=1, max_length=200)
    relationship_id: str
    # "left" keeps every row of the left dataset; "inner" keeps only matches.
    how: str = Field(default="left", pattern="^(left|inner)$")
    # Columns to take from the right side. Empty means all of them.
    columns: list[str] = Field(default_factory=list)
    prefix: str = ""
