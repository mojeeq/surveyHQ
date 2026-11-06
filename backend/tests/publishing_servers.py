"""Stand-ins for the places dashboards are published to.

GitHub is faked at its API, with enough of a git repository behind it - blobs,
trees, commits, branches - that a publish is checked by what ends up on the
branch, not by which calls were made. SFTP and FTP are real servers, run in
this process on a free port and writing into a temporary folder, because the
part of those worth testing is the conversation with a server: the temporary
name and the rename, the folders made on the way, the host key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import socket
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import paramiko
import respx

# --- GitHub -------------------------------------------------------------------

GOOD_TOKEN = "github-token-for-tests"


def _sha(value: Any) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class FakeGitHub:
    """One repository on a GitHub that keeps its state between calls."""

    def __init__(
        self,
        owner: str = "statsoffice",
        repo: str = "dashboards",
        *,
        empty: bool = False,
        can_push: bool = True,
        token_can_write: bool = True,
        can_enable_pages: bool = True,
        can_read_pages: bool = True,
    ) -> None:
        self.owner, self.repo = owner, repo
        self.can_push = can_push
        # A fine-grained token with Contents only readable, or without this
        # repository: GitHub still reports the account's own permissions on
        # the repository, and refuses the writes.
        self.token_can_write = token_can_write
        self.can_enable_pages = can_enable_pages
        self.can_read_pages = can_read_pages
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, dict[str, str]] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        self.refs: dict[str, str] = {}
        self.pages: dict[str, Any] | None = None
        self.calls: list[str] = []
        if not empty:
            # A repository with a README on main, as one made on GitHub's site is.
            self._commit_files("main", {"README.md": b"# Dashboards\n"}, "Initial commit")

    # What is on a branch, for the tests to read.
    def files(self, branch: str = "gh-pages") -> dict[str, bytes]:
        sha = self.refs.get(branch)
        if sha is None:
            return {}
        tree = self.trees[self.commits[sha]["tree"]]
        return {path: self.blobs[blob] for path, blob in tree.items()}

    def put_file(self, branch: str, path: str, body: bytes) -> None:
        """Somebody else's commit, made on GitHub's site."""
        current = dict(self.files(branch))
        current[path] = body
        self._commit_files(branch, current, "Edited on GitHub")

    def _commit_files(self, branch: str, files: dict[str, bytes], message: str) -> None:
        tree: dict[str, str] = {}
        for path, body in files.items():
            blob = hashlib.sha1(body).hexdigest()
            self.blobs[blob] = body
            tree[path] = blob
        tree_sha = _sha(tree)
        self.trees[tree_sha] = tree
        parent = self.refs.get(branch)
        commit = {"tree": tree_sha, "parents": [parent] if parent else [], "message": message}
        commit_sha = _sha([commit, len(self.commits)])
        self.commits[commit_sha] = commit
        self.refs[branch] = commit_sha

    # --- the API ---------------------------------------------------------------

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        if request.headers.get("authorization") != f"Bearer {GOOD_TOKEN}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        prefix = f"/repos/{self.owner}/{self.repo}"
        path = unquote(request.url.path)
        if not path.startswith(prefix):
            return httpx.Response(404, json={"message": "Not Found"})
        rest = path[len(prefix):]
        body = json.loads(request.content) if request.content else {}
        method = request.method

        if rest == "" and method == "GET":
            return httpx.Response(
                200,
                json={
                    "full_name": f"{self.owner}/{self.repo}",
                    "private": False,
                    "permissions": {"pull": True, "push": self.can_push, "admin": False},
                },
            )
        if rest.startswith("/git/ref/heads/") and method == "GET":
            branch = rest[len("/git/ref/heads/"):]
            if not self.refs:
                return httpx.Response(409, json={"message": "Git Repository is empty."})
            if branch not in self.refs:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"object": {"sha": self.refs[branch]}})
        if rest.startswith("/git/commits/") and method == "GET":
            commit = self.commits.get(rest[len("/git/commits/"):])
            if commit is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"tree": {"sha": commit["tree"]}})
        if not (self.can_push and self.token_can_write) and method in ("POST", "PATCH", "PUT"):
            return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})
        if rest == "/git/blobs" and method == "POST":
            data = base64.b64decode(body["content"])
            sha = hashlib.sha1(data).hexdigest()
            self.blobs[sha] = data
            return httpx.Response(201, json={"sha": sha})
        if rest == "/git/trees" and method == "POST":
            tree = dict(self.trees[body["base_tree"]]) if body.get("base_tree") else {}
            for entry in body["tree"]:
                if entry["sha"] is None:
                    if entry["path"] not in tree:
                        return httpx.Response(422, json={"message": "path not in tree"})
                    del tree[entry["path"]]
                else:
                    tree[entry["path"]] = entry["sha"]
            sha = _sha(tree)
            self.trees[sha] = tree
            return httpx.Response(201, json={"sha": sha})
        if rest == "/git/commits" and method == "POST":
            commit = {"tree": body["tree"], "parents": body["parents"], "message": body["message"]}
            sha = _sha([commit, len(self.commits)])
            self.commits[sha] = commit
            return httpx.Response(201, json={"sha": sha})
        if rest.startswith("/git/refs/heads/") and method == "PATCH":
            branch = rest[len("/git/refs/heads/"):]
            parents = self.commits[body["sha"]]["parents"]
            if self.refs.get(branch) not in parents:
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            self.refs[branch] = body["sha"]
            return httpx.Response(200, json={"object": {"sha": body["sha"]}})
        if rest == "/git/refs" and method == "POST":
            branch = body["ref"][len("refs/heads/"):]
            if branch in self.refs:
                return httpx.Response(422, json={"message": "Reference already exists"})
            self.refs[branch] = body["sha"]
            return httpx.Response(201, json={"object": {"sha": body["sha"]}})
        if rest.startswith("/contents/") and method == "GET":
            branch = request.url.params.get("ref") or "main"
            found = self.files(branch).get(rest[len("/contents/"):])
            if found is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, content=found)
        if rest.startswith("/contents/") and method == "PUT":
            branch = body.get("branch") or "main"
            self._commit_files(
                branch,
                {**self.files(branch), rest[len("/contents/"):]: base64.b64decode(body["content"])},
                body["message"],
            )
            return httpx.Response(201, json={"content": {}})
        if rest == "/pages" and not self.can_read_pages:
            return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})
        if rest == "/pages" and method == "GET":
            if self.pages is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json=self.pages)
        if rest == "/pages" and method == "POST":
            if not self.can_enable_pages:
                return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})
            self.pages = {
                "html_url": f"https://{self.owner}.github.io/{self.repo}/",
                "build_type": "legacy",
                "source": body["source"],
            }
            return httpx.Response(201, json=self.pages)
        return httpx.Response(404, json={"message": f"Not faked: {method} {rest}"})


def mock_github(fake: FakeGitHub) -> respx.MockRouter:
    router = respx.mock(assert_all_called=False)
    router.route(host="api.github.com").mock(side_effect=fake)
    return router


# --- SFTP ---------------------------------------------------------------------

SFTP_USER = "web"
SFTP_PASSWORD = "sftp-password-for-tests"


class _Server(paramiko.ServerInterface):
    def __init__(self, client_key: paramiko.PKey | None) -> None:
        self.client_key = client_key

    def check_auth_password(self, username: str, password: str) -> int:
        if (username, password) == (SFTP_USER, SFTP_PASSWORD):
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        if self.client_key is not None and key.get_base64() == self.client_key.get_base64():
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return "password,publickey"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return paramiko.OPEN_SUCCEEDED


class _Handle(paramiko.SFTPHandle):
    def stat(self) -> Any:
        try:
            return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)

    def chattr(self, attr: Any) -> int:
        try:
            paramiko.SFTPServer.set_file_attr(self.filename, attr)
            return paramiko.SFTP_OK
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)


class _Folder(paramiko.SFTPServerInterface):
    """An SFTP server whose whole world is one folder."""

    def __init__(self, server: Any, root: str) -> None:
        super().__init__(server)
        self.root = root

    def _real(self, path: str) -> str:
        return self.root + self.canonicalize(path)

    def _errno(self, call: Any) -> Any:
        try:
            call()
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)
        return paramiko.SFTP_OK

    def list_folder(self, path: str) -> Any:
        real = self._real(path)
        try:
            return [
                paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(real, name)), name)
                for name in os.listdir(real)
            ]
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)

    def stat(self, path: str) -> Any:
        try:
            return paramiko.SFTPAttributes.from_stat(os.stat(self._real(path)))
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)

    lstat = stat

    def open(self, path: str, flags: int, attr: Any) -> Any:
        real = self._real(path)
        try:
            fd = os.open(real, flags, 0o666)
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)
        if flags & os.O_WRONLY:
            mode = "ab" if flags & os.O_APPEND else "wb"
        elif flags & os.O_RDWR:
            mode = "a+b" if flags & os.O_APPEND else "r+b"
        else:
            mode = "rb"
        handle = _Handle(flags)
        handle.filename = real
        handle.readfile = handle.writefile = os.fdopen(fd, mode)
        return handle

    def remove(self, path: str) -> int:
        return self._errno(lambda: os.remove(self._real(path)))

    def rename(self, oldpath: str, newpath: str) -> int:
        def move() -> None:
            if os.path.exists(self._real(newpath)):
                raise FileExistsError(17, "exists")
            os.rename(self._real(oldpath), self._real(newpath))

        return self._errno(move)

    def posix_rename(self, oldpath: str, newpath: str) -> int:
        return self._errno(lambda: os.replace(self._real(oldpath), self._real(newpath)))

    def mkdir(self, path: str, attr: Any) -> int:
        return self._errno(lambda: os.mkdir(self._real(path)))

    def rmdir(self, path: str) -> int:
        return self._errno(lambda: os.rmdir(self._real(path)))

    def chattr(self, path: str, attr: Any) -> int:
        return self._errno(lambda: paramiko.SFTPServer.set_file_attr(self._real(path), attr))


class SftpServer:
    """A real SFTP server on a free port, serving `root`."""

    def __init__(self, root: Path, client_key: paramiko.PKey | None = None) -> None:
        self.root = root
        self.host_key = paramiko.ECDSAKey.generate()
        self.client_key = client_key
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.transports: list[paramiko.Transport] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def host_key_line(self) -> str:
        return f"{self.host_key.get_name()} {self.host_key.get_base64()}"

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            transport = paramiko.Transport(conn)
            transport.add_server_key(self.host_key)
            transport.set_subsystem_handler("sftp", paramiko.SFTPServer, _Folder, str(self.root))
            try:
                transport.start_server(server=_Server(self.client_key))
            except (EOFError, OSError, paramiko.SSHException):
                transport.close()
                continue
            self.transports.append(transport)

    def stop(self) -> None:
        self.sock.close()
        for transport in self.transports:
            transport.close()


# --- FTP ----------------------------------------------------------------------

FTP_USER = "web"
FTP_PASSWORD = "ftp-password-for-tests"


class FtpServer:
    """A real FTP server on a free port, serving `root`."""

    def __init__(self, root: Path) -> None:
        from pyftpdlib.authorizers import DummyAuthorizer
        from pyftpdlib.handlers import FTPHandler
        from pyftpdlib.servers import ThreadedFTPServer

        logging.getLogger("pyftpdlib").setLevel(logging.WARNING)
        authorizer = DummyAuthorizer()
        authorizer.add_user(FTP_USER, FTP_PASSWORD, str(root), perm="elradfmwMT")
        handler = type("Handler", (FTPHandler,), {"authorizer": authorizer, "banner": "ready"})
        self.server = ThreadedFTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"handle_exit": False}, daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.server.close_all()
