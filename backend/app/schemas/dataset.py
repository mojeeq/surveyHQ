from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.dataset import DatasetSource, DatasetStatus, VariableType


class VariableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    label: str = ""
    var_type: VariableType
    storage_type: str = ""
    position: int = 0
    n_missing: int = 0
    n_unique: int = 0
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    value_labels: dict[str, str] = Field(default_factory=dict)
    missing_tags: list[str] = Field(default_factory=list)
    is_hidden: bool = False


class VariableUpdate(BaseModel):
    """Labels a person writes for a variable the export did not label."""

    label: str | None = None
    # Code -> what to show for it. Codes are strings because that is how a JSON
    # object keys them, and how the stored labels from the file are keyed too.
    value_labels: dict[str, str] | None = None
    is_hidden: bool | None = None


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str = ""
    source: DatasetSource
    source_ref: str = ""
    connection_id: str | None = None
    project_id: str | None = None
    status: DatasetStatus
    error: str = ""
    row_count: int = 0
    column_count: int = 0
    file_size: int = 0
    tags: list[str] = Field(default_factory=list)
    # Non-empty when this dataset was built from others and can be rebuilt.
    derivation: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    refreshed_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class DatasetDetail(DatasetOut):
    variables: list[VariableOut] = Field(default_factory=list)


class ArchiveImportOut(BaseModel):
    """What uploading one export archive did.

    An archive yields several datasets, so this reports per member file rather
    than describing a single one: which were created, which were appended to,
    and anything the import wants the user to know before trusting the numbers.
    """

    datasets: list[DatasetOut] = Field(default_factory=list)
    created: list[str] = Field(default_factory=list)
    appended: list[str] = Field(default_factory=list)
    replaced: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rows: int = 0


class DatasetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class DatasetPreview(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    limit: int
    offset: int
