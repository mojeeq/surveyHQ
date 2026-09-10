from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.project import ProjectStatus
from app.models.user import Role


class ProjectMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    role: Role
    email: str = ""
    full_name: str = ""


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str = ""
    status: ProjectStatus
    starts_on: dt.date | None = None
    ends_on: dt.date | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    # Filled in by the endpoint; the model does not carry counts
    dataset_count: int = 0
    dashboard_count: int = 0
    member_count: int = 0
    # This caller's role over the project, so the UI can hide what they cannot do
    your_role: Role | None = None


class ProjectDetail(ProjectOut):
    members: list[ProjectMemberOut] = Field(default_factory=list)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: ProjectStatus = ProjectStatus.active
    starts_on: dt.date | None = None
    ends_on: dt.date | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: ProjectStatus | None = None
    starts_on: dt.date | None = None
    ends_on: dt.date | None = None


class ProjectMemberIn(BaseModel):
    user_id: str
    role: Role = Role.viewer

    @field_validator("role")
    @classmethod
    def _not_admin(cls, value: Role) -> Role:
        # Administration is global, so there is no administrator of one project.
        # Silently downgrading would be worse than saying so.
        if value is Role.admin:
            raise ValueError(
                "'admin' is a global role, not a project role; use 'manager'"
            )
        return value


class ProjectScriptIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    code: str = ""
    run_on_import: bool = False


class ProjectScriptPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    code: str | None = None
    run_on_import: bool | None = None
    display_order: int | None = None


class ProjectScriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: str = ""
    code: str = ""
    run_on_import: bool = False
    display_order: int = 0
    last_run_at: dt.datetime | None = None
    last_ok: bool = True
    last_output: str = ""
    created_at: dt.datetime
    updated_at: dt.datetime


class RunScriptIn(BaseModel):
    """Code typed into the console and run without being saved."""

    code: str = Field(min_length=1, max_length=200_000)


class AssignProjectIn(BaseModel):
    """Move a dataset or dashboard into a project, or out to the shared area."""

    project_id: str | None = None
