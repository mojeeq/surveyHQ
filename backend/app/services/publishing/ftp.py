"""Publishing to a web host over FTP.

What most shared hosting offers - cPanel and its kind - and often the only way
into a ministry's existing website. Encrypted (explicit FTPS) unless somebody
turns it off, because plain FTP sends the password across the internet as it
was typed. The certificate is checked too, unless the destination says not to:
a shared host's certificate is often for the hosting company's server name
rather than the one people type, and the answer then is that name.
"""

from __future__ import annotations

import contextlib
import ftplib
import io
import posixpath
import ssl
from typing import Any

from app.services.publishing.sites import (
    HEAD_BYTES,
    Check,
    NotReady,
    PublishError,
    Site,
)

PROBE = ".surveyhq-check"


def _code(exc: BaseException) -> str:
    return str(exc)[:3]


class FtpSite(Site):
    def __init__(self, settings: dict[str, Any], secret: dict[str, str]) -> None:
        self.host = settings.get("host", "")
        self.port = int(settings.get("port") or 21)
        self.username = settings.get("username", "")
        self.folder = settings.get("folder") or ""
        self.site_url = settings.get("site_url") or ""
        self.tls = settings.get("tls", True) is not False
        self.verify = settings.get("verify_tls", True) is not False
        self.password = secret.get("password") or ""
        if not self.password:
            raise NotReady("This destination has no password. Edit it and add one.")
        self.ftp: ftplib.FTP | None = None

    def close(self) -> None:
        if self.ftp is None:
            return
        try:
            self.ftp.quit()
        except (*ftplib.all_errors, EOFError):
            self.ftp.close()

    def _open(self) -> ftplib.FTP:
        if self.ftp is not None:
            return self.ftp
        where = f"{self.host}:{self.port}"
        if self.tls:
            context = ssl.create_default_context()
            if not self.verify:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            ftp: ftplib.FTP = ftplib.FTP_TLS(context=context, timeout=30)
        else:
            ftp = ftplib.FTP(timeout=30)
        try:
            ftp.connect(self.host, self.port)
            ftp.login(self.username, self.password)
            if isinstance(ftp, ftplib.FTP_TLS):
                # The files as well as the password.
                ftp.prot_p()
        except ssl.SSLCertVerificationError as exc:
            ftp.close()
            raise NotReady(
                f"{self.host}'s certificate could not be trusted ({exc.verify_message}). Use "
                "the server name the certificate is for - often the hosting company's - or, "
                "if you know the server, turn off certificate checking on the destination."
            ) from None
        except ssl.SSLError as exc:
            ftp.close()
            raise NotReady(
                f"{self.host} would not make an encrypted connection ({exc}). If it only "
                "speaks plain FTP, turn encryption off on the destination - knowing that "
                "the password then crosses the network as it was typed."
            ) from None
        except ftplib.error_perm as exc:
            ftp.close()
            if _code(exc) == "530":
                raise NotReady(f"{self.host} refused the user name and password.") from None
            raise PublishError(f"{where} refused the connection: {exc}") from None
        except (*ftplib.all_errors, EOFError) as exc:
            ftp.close()
            raise PublishError(f"{where} could not be reached over FTP: {exc}") from None
        ftp.set_pasv(True)
        self.ftp = ftp
        return ftp

    def _full(self, rel: str) -> str:
        return posixpath.join(self.folder, rel) if self.folder else rel

    def _mkdirs(self, folder: str) -> None:
        ftp = self._open()
        built = "/" if folder.startswith("/") else ""
        for part in [one for one in folder.split("/") if one]:
            built = posixpath.join(built, part) if built else part
            try:
                ftp.mkd(built)
            except ftplib.error_perm:
                # 550: there already, most often. When it is a refusal
                # instead, the write into it says so in words.
                pass
            except (*ftplib.all_errors, EOFError) as exc:
                raise PublishError(f"Could not make the folder {built}: {exc}") from None

    def _write(self, full: str, body: bytes) -> None:
        ftp = self._open()
        parent = posixpath.dirname(full)
        if parent:
            self._mkdirs(parent)
        temp = f"{full}.surveyhq-upload"
        try:
            ftp.storbinary(f"STOR {temp}", io.BytesIO(body))
            with contextlib.suppress(ftplib.error_perm):
                ftp.delete(full)
            ftp.rename(temp, full)
        except (*ftplib.all_errors, EOFError) as exc:
            raise PublishError(f"Could not write {full} on {self.host}: {exc}") from None

    # --- the site ------------------------------------------------------------

    def check(self) -> Check:
        ftp = self._open()
        if self.folder:
            self._mkdirs(self.folder)
        probe = self._full(PROBE)
        self._write(probe, b"SurveyHQ can write here\n")
        try:
            ftp.delete(probe)
        except (*ftplib.all_errors, EOFError):
            pass
        notes: list[str] = []
        if not self.tls:
            notes.append(
                "This destination uses plain FTP, so the password and the pages cross the "
                "network unencrypted. Turn encryption on if the server allows it."
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
        ftp = self._open()
        full = self._full(rel)
        try:
            ftp.voidcmd("TYPE I")
            conn = ftp.transfercmd(f"RETR {full}")
        except ftplib.error_perm as exc:
            if _code(exc) == "550":
                return None
            raise PublishError(f"Could not read {full} on {self.host}: {exc}") from None
        except (*ftplib.all_errors, EOFError) as exc:
            raise PublishError(f"Could not read {full} on {self.host}: {exc}") from None
        data = b""
        try:
            # The start of the file only: whether this platform wrote it is
            # said in its first lines, and the rest can be megabytes.
            while len(data) < HEAD_BYTES:
                chunk = conn.recv(HEAD_BYTES - len(data))
                if not chunk:
                    break
                data += chunk
        finally:
            conn.close()
        try:
            ftp.voidresp()
        except (*ftplib.all_errors, EOFError):
            # 426, for a transfer cut short on purpose.
            pass
        return data

    def apply(self, writes: dict[str, bytes], deletes: list[str], message: str) -> list[str]:
        for rel, body in writes.items():
            self._write(self._full(rel), body)
        ftp = self._open()
        for rel in deletes:
            full = self._full(rel)
            try:
                ftp.delete(full)
            except ftplib.error_perm as exc:
                if _code(exc) != "550":
                    raise PublishError(f"Could not remove {full} on {self.host}: {exc}") from None
            except (*ftplib.all_errors, EOFError) as exc:
                raise PublishError(f"Could not remove {full} on {self.host}: {exc}") from None
            if "/" in rel:
                try:
                    ftp.rmd(posixpath.dirname(full))
                except (*ftplib.all_errors, EOFError):
                    pass
        return []

    def folder_url(self) -> str:
        return self.site_url
