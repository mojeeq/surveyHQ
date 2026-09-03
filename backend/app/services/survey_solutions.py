"""Client for the Survey Solutions (World Bank CAPI) headquarters API.

Covers the pieces a monitoring platform needs:
  * connection testing and server details
  * questionnaire discovery
  * interview / assignment listings for field progress
  * the v2 export pipeline (request job -> poll -> download zip -> unpack)

Survey Solutions is workspace aware: API paths are ``{server}/{workspace}/api/...``
for data endpoints, while a handful of admin endpoints live outside a workspace.
"""

from __future__ import annotations

import io
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=20.0, read=300.0)
EXPORT_POLL_SECONDS = 5
EXPORT_MAX_WAIT_SECONDS = 3600

ExportType = Literal["STATA", "Tabular", "SPSS", "Binary", "DDI", "Paradata"]
InterviewStatus = Literal[
    "All",
    "SupervisorAssigned",
    "InterviewerAssigned",
    "Completed",
    "RejectedBySupervisor",
    "ApprovedBySupervisor",
    "RejectedByHeadquarters",
    "ApprovedByHeadquarters",
]


class SurveySolutionsError(RuntimeError):
    """Any failure talking to a Survey Solutions server."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Questionnaire:
    id: str
    version: int
    title: str
    variable: str = ""
    last_entry_date: str | None = None

    @property
    def identity(self) -> str:
        """The ``guid$version`` form the export API expects."""
        return f"{self.id}${self.version}"

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Questionnaire:
        return cls(
            id=str(payload.get("QuestionnaireId") or payload.get("Id") or ""),
            version=int(payload.get("Version") or 0),
            title=str(payload.get("Title") or "Untitled"),
            variable=str(payload.get("Variable") or ""),
            last_entry_date=payload.get("LastEntryDate"),
        )


@dataclass
class ExportJob:
    job_id: int
    status: str
    has_file: bool = False
    progress: int = 0
    download_url: str | None = None
    error: str = ""

    @property
    def is_finished(self) -> bool:
        return self.status in ("Completed", "Fail", "Canceled")

    @property
    def succeeded(self) -> bool:
        return self.status == "Completed"

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ExportJob:
        links = payload.get("Links") or {}
        return cls(
            job_id=int(payload.get("JobId") or payload.get("Id") or 0),
            status=str(payload.get("ExportStatus") or payload.get("Status") or "Unknown"),
            has_file=bool(payload.get("HasExportFile")),
            progress=int(payload.get("Progress") or 0),
            download_url=links.get("Download"),
            error=str(payload.get("Error") or ""),
        )


class SurveySolutionsClient:
    """Thin, synchronous wrapper. Use as a context manager."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        workspace: str = "primary",
        verify_ssl: bool = True,
        timeout: httpx.Timeout | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.workspace = (workspace or "primary").strip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._client = httpx.Client(
            auth=(username, password),
            verify=verify_ssl,
            timeout=timeout or DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": "SurveyHQ/1.0"},
        )

    def __enter__(self) -> SurveySolutionsClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- request plumbing --------------------------------------------------
    def _url(self, path: str, workspace_scoped: bool = True) -> str:
        path = path.lstrip("/")
        if workspace_scoped:
            return f"{self.base_url}/{self.workspace}/{path}"
        return f"{self.base_url}/{path}"

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        reraise=True,
    )
    def _request(
        self,
        method: str,
        path: str,
        *,
        workspace_scoped: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        url = self._url(path, workspace_scoped)
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            raise SurveySolutionsError(
                f"Could not reach the Survey Solutions server at {self.base_url}: {exc}"
            ) from exc
        if response.status_code == 401:
            raise SurveySolutionsError(
                "Authentication failed. Check the API user name and password, and "
                "confirm the account has the API role on this workspace.",
                401,
            )
        if response.status_code == 403:
            raise SurveySolutionsError(
                f"Access denied to workspace '{self.workspace}'. The API user must be "
                "granted access to it.",
                403,
            )
        if response.status_code == 404:
            raise SurveySolutionsError(
                f"Endpoint not found: {url}. Check the server URL and workspace name.",
                404,
            )
        if response.status_code >= 400:
            raise SurveySolutionsError(
                f"Survey Solutions returned {response.status_code}: {response.text[:400]}",
                response.status_code,
            )
        return response

    def _get_json(self, path: str, **kwargs: Any) -> Any:
        response = self._request("GET", path, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SurveySolutionsError(
                "The server did not return JSON. This usually means the URL points at "
                "the web interface rather than the API root."
            ) from exc

    # -- discovery ---------------------------------------------------------
    def test_connection(self) -> dict[str, Any]:
        """Validate credentials and report what the account can see."""
        payload = self._get_json("api/v1/questionnaires", params={"limit": 1, "offset": 0})
        total = int(payload.get("TotalCount") or 0)
        info: dict[str, Any] = {
            "ok": True,
            "workspace": self.workspace,
            "questionnaire_count": total,
        }
        try:
            version = self._request(
                "GET", "api/v1/settings/globalnotice", workspace_scoped=True
            )
            info["reachable_endpoints"] = ["questionnaires", "settings"]
            _ = version
        except SurveySolutionsError:
            info["reachable_endpoints"] = ["questionnaires"]
        try:
            info["workspaces"] = [w["Name"] for w in self.list_workspaces()]
        except SurveySolutionsError:
            info["workspaces"] = [self.workspace]
        return info

    def list_workspaces(self) -> list[dict[str, Any]]:
        payload = self._get_json("api/v1/workspaces", workspace_scoped=False)
        return list(payload.get("Workspaces") or [])

    def list_questionnaires(self, page_size: int = 100) -> list[Questionnaire]:
        results: list[Questionnaire] = []
        offset = 0
        while True:
            payload = self._get_json(
                "api/v1/questionnaires", params={"limit": page_size, "offset": offset}
            )
            batch = payload.get("Questionnaires") or []
            results.extend(Questionnaire.from_api(item) for item in batch)
            total = int(payload.get("TotalCount") or len(results))
            offset += page_size
            if len(results) >= total or not batch:
                break
        return results

    def iter_interviews(
        self,
        questionnaire_id: str | None = None,
        version: int | None = None,
        status: str | None = None,
        page_size: int = 200,
        max_pages: int = 200,
    ) -> Iterator[dict[str, Any]]:
        """Interview summaries, used for near-real-time field progress."""
        params: dict[str, Any] = {"limit": page_size, "offset": 0}
        if questionnaire_id:
            params["questionnaireId"] = questionnaire_id
        if version is not None:
            params["questionnaireVersion"] = version
        if status and status != "All":
            params["status"] = status

        for _ in range(max_pages):
            payload = self._get_json("api/v1/interviews", params=params)
            batch = payload.get("Interviews") or []
            if not batch:
                return
            yield from batch
            total = int(payload.get("TotalCount") or 0)
            params["offset"] = int(params["offset"]) + page_size
            if params["offset"] >= total:
                return

    def list_assignments(self, page_size: int = 200) -> list[dict[str, Any]]:
        payload = self._get_json(
            "api/v1/assignments", params={"limit": page_size, "offset": 0}
        )
        return list(payload.get("Assignments") or [])

    def list_supervisors(self) -> list[dict[str, Any]]:
        payload = self._get_json("api/v1/supervisors", params={"limit": 200, "offset": 0})
        return list(payload.get("Users") or [])

    def list_interviewers(self, supervisor_id: str) -> list[dict[str, Any]]:
        payload = self._get_json(
            f"api/v1/supervisors/{supervisor_id}/interviewers",
            params={"limit": 200, "offset": 0},
        )
        return list(payload.get("Users") or [])

    # -- export pipeline ---------------------------------------------------
    def start_export(
        self,
        questionnaire_identity: str,
        export_type: ExportType = "STATA",
        interview_status: InterviewStatus = "All",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> ExportJob:
        body: dict[str, Any] = {
            "ExportType": export_type,
            "QuestionnaireId": questionnaire_identity,
            "InterviewStatus": interview_status,
        }
        if from_date:
            body["From"] = from_date
        if to_date:
            body["To"] = to_date
        response = self._request("POST", "api/v2/export", json=body)
        return ExportJob.from_api(response.json())

    def get_export_job(self, job_id: int) -> ExportJob:
        return ExportJob.from_api(self._get_json(f"api/v2/export/{job_id}"))

    def wait_for_export(
        self,
        job_id: int,
        poll_seconds: int = EXPORT_POLL_SECONDS,
        max_wait_seconds: int = EXPORT_MAX_WAIT_SECONDS,
        on_progress: Any = None,
    ) -> ExportJob:
        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() < deadline:
            job = self.get_export_job(job_id)
            if on_progress:
                on_progress(job)
            if job.is_finished:
                if not job.succeeded:
                    raise SurveySolutionsError(
                        f"Export job {job_id} finished with status '{job.status}'. "
                        f"{job.error}".strip()
                    )
                return job
            time.sleep(poll_seconds)
        raise SurveySolutionsError(
            f"Export job {job_id} did not finish within {max_wait_seconds} seconds."
        )

    def _same_host(self, url: str) -> bool:
        return urlparse(url).netloc.lower() == urlparse(self.base_url).netloc.lower()

    def _fetch_export_file(self, url: str) -> httpx.Response:
        """GET an export file.

        Credentials go only to the configured server. Survey Solutions can hand
        back a link to separate file storage, and sending Basic auth or an
        ``Accept: application/json`` header to a host that did not ask for them
        is how a download ends up rejected rather than served.
        """
        if self._same_host(url):
            return self._client.get(url, headers={"Accept": "*/*"})
        with httpx.Client(
            verify=self.verify_ssl,
            timeout=self._client.timeout,
            follow_redirects=True,
            headers={"Accept": "*/*", "User-Agent": "SurveyHQ/1.0"},
        ) as anonymous:
            return anonymous.get(url)

    def download_export(self, job: ExportJob) -> bytes:
        """Fetch the finished export.

        The link the server advertises is tried first, then the API's own file
        endpoint. They are genuinely different routes - the link can point at
        external storage or through a proxy - so when one is refused the other
        is still worth attempting.
        """
        candidates: list[str] = []
        if job.download_url:
            candidates.append(job.download_url)
        api_url = self._url(f"api/v2/export/{job.job_id}/file")
        if api_url not in candidates:
            candidates.append(api_url)

        failures: list[str] = []
        for url in candidates:
            host = urlparse(url).netloc or "the server"
            try:
                response = self._fetch_export_file(url)
            except httpx.TransportError as exc:
                failures.append(f"{host} could not be reached ({exc})")
                continue
            if response.status_code < 400:
                return response.content
            failures.append(f"{host} returned {response.status_code}")

        detail = "; ".join(failures)
        hint = ""
        if any("421" in failure for failure in failures):
            # 421 is "Misdirected Request": something answered that does not
            # serve this host. Naming the cause beats naming the number.
            hint = (
                " A 421 means the request reached a server that does not serve that "
                "address - usually a reverse proxy, load balancer or CDN in front of "
                "Survey Solutions. Check that the export download route is reachable "
                "from this machine, and that the server URL you configured is the one "
                "the server itself advertises."
            )
        raise SurveySolutionsError(
            f"Could not download export {job.job_id}: {detail}.{hint}",
            None,
        )

    def export_to_file(
        self,
        questionnaire_identity: str,
        destination: Path,
        export_type: ExportType = "STATA",
        interview_status: InterviewStatus = "All",
        on_progress: Any = None,
    ) -> Path:
        """Full export round trip, keeping the zip exactly as it arrived.

        The archive is what the platform already knows how to import - one
        dataset per roster level, paradata included - so it is written down
        rather than unpacked here. Keeping it also means it can be downloaded
        afterwards, which is the only copy of what the server actually sent.
        """
        job = self.start_export(questionnaire_identity, export_type, interview_status)
        logger.info("Started export job %s for %s", job.job_id, questionnaire_identity)
        job = self.wait_for_export(job.job_id, on_progress=on_progress)
        payload = self.download_export(job)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return destination

    def export_to_directory(
        self,
        questionnaire_identity: str,
        destination: Path,
        export_type: ExportType = "STATA",
        interview_status: InterviewStatus = "All",
        on_progress: Any = None,
    ) -> list[Path]:
        """Full export round trip. Returns the extracted data files."""
        job = self.start_export(questionnaire_identity, export_type, interview_status)
        logger.info("Started export job %s for %s", job.job_id, questionnaire_identity)
        job = self.wait_for_export(job.job_id, on_progress=on_progress)
        payload = self.download_export(job)
        return extract_export_archive(payload, destination)


def extract_export_archive(payload: bytes, destination: Path) -> list[Path]:
    """Unpack a Survey Solutions export zip, keeping only tabular data files."""
    destination.mkdir(parents=True, exist_ok=True)
    keep_suffixes = {".dta", ".tab", ".csv", ".sav"}
    extracted: list[Path] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise SurveySolutionsError(
            "The downloaded export was not a valid zip archive."
        ) from exc

    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name or Path(name).suffix.lower() not in keep_suffixes:
                continue
            target = destination / name
            with archive.open(info) as source, open(target, "wb") as handle:
                handle.write(source.read())
            extracted.append(target)
    if not extracted:
        raise SurveySolutionsError(
            "The export archive contained no data files. Check that the questionnaire "
            "has interviews matching the selected status."
        )
    return extracted


def pick_main_file(files: list[Path], questionnaire_variable: str = "") -> Path:
    """Choose the primary interview-level file out of an export.

    Survey Solutions writes one file per roster level plus system files; the
    main level is named after the questionnaire variable.
    """
    system_names = {
        "interview__actions",
        "interview__errors",
        "interview__comments",
        "interview__diagnostics",
        "assignment__actions",
    }
    candidates = [f for f in files if f.stem.lower() not in system_names]
    if questionnaire_variable:
        for file in candidates:
            if file.stem.lower() == questionnaire_variable.lower():
                return file
    if not candidates:
        candidates = files
    # Largest remaining file is the interview level in practice
    return max(candidates, key=lambda f: f.stat().st_size)
