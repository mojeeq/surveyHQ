from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.user import Role
from app.services.accounts import validate_username


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    # New clients send identifier so either a username or an email can be used.
    # Keep email for API/backward compatibility with existing integrations.
    identifier: str | None = Field(default=None, min_length=1, max_length=320)
    email: EmailStr | None = None
    password: str

    @model_validator(mode="after")
    def _one_identity(self) -> LoginRequest:
        if not (self.identifier or self.email):
            raise ValueError("A username or email address is required")
        return self

    @property
    def identity(self) -> str:
        return (self.identifier or str(self.email or "")).strip()


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: EmailStr
    full_name: str = Field(default="", max_length=200)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def _valid_username(cls, value: str) -> str:
        return validate_username(value)


class UserBase(BaseModel):
    email: EmailStr
    username: str | None = None
    full_name: str = ""
    role: Role = Role.viewer
    is_active: bool = True
    # Confines this user to the projects they belong to, shutting off the
    # shared area that every user can otherwise see.
    restricted_to_projects: bool = False

    @field_validator("username")
    @classmethod
    def _valid_optional_username(cls, value: str | None) -> str | None:
        return validate_username(value) if value else None


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=32)
    full_name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    restricted_to_projects: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def _valid_username(cls, value: str | None) -> str | None:
        return validate_username(value) if value else None


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # The UI blocks on this: an account whose password someone else chose should
    # not be usable until the holder has set their own.
    must_change_password: bool = False
    created_at: dt.datetime
    last_login_at: dt.datetime | None = None


class UserLookup(BaseModel):
    """The deliberately small public identity returned by exact username lookup."""

    id: str
    username: str
    full_name: str = ""


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ApiKeyCreate(BaseModel):
    name: str = Field(default="", max_length=120)


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str
    created_at: dt.datetime
    last_used_at: dt.datetime | None = None
    revoked: bool


class ApiKeyCreated(ApiKeyOut):
    key: str
