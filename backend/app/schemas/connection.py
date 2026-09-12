from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models.connection import ExportFormat, SyncStatus
from app.services.scheduling import valid_time, valid_timezone

ConnectionProvider = Literal[
    "survey_solutions",
    "odk_central",
    "kobotoolbox",
    "surveycto",
    "csweb",
    "sdmx",
]


class ConnectionBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str
    provider: ConnectionProvider = "survey_solutions"
    source_config: dict[str, Any] = Field(default_factory=dict)
    workspace: str = "primary"
    username: str = ""
    verify_ssl: bool = True
    sync_enabled: bool = False
    sync_interval_minutes: int = Field(default=360, ge=5, le=10080)
    export_format: ExportFormat = ExportFormat.stata
    # Historical name retained in the API for compatibility. For non-Survey
    # Solutions providers these are selected forms/dictionaries/data queries.
    questionnaires: list[str] = Field(default_factory=list)
    interview_status: str = "All"
    project_id: str | None = None
    sync_mode: Literal["interval", "daily"] = "interval"
    sync_times: list[str] = Field(default_factory=list)
    sync_timezone: str = "UTC"

    @field_validator("sync_times")
    @classmethod
    def _validate_times(cls, value: list[str]) -> list[str]:
        cleaned = [text.strip() for text in value if text.strip()]
        for text in cleaned:
            if not valid_time(text):
                raise ValueError(f"'{text}' is not a time of day. Use 24-hour HH:MM, e.g. 06:00")
        return sorted(set(cleaned))

    @field_validator("sync_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        name = value.strip() or "UTC"
        if not valid_timezone(name):
            raise ValueError(f"'{name}' is not a known time zone")
        return name

    @field_validator("base_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("The server URL must start with http:// or https://")
        HttpUrl(value)
        return value


class ConnectionCreate(ConnectionBase):
    # Password, API token or secret depending on provider. It is encrypted at
    # rest and never returned by ConnectionOut.
    password: str = ""


class ConnectionUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    provider: ConnectionProvider | None = None
    source_config: dict[str, Any] | None = None
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
    sync_mode: Literal["interval", "daily"] | None = None
    sync_times: list[str] | None = None
    sync_timezone: str | None = None

    _check_times = field_validator("sync_times")(ConnectionBase._validate_times.__func__)
    _check_zone = field_validator("sync_timezone")(ConnectionBase._validate_timezone.__func__)


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    base_url: str
    provider: ConnectionProvider = "survey_solutions"
    source_config: dict[str, Any] = Field(default_factory=dict)
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
    sync_mode: str = "interval"
    sync_times: list[str] = Field(default_factory=list)
    sync_timezone: str = "UTC"
    last_sync_at: dt.datetime | None = None
    last_sync_status: SyncStatus
    last_sync_error: str = ""
    server_info: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime
    # Never serialise the stored secret; this flag is all the UI needs.
    has_password: bool = False


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class QuestionnaireOut(BaseModel):
    """Backwards-compatible shape for any selectable source resource."""

    id: str
    version: int = 1
    title: str
    variable: str = ""
    identity: str
    last_entry_date: str | None = None
    kind: str = "resource"


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
    has_archive: bool = False


class SyncRequest(BaseModel):
    questionnaires: list[str] = Field(default_factory=list)
    interview_status: str | None = None
    project_id: str | None = None
    mode: Literal["replace", "append"] = "replace"
