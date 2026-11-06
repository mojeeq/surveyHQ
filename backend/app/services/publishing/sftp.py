"""Publishing to a web server over SFTP.

The commonest "our own web server": a Linux machine running nginx or Apache,
reached over SSH, with a folder the web server serves. The page is written
into that folder, under a temporary name first and then renamed over the old
one, so a reader never opens a half-written file.

The server's identity is checked on every connection. Its key is learned the
first time the destination is tested - and shown, so whoever set it up can
compare it with the server's - and any later connection to a machine with a
different key is refused. Otherwise anything able to answer for the host name
could collect the password and be sent the board.
"""

from __future__ import annotations

import base64
import contextlib
import errno
import hashlib
import io
import posixpath
import socket
from typing import Any

import paramiko

from app.services.publishing.sites import (
    HEAD_BYTES,
    Check,
    NotReady,
    PublishError,
    Site,
)

# A file written to check the folder can be written to, and removed at once.
PROBE = ".surveyhq-check"


def fingerprint(key_line: str) -> str:
    """A host key as OpenSSH shows it: SHA256 of the key, in base64."""
    try:
        raw = base64.b64decode(key_line.split()[1])
    except (IndexError, ValueError):
        return ""
    digest = base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii").rstrip("=")
    return f"SHA256:{digest}"


def load_key(text: str, passphrase: str = "") -> paramiko.PKey:
    """A private key pasted as text, whichever of the usual kinds it is."""
    problem = ""
    for kind in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return kind.from_private_key(
                io.StringIO(text.strip() + "\n"), password=passphrase or None
            )
        except paramiko.PasswordRequiredException:
            raise NotReady(
                "The private key is protected by a passphrase. Add it to the destination."
            ) from None
        except (paramiko.SSHException, ValueError) as exc:
            problem = str(exc)
    raise NotReady(
        "The private key could not be read. Paste the whole key, from its "
        f"-----BEGIN line to its -----END line{f' ({problem})' if problem else ''}."
    )


def _missing(exc: OSError) -> bool:
    return isinstance(exc, FileNotFoundError) or getattr(exc, "errno", None) == errno.ENOENT


class SftpSite(Site):
    def __init__(
        self,
        settings: dict[str, Any],
        secret: dict[str, str],
        *,
        trust_new_host_key: bool = False,
    ) -> None:
        self.host = settings.get("host", "")
        self.port = int(settings.get("port") or 22)
        self.username = settings.get("username", "")
        self.folder = settings.get("folder") or ""
        self.site_url = settings.get("site_url") or ""
        self.auth = settings.get("auth") or "password"
        self.host_key = settings.get("host_key") or ""
        self.secret = secret
        self.trust_new = trust_new_host_key
        # Set when a test trusted the server for the first time, for the caller
        # to keep on the destination.
        self.learned_host_key = ""
        self.transport: paramiko.Transport | None = None
        self.client: paramiko.SFTPClient | None = None

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        if self.transport is not None:
            self.transport.close()

    def _open(self) -> paramiko.SFTPClient:
        if self.client is not None:
            return self.client
        where = f"{self.host}:{self.port}"
        try:
            sock = socket.create_connection((self.host, self.port), timeout=20)
            transport = paramiko.Transport(sock)
            transport.start_client(timeout=20)
        except (OSError, paramiko.SSHException, EOFError) as exc:
            raise PublishError(f"{where} could not be reached over SSH: {exc}") from None
        self.transport = transport

        key = transport.get_remote_server_key()
        seen = f"{key.get_name()} {key.get_base64()}"
        if self.host_key and seen != self.host_key:
            raise NotReady(
                f"The server at {self.host} is not the one that was trusted: its key is now "
                f"{fingerprint(seen)}, where it was {fingerprint(self.host_key)}. If the "
                "server was rebuilt, clear its trusted key on the destination and test it "
                "again. If it was not, do not publish to it."
            )
        if not self.host_key:
            if not self.trust_new:
                raise NotReady(
                    "Test this destination first, so that the server's identity can be "
                    "checked and trusted."
                )
            self.learned_host_key = seen

        try:
            if self.auth == "key":
                private = self.secret.get("private_key") or ""
                if not private:
                    raise NotReady("This destination has no private key. Edit it and add one.")
                transport.auth_publickey(
                    self.username, load_key(private, self.secret.get("passphrase") or "")
                )
            else:
                password = self.secret.get("password") or ""
                if not password:
                    raise NotReady("This destination has no password. Edit it and add one.")
                transport.auth_password(self.username, password)
        except paramiko.BadAuthenticationType as exc:
            raise NotReady(
                f"{self.host} does not take that way of signing in; it allows "
                f"{', '.join(exc.allowed_types) or 'none'}."
            ) from None
        except paramiko.AuthenticationException:
            what = "key" if self.auth == "key" else "password"
            raise NotReady(f"{self.host} refused the user name and {what}.") from None
        except (paramiko.SSHException, OSError, EOFError) as exc:
            raise PublishError(f"Signing in to {where} failed: {exc}") from None

        client = paramiko.SFTPClient.from_transport(transport)
        if client is None:  # pragma: no cover - paramiko returns None only on a closed transport
            raise PublishError(f"{where} would not open an SFTP session.")
        client.get_channel().settimeout(60)
        self.client = client
        return client

    def _full(self, rel: str) -> str:
        return posixpath.join(self.folder, rel) if self.folder else rel

    def _mkdirs(self, folder: str) -> None:
        client = self._open()
        built = "/" if folder.startswith("/") else ""
        for part in [one for one in folder.split("/") if one]:
            built = posixpath.join(built, part) if built else part
            try:
                client.stat(built)
            except OSError as exc:
                if not _missing(exc):
                    raise PublishError(f"Could not look at {built} on {self.host}: {exc}") from None
                try:
                    client.mkdir(built)
                except OSError as made:
                    raise PublishError(
                        f"Could not make the folder {built} on {self.host}: {made}"
                    ) from None

    def _write(self, full: str, body: bytes) -> None:
        client = self._open()
        parent = posixpath.dirname(full)
        if parent:
            self._mkdirs(parent)
        temp = f"{full}.surveyhq-upload"
        try:
            with client.open(temp, "wb") as handle:
                handle.set_pipelined(True)
                handle.write(body)
            try:
                # Over the old file in one step, where the server can.
                client.posix_rename(temp, full)
            except OSError:
                with contextlib.suppress(OSError):
                    client.remove(full)
                client.rename(temp, full)
            # Readable by the web server whatever the account's umask.
            with contextlib.suppress(OSError):
                client.chmod(full, 0o644)
        except OSError as exc:
            raise PublishError(f"Could not write {full} on {self.host}: {exc}") from None

    # --- the site ------------------------------------------------------------

    def check(self) -> Check:
        self._open()
        if self.folder:
            self._mkdirs(self.folder)
        probe = self._full(PROBE)
        self._write(probe, b"SurveyHQ can write here\n")
        with contextlib.suppress(OSError):
            self._open().remove(probe)
        notes: list[str] = []
        if self.learned_host_key:
            notes.append(
                f"Trusted the server's key, {fingerprint(self.learned_host_key)}. Compare it "
                "with the server's own if you can: every later connection is checked against it."
            )
        if not self.site_url:
            notes.append(
                "Add the web address this folder is served at, so published dashboards get a link."
            )
        return Check(
            message=(
                f"Connected to {self.host} as {self.username}, and can write to "
                f"{self.folder or 'the folder it signs in to'}."
            ),
            url=self.folder_url(),
            notes=notes,
        )

    def read_head(self, rel: str) -> bytes | None:
        client = self._open()
        try:
            with client.open(self._full(rel), "rb") as handle:
                return handle.read(HEAD_BYTES)
        except OSError as exc:
            if _missing(exc):
                return None
            raise PublishError(f"Could not read {self._full(rel)} on {self.host}: {exc}") from None

    def apply(self, writes: dict[str, bytes], deletes: list[str], message: str) -> list[str]:
        for rel, body in writes.items():
            self._write(self._full(rel), body)
        client = self._open()
        for rel in deletes:
            full = self._full(rel)
            try:
                client.remove(full)
            except OSError as exc:
                if not _missing(exc):
                    raise PublishError(f"Could not remove {full} on {self.host}: {exc}") from None
            if "/" in rel:
                # The page's own folder, now empty. Left where anything else
                # is still in it.
                with contextlib.suppress(OSError):
                    client.rmdir(posixpath.dirname(full))
        return []

    def folder_url(self) -> str:
        return self.site_url
