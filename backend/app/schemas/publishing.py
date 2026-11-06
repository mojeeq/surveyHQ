"""What the publishing endpoints take and give back."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

Kind = Literal["github", "sftp", "ftp"]


class TargetIn(BaseModel):
    """A new destination. The secrets go in and never come back out."""

    name: str = Field(min_length=1, max_length=120)
    kind: Kind
    settings: dict[str, Any] = Field(default_factory=dict)
    token: str = Field(default="", max_length=500)
    password: str = Field(default="", max_length=500)
    private_key: str = Field(default="", max_length=20_000)
    passphrase: str = Field(default="", max_length=500)


class TargetPatch(BaseModel):
    """A change to a destination. A secret left out, or left empty, is kept."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    settings: dict[str, Any] | None = None
    token: str = Field(default="", max_length=500)
    password: str = Field(default="", max_length=500)
    private_key: str = Field(default="", max_length=20_000)
    passphrase: str = Field(default="", max_length=500)
    # For a server that was rebuilt: its new key is trusted at the next test.
    forget_host_key: bool = False


class TargetOut(BaseModel):
    id: str
    name: str
    kind: Kind
    # Everything but the SSH host key, which is shown as its fingerprint.
    settings: dict[str, Any]
    # Which secrets are kept - "token", "password", "private_key" - so a form
    # can say "kept, leave blank to keep it" rather than show an empty box.
    secrets: list[str] = Field(default_factory=list)
    host_key_fingerprint: str = ""
    # Where the destination's folder is served, as far as is known before
    # anything is published there.
    folder_url: str = ""
    publications: int = 0
    created_at: dt.datetime | None = None


class CheckOut(BaseModel):
    message: str
    url: str = ""
    notes: list[str] = Field(default_factory=list)
    host_key_fingerprint: str = ""


class PublicationIn(BaseModel):
    target_id: str
    # The folder on the site. Left out, it is the board's name.
    path: str | None = Field(default=None, max_length=200)
    view_id: str = ""
    auto_republish: bool = False
    # Yes to writing over a page this platform did not put there.
    replace_existing: bool = False


class PublicationPatch(BaseModel):
    auto_republish: bool | None = None


class RepublishIn(BaseModel):
    replace_existing: bool = False


class PublicationOut(BaseModel):
    id: str
    dashboard_id: str
    target_id: str
    target_name: str = ""
    target_kind: str = ""
    path: str
    view_id: str = ""
    view_name: str = ""
    auto_republish: bool
    status: str
    url: str = ""
    last_published_at: dt.datetime | None = None
    last_error: str = ""
    size_bytes: int = 0
    notes: list[str] = Field(default_factory=list)
    created_at: dt.datetime | None = None
