from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import Role


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = ""
    role: Role = Role.viewer
    is_active: bool = True
    # Confines this user to the projects they belong to, shutting off the
    # shared area that every user can otherwise see.
    restricted_to_projects: bool = False


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    restricted_to_projects: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # The UI blocks on this: an account whose password someone else chose should
    # not be usable until the holder has set their own.
    must_change_password: bool = False
    created_at: dt.datetime
    last_login_at: dt.datetime | None = None


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
