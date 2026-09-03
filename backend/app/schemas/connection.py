from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models.connection import ExportFormat, SyncStatus


class ConnectionBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str
    workspace: str = "primary"
    username: str = ""
    verify_ssl: bool = True
    sync_enabled: bool = False
    sync_interval_minutes: int = Field(default=360, ge=5, le=10080)
    export_format: ExportFormat = ExportFormat.stata
    questionnaires: list[str] = Field(default_factory=list)
    interview_status: str = "All"
    project_id: str | None = None

    @field_validator("base_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("The server URL must start with http:// or https://")
        # Reject a URL that already includes an API path; we build those ourselves
        HttpUrl(value)
        return value


class ConnectionCreate(ConnectionBase):
    password: str = ""


class ConnectionUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    workspace: str | None = None
    username: str | None = None
    password: str | None = None
    verify_ssl: bool | None = None
    is_active: bool | None = None
    sync_enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    export_format: ExportFormat | None = None
    questionnaires: list[str] | None = None
    interview_status: str | None = None
    project_id: str | None = None


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    base_url: str
    workspace: str
    username: str
    verify_ssl: bool
    is_active: bool
    sync_enabled: bool
    sync_interval_minutes: int
    export_format: ExportFormat
    questionnaires: list[str] = Field(default_factory=list)
    interview_status: str
    project_id: str | None = None
    last_sync_at: dt.datetime | None = None
    last_sync_status: SyncStatus
    last_sync_error: str = ""
    server_info: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime
    # Never serialise the stored password; this flag is all the UI needs
    has_password: bool = False


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class QuestionnaireOut(BaseModel):
    id: str
    version: int
    title: str
    variable: str = ""
    identity: str
    last_entry_date: str | None = None


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connection_id: str
    questionnaire: str
    status: SyncStatus
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    rows_imported: int
    datasets_created: int
    message: str = ""
    log: list[Any] = Field(default_factory=list)
    # Whether the export zip is still on disk to be downloaded.
    has_archive: bool = False


class SyncRequest(BaseModel):
    questionnaires: list[str] = Field(default_factory=list)
    interview_status: str | None = None
    # Where the imported datasets land. Absent falls back to the connection's
    # own project, which is how a scheduled sync knows where to put things.
    project_id: str | None = None
    mode: Literal["replace", "append"] = "replace"
