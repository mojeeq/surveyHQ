"""What every kind of destination does, and the settings each one keeps.

A destination is a folder on somebody's web server. Publishing writes files
into it and unpublishing takes them out; that is the whole of what the rest of
the service asks of one, so GitHub, SFTP and FTP each answer the same four
questions in their own way:

- `check`: can this be reached and written to, and at what address?
- `read_head`: the start of a file that is there, or None. Enough to tell a
  page this platform wrote from somebody else's, which is what stops a publish
  writing over a ministry's own front page.
- `apply`: write these files and remove those, as one change where the
  destination can make one.
- `folder_url`: the web address the folder is served at, if known.

Paths handed to a site are relative to the destination's folder and always use
forward slashes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.crypto import decrypt, encrypt
from app.models import PublishKind

# Written into the head of every page this platform publishes, and looked for
# before anything is overwritten or deleted. A page without it is somebody
# else's.
MARKER = '<meta name="generator" content="SurveyHQ">'
_MARKER_SEEN = b'name="generator" content="SurveyHQ'
# How much of an existing file is read to look for the marker. It sits in the
# first few lines of the head; a whole exported page is megabytes.
HEAD_BYTES = 8192


class PublishError(Exception):
    """A publish that could not be done, in words for the person who asked.

    `status` is what the API answers with: 502 when the destination refused or
    could not be reached, 422 when the destination is not set up well enough to
    try, 409 when the address is somebody else's page.
    """

    status = 502

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        if status is not None:
            self.status = status


class AddressTaken(PublishError):
    """There is a page at that address that this platform did not write."""

    status = 409


class NotReady(PublishError):
    """The destination needs something done before it can be used."""

    status = 422


def ours(head: bytes | None) -> bool:
    """Whether a file that is there was written by this platform."""
    return bool(head) and _MARKER_SEEN in (head or b"")


@dataclass
class Check:
    """What testing a destination found."""

    message: str
    url: str = ""
    notes: list[str] = field(default_factory=list)


class Site:
    """One destination, open. Used as a context manager so a connection is
    always closed, however the publish ends."""

    def __enter__(self) -> Site:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:  # pragma: no cover - overridden where it matters
        return None

    def check(self) -> Check:
        raise NotImplementedError

    def read_head(self, rel: str) -> bytes | None:
        raise NotImplementedError

    def apply(self, writes: dict[str, bytes], deletes: list[str], message: str) -> list[str]:
        """Write and remove files. Returns anything worth telling the person."""
        raise NotImplementedError

    def folder_url(self) -> str:
        raise NotImplementedError


# --- settings ---------------------------------------------------------------

_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def clean_path(raw: str, *, what: str = "The address", absolute_ok: bool = False) -> str:
    """A folder path as kept: forward slashes, no empty or climbing segments.

    Letters, digits, dots, dashes and underscores only. A space or a non-ASCII
    letter is a valid file name on most servers and a broken or ugly link in
    most emails, and this is a link that is going into emails.
    """
    text = (raw or "").strip().replace("\\", "/")
    leading = absolute_ok and text.startswith("/")
    parts = [part for part in text.split("/") if part]
    for part in parts:
        if part in (".", ".."):
            raise ValueError(f"{what} cannot contain '.' or '..'")
        if not _SEGMENT.match(part):
            raise ValueError(
                f"{what} can use letters, digits, dots, dashes and underscores, "
                f"with / between folders - '{part}' cannot be used"
            )
    cleaned = "/".join(parts)
    if len(cleaned) > 200:
        raise ValueError(f"{what} can be 200 characters at most")
    return f"/{cleaned}" if leading else cleaned


def _url(raw: Any, what: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if not re.match(r"^https?://[^\s/]+", text):
        raise ValueError(f"{what} has to start with https:// (or http://)")
    return text.rstrip("/") + "/"


def _port(raw: Any, default: int) -> int:
    if raw in (None, ""):
        return default
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise ValueError("The port has to be a number") from None
    if not 1 <= port <= 65535:
        raise ValueError("The port has to be between 1 and 65535")
    return port


def _required(raw: Any, what: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{what} is needed")
    return text


def clean_settings(kind: str, raw: dict[str, Any], kept: dict[str, Any] | None = None) -> dict:
    """The settings for a destination of this kind, checked and tidied.

    `kept` is what the destination had before, for what a form never sends:
    the SSH host key, which is learned by testing rather than typed in.
    """
    raw = raw or {}
    kept = kept or {}
    common = {
        "site_url": _url(raw.get("site_url"), "The web address"),
        "contents_page": bool(raw.get("contents_page")),
    }
    if kind == PublishKind.github.value:
        owner = _required(raw.get("owner"), "The GitHub account or organisation")
        repo = _required(raw.get("repo"), "The repository")
        if not re.match(r"^[A-Za-z0-9-]+$", owner):
            raise ValueError("A GitHub account name is letters, digits and dashes")
        if not re.match(r"^[A-Za-z0-9._-]+$", repo):
            raise ValueError("A repository name is letters, digits, dots, dashes and underscores")
        branch = str(raw.get("branch") or "gh-pages").strip()
        if not re.match(r"^[A-Za-z0-9._/-]+$", branch) or ".." in branch:
            raise ValueError("That is not a branch name GitHub accepts")
        same_repo = (owner, repo) == (kept.get("owner"), kept.get("repo"))
        return {
            **common,
            "owner": owner,
            "repo": repo,
            # Learned from GitHub at a publish or a test. Another repository
            # is another site.
            "pages_url": str(kept.get("pages_url") or "") if same_repo else "",
            "branch": branch,
            "folder": clean_path(raw.get("folder", ""), what="The folder"),
            # Changed only for GitHub Enterprise Server, which serves the same
            # API at an address of its own.
            "api_url": (_url(raw.get("api_url"), "The API address") or "https://api.github.com/"),
        }
    if kind == PublishKind.sftp.value:
        auth = str(raw.get("auth") or "password")
        if auth not in ("password", "key"):
            raise ValueError("Sign in with a password or with a key")
        host = _required(raw.get("host"), "The server")
        changed_host = host != kept.get("host") or _port(raw.get("port"), 22) != kept.get("port")
        return {
            **common,
            "host": host,
            "port": _port(raw.get("port"), 22),
            "username": _required(raw.get("username"), "The user name"),
            "folder": clean_path(raw.get("folder", ""), what="The folder", absolute_ok=True),
            "auth": auth,
            # Learned from the server the first time the destination is tested,
            # and checked on every connection after. A different server - which
            # is what a new host name or port is - has to be trusted again.
            "host_key": "" if changed_host else str(kept.get("host_key") or ""),
        }
    if kind == PublishKind.ftp.value:
        return {
            **common,
            "host": _required(raw.get("host"), "The server"),
            "port": _port(raw.get("port"), 21),
            "username": _required(raw.get("username"), "The user name"),
            "folder": clean_path(raw.get("folder", ""), what="The folder", absolute_ok=True),
            # Encrypted unless somebody says otherwise: plain FTP sends the
            # password across the internet as it is typed.
            "tls": raw.get("tls") is None or bool(raw.get("tls")),
            # Checked unless somebody says otherwise, for the same reason.
            "verify_tls": raw.get("verify_tls") is None or bool(raw.get("verify_tls")),
        }
    raise ValueError(f"'{kind}' is not a kind of destination this platform knows")


SECRET_KEYS = ("token", "password", "private_key", "passphrase")


def seal(secret: dict[str, str]) -> str:
    """The secret, encrypted for keeping. Empty values are left out."""
    kept = {key: value for key, value in secret.items() if value}
    return encrypt(json.dumps(kept)) if kept else ""


def unseal(sealed: str) -> dict[str, str]:
    if not sealed:
        return {}
    try:
        value = json.loads(decrypt(sealed))
    except ValueError as exc:
        raise NotReady(str(exc)) from None
    return value if isinstance(value, dict) else {}


def page_file(path: str) -> str:
    """Where a publication's page goes: a folder of its own, so its address
    ends in a slash and the file name never shows."""
    return f"{path}/index.html" if path else "index.html"


def join_url(base: str, path: str) -> str:
    if not base:
        return ""
    return base.rstrip("/") + "/" + (f"{path}/" if path else "")


def known_folder_url(target: Any) -> str:
    """Where a destination's folder is served, without asking the server."""
    from app.services.publishing import github

    settings = dict(target.settings or {})
    if target.kind == PublishKind.github.value:
        return github.folder_url(settings)
    return str(settings.get("site_url") or "")


def open_site(target: Any, *, trust_new_host_key: bool = False) -> Site:
    """The destination, ready to use."""
    from app.services.publishing import ftp, github, sftp

    secret = unseal(target.secret_encrypted)
    settings = dict(target.settings or {})
    if target.kind == PublishKind.github.value:
        return github.GitHubSite(settings, secret)
    if target.kind == PublishKind.sftp.value:
        return sftp.SftpSite(settings, secret, trust_new_host_key=trust_new_host_key)
    if target.kind == PublishKind.ftp.value:
        return ftp.FtpSite(settings, secret)
    raise NotReady(f"'{target.kind}' is not a kind of destination this platform knows")
