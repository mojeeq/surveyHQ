"""Publishing to GitHub Pages.

The page is committed to a branch of a repository - `gh-pages` unless told
otherwise - and GitHub Pages serves that branch as a website. Nothing is
cloned: the files go up through GitHub's Git Data API, which writes a blob per
file, a tree, a commit and a branch update. That makes a publish one commit
however many files it touches, so the dashboard and the site's contents page
never disagree, and it handles files up to 100 MB where the simpler "put a
file" call stops far sooner.

The token is a fine-grained personal access token with "Contents: Read and
write" on the one repository, and "Pages: Read and write" if it should switch
GitHub Pages on by itself. A classic token with the `repo` scope also works.
"""

from __future__ import annotations

import base64
import posixpath
from typing import Any
from urllib.parse import quote

import httpx

from app.services.publishing.sites import (
    HEAD_BYTES,
    Check,
    NotReady,
    PublishError,
    Site,
)

_CANNOT_SEE_PAGES = (
    "This token may not read the repository's GitHub Pages settings, so whether Pages "
    "serves the {branch} branch could not be checked. If it does, the page will appear; "
    "give the token 'Pages: Read and write' to have this checked and switched on for you."
)

# A branch that does not exist yet is started with this beside the pages:
# without it GitHub runs the branch through Jekyll, which takes longer and
# drops any file or folder whose name starts with an underscore.
NO_JEKYLL = ".nojekyll"


def default_url(owner: str, repo: str, api_url: str) -> str:
    """Where GitHub serves a project's Pages site, before it has said so.

    Only for github.com: an Enterprise server serves Pages at an address of
    its own, which the Pages API gives once Pages is on.
    """
    if "api.github.com" not in api_url:
        return ""
    lowered = owner.lower()
    if repo.lower() == f"{lowered}.github.io":
        return f"https://{lowered}.github.io/"
    return f"https://{lowered}.github.io/{repo}/"


def folder_url(settings: dict[str, Any], pages_url: str = "") -> str:
    """The address of the destination's folder, from what is known."""
    base = (
        settings.get("site_url")
        or pages_url
        or settings.get("pages_url")
        or default_url(
            settings.get("owner", ""),
            settings.get("repo", ""),
            settings.get("api_url") or "https://api.github.com/",
        )
    )
    if not base:
        return ""
    folder = settings.get("folder") or ""
    return base.rstrip("/") + "/" + (f"{folder}/" if folder else "")


class _Empty:
    """The repository has no commits at all."""


class _Unknown:
    """This token may not see the repository's Pages settings."""


class _Moved(Exception):
    """The branch moved between reading it and updating it."""


class GitHubSite(Site):
    def __init__(self, settings: dict[str, Any], secret: dict[str, str]) -> None:
        self.owner = settings.get("owner", "")
        self.repo = settings.get("repo", "")
        self.branch = settings.get("branch") or "gh-pages"
        self.folder = settings.get("folder") or ""
        self.api_url = settings.get("api_url") or "https://api.github.com/"
        self.site_url = settings.get("site_url") or ""
        token = secret.get("token") or ""
        if not token:
            raise NotReady("This destination has no GitHub token. Edit it and add one.")
        self.settings = settings
        self.client = httpx.Client(
            base_url=self.api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "SurveyHQ",
            },
            timeout=httpx.Timeout(60.0, connect=15.0),
            follow_redirects=True,
        )
        # What GitHub said the Pages site's address is, once it has said; kept
        # on the destination so the next publish knows it without asking.
        self.pages_url = settings.get("pages_url") or ""

    def close(self) -> None:
        self.client.close()

    # --- talking to GitHub ---------------------------------------------------

    @property
    def _repo_path(self) -> str:
        return f"/repos/{self.owner}/{self.repo}"

    def _full(self, rel: str) -> str:
        return posixpath.join(self.folder, rel) if self.folder else rel

    def _call(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise PublishError(f"GitHub could not be reached: {exc}") from None

    def _fail(self, response: httpx.Response, doing: str) -> PublishError:
        try:
            said = str(response.json().get("message") or "")
        except ValueError:
            said = response.text[:200]
        where = f"{self.owner}/{self.repo}"
        if response.status_code == 401:
            return NotReady(
                "GitHub refused the token: it is wrong, has expired or was revoked. "
                "Make a new one and put it on the destination."
            )
        if response.status_code == 404:
            return NotReady(f"GitHub has no repository {where}, or this token cannot see it.")
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            return PublishError(
                "GitHub's rate limit for this token is used up. Try again in an hour."
            )
        if response.status_code == 403:
            return NotReady(
                f"GitHub would not let this token {doing} ({said}). A fine-grained token "
                f"needs 'Contents: Read and write' on {where}."
            )
        return PublishError(f"GitHub refused to {doing}: {said or response.status_code}")

    def _json(self, response: httpx.Response, doing: str, ok: tuple[int, ...] = (200, 201)) -> Any:
        if response.status_code not in ok:
            raise self._fail(response, doing)
        return response.json()

    # --- the site ------------------------------------------------------------

    def check(self) -> Check:
        info = self._json(self._call("GET", self._repo_path), "read the repository")
        permissions = info.get("permissions") or {}
        if permissions and not any(
            permissions.get(level) for level in ("push", "maintain", "admin")
        ):
            raise NotReady(
                f"This token can read {self.owner}/{self.repo} but not write to it. Give "
                "it 'Contents: Read and write' on this repository."
            )
        notes: list[str] = []
        if info.get("private"):
            notes.append(
                "The repository is private, but a GitHub Pages site is public: anyone with "
                "the address can open what is published there."
            )
        pages = self._pages()
        if pages is _Unknown:
            notes.append(_CANNOT_SEE_PAGES.format(branch=self.branch))
        elif pages is None:
            notes.append(
                "GitHub Pages is not switched on for this repository yet. The first publish "
                "switches it on if the token may; otherwise switch it on under Settings, "
                f"Pages: Deploy from a branch, {self.branch}, / (root)."
            )
        else:
            notes.extend(self._pages_mismatch(pages))
        where = f" in {self.folder}/" if self.folder else ""
        return Check(
            message=(
                f"Connected to {self.owner}/{self.repo}. Pages will be committed to the "
                f"{self.branch} branch{where}."
            ),
            url=self.folder_url(),
            notes=notes,
        )

    def read_head(self, rel: str) -> bytes | None:
        url = f"{self._repo_path}/contents/{quote(self._full(rel))}"
        try:
            with self.client.stream(
                "GET",
                url,
                params={"ref": self.branch},
                headers={"Accept": "application/vnd.github.raw+json"},
            ) as response:
                if response.status_code == 404:
                    return None
                if response.status_code != 200:
                    response.read()
                    raise self._fail(response, "read what is published")
                data = b""
                for chunk in response.iter_bytes():
                    data += chunk
                    if len(data) >= HEAD_BYTES:
                        break
                return data[:HEAD_BYTES]
        except httpx.HTTPError as exc:
            raise PublishError(f"GitHub could not be reached: {exc}") from None

    def apply(self, writes: dict[str, bytes], deletes: list[str], message: str) -> list[str]:
        # One retry: a branch that moved under the publish - somebody else
        # publishing to the same site at the same moment - is read again and
        # the change made on top of it.
        try:
            return self._apply_once(writes, deletes, message)
        except _Moved:
            try:
                return self._apply_once(writes, deletes, message)
            except _Moved:
                raise PublishError(
                    "The branch kept changing while this was publishing. Try again in a moment."
                ) from None

    def folder_url(self) -> str:
        return folder_url(self.settings, self.pages_url)

    # --- the pieces of a publish --------------------------------------------

    def _head(self) -> str | None | type[_Empty]:
        response = self._call("GET", f"{self._repo_path}/git/ref/heads/{self.branch}")
        if response.status_code == 404:
            return None
        if response.status_code == 409:
            return _Empty
        return str(self._json(response, "read the branch")["object"]["sha"])

    def _start_repository(self) -> None:
        """Give an empty repository its first commit, which the Git Data API
        needs before it will do anything else."""
        body = {"message": "Start the dashboard site", "content": "", "branch": self.branch}
        url = f"{self._repo_path}/contents/{NO_JEKYLL}"
        response = self._call("PUT", url, json=body)
        if response.status_code not in (200, 201):
            # Some servers will not start a repository on a branch that is not
            # its default; started on the default instead, the branch is then
            # made as for any repository that does not have it yet.
            body.pop("branch")
            response = self._call("PUT", url, json=body)
        if response.status_code not in (200, 201):
            raise NotReady(
                f"{self.owner}/{self.repo} is empty and could not be started "
                f"({self._fail(response, 'start it')}). Add a README to it on GitHub, then "
                "publish again."
            )

    def _blob(self, body: bytes) -> str:
        response = self._call(
            "POST",
            f"{self._repo_path}/git/blobs",
            json={"content": base64.b64encode(body).decode("ascii"), "encoding": "base64"},
        )
        return str(self._json(response, "upload the page")["sha"])

    def _apply_once(self, writes: dict[str, bytes], deletes: list[str], message: str) -> list[str]:
        head = self._head()
        if head is _Empty:
            self._start_repository()
            head = self._head()
            if head is _Empty:
                raise PublishError("GitHub has not finished starting the repository. Try again.")
        fresh = head is None
        base_tree = ""
        if not fresh:
            commit = self._json(
                self._call("GET", f"{self._repo_path}/git/commits/{head}"), "read the branch"
            )
            base_tree = str(commit["tree"]["sha"])

        entries: list[dict[str, Any]] = [
            {"path": self._full(rel), "mode": "100644", "type": "blob", "sha": self._blob(body)}
            for rel, body in writes.items()
        ]
        if fresh:
            entries.append(
                {"path": NO_JEKYLL, "mode": "100644", "type": "blob", "sha": self._blob(b"")}
            )
        # A null sha is how the tree API removes a file. Only ever handed files
        # that are there: removing one that is not is an error on GitHub's side.
        entries.extend(
            {"path": self._full(rel), "mode": "100644", "type": "blob", "sha": None}
            for rel in deletes
        )
        body: dict[str, Any] = {"tree": entries}
        if base_tree:
            body["base_tree"] = base_tree
        tree = str(
            self._json(self._call("POST", f"{self._repo_path}/git/trees", json=body),
                       "build the commit")["sha"]
        )

        if tree != base_tree:
            commit_sha = str(
                self._json(
                    self._call(
                        "POST",
                        f"{self._repo_path}/git/commits",
                        json={"message": message, "tree": tree, "parents": [] if fresh else [head]},
                    ),
                    "make the commit",
                )["sha"]
            )
            if fresh:
                moved = self._call(
                    "POST",
                    f"{self._repo_path}/git/refs",
                    json={"ref": f"refs/heads/{self.branch}", "sha": commit_sha},
                )
            else:
                moved = self._call(
                    "PATCH",
                    f"{self._repo_path}/git/refs/heads/{self.branch}",
                    json={"sha": commit_sha, "force": False},
                )
            if moved.status_code == 422:
                raise _Moved()
            self._json(moved, "update the branch")
        return self._ensure_pages()

    def _pages(self) -> dict[str, Any] | None | type[_Unknown]:
        """GitHub Pages as GitHub has it: on, off (None), or not ours to see.

        A token without "Pages: Read" is refused the question, and reading
        that refusal as "off" sent it on to switch Pages on - and then to say
        Pages was off when it was serving the site perfectly well.
        """
        response = self._call("GET", f"{self._repo_path}/pages")
        if response.status_code in (401, 403):
            return _Unknown
        if response.status_code != 200:
            return None
        pages = response.json()
        if pages.get("html_url"):
            self.pages_url = str(pages["html_url"])
        return pages

    def _pages_mismatch(self, pages: dict[str, Any]) -> list[str]:
        """Whether GitHub Pages serves what this destination writes."""
        source = pages.get("source") or {}
        if pages.get("build_type") == "workflow":
            return [
                "GitHub Pages on this repository is built by a GitHub Actions workflow, so "
                "it does not serve what is committed to a branch. Under Settings, Pages, "
                f"choose 'Deploy from a branch' and {self.branch}."
            ]
        if source.get("branch") and source["branch"] != self.branch:
            return [
                f"GitHub Pages is serving the '{source['branch']}' branch, but this "
                f"destination publishes to '{self.branch}'. Change one of them so they match."
            ]
        if source.get("path") == "/docs" and not (self.folder + "/").startswith("docs/"):
            return [
                "GitHub Pages serves this branch's docs folder, so pages published outside "
                "it will not appear. Set the destination's folder to docs, or Pages to / (root)."
            ]
        return []

    def _ensure_pages(self) -> list[str]:
        pages = self._pages()
        if pages is _Unknown:
            return [_CANNOT_SEE_PAGES.format(branch=self.branch)]
        if pages is not None:
            return self._pages_mismatch(pages)
        response = self._call(
            "POST",
            f"{self._repo_path}/pages",
            json={"source": {"branch": self.branch, "path": "/"}},
        )
        if response.status_code in (200, 201):
            created = response.json()
            if created.get("html_url"):
                self.pages_url = str(created["html_url"])
            return [
                "GitHub Pages was switched on for this repository. The first time, the site "
                "can take a few minutes to appear."
            ]
        try:
            said = str(response.json().get("message") or "")
        except ValueError:
            said = ""
        return [
            f"The page is committed, but GitHub Pages is not on for {self.owner}/{self.repo} "
            f"and this token could not switch it on{f' ({said})' if said else ''}. Switch it "
            f"on under Settings, Pages: Deploy from a branch, {self.branch}, / (root)."
        ]
