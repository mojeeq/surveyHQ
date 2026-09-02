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


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str = ""
    source: DatasetSource
    source_ref: str = ""
    connection_id: str | None = None
    status: DatasetStatus
    error: str = ""
    row_count: int = 0
    column_count: int = 0
    file_size: int = 0
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    refreshed_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class DatasetDetail(DatasetOut):
    variables: list[VariableOut] = Field(default_factory=list)


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
