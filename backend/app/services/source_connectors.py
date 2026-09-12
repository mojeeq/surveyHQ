"""External data-source connectors used by SurveyHQ connections.

Each provider presents the same small contract to the API and sync worker:

* test the credentials/server;
* list importable resources (forms, dictionaries, data queries);
* export one resource to a local CSV/ZIP file.

The ingestion layer therefore does not need provider-specific knowledge.  A new
collector is one adapter here, not another parallel connection subsystem.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from app.services.net_guard import UnsafeAddressError, check_url
from app.services.survey_solutions import SurveySolutionsClient, SurveySolutionsError

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=20.0, read=300.0)

PROVIDER_LABELS: dict[str, str] = {
    "survey_solutions": "Survey Solutions",
    "odk_central": "ODK Central",
    "kobotoolbox": "KoboToolbox",
    "surveycto": "SurveyCTO",
    "csweb": "CSPro / CSWeb",
    "sdmx": "SDMX REST API",
}


class SourceConnectorError(RuntimeError):
    """A readable failure while talking to an external source."""


@dataclass(frozen=True)
class SourceResource:
    """One selectable thing a connection can import."""

    id: str
    title: str
    identity: str
    version: int = 1
    variable: str = ""
    last_entry_date: str | None = None
    kind: str = "resource"


def _guard_request(request: httpx.Request) -> None:
    try:
        check_url(str(request.url))
    except UnsafeAddressError as exc:
        raise SourceConnectorError(str(exc)) from exc


def _scalar(value: Any) -> Any:
    """Keep ordinary CSV values ordinary and preserve nested data as JSON."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return ""
    return value


def write_rows_csv(rows: list[dict[str, Any]], destination: Path) -> Path:
    """Write heterogeneous API objects as one stable UTF-8 CSV table."""
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            name = str(key)
            if name not in seen:
                seen.add(name)
                fields.append(name)
    if not fields:
        # The normal CSV reader still needs a header.  An empty source is a
        # valid refresh and should not become an opaque parser error.
        fields = ["_empty"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _scalar(row.get(key)) for key in fields})
    return destination


class HTTPSourceConnector:
    """Shared guarded HTTP plumbing for non-Survey-Solutions providers."""

    provider = "external"

    def __init__(
        self,
        *,
        base_url: str,
        username: str = "",
        secret: str = "",
        verify_ssl: bool = True,
        source_config: dict[str, Any] | None = None,
        auth: httpx.Auth | tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.secret = secret
        self.source_config = dict(source_config or {})
        self._client = httpx.Client(
            auth=auth,
            headers={"User-Agent": "SurveyHQ/1.0", **(headers or {})},
            verify=verify_ssl,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            event_hooks={"request": [_guard_request]},
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}" if path else self.base_url

    def _same_origin_path(self, url: str) -> str:
        """Turn a provider's absolute next-link into a safe relative request.

        Credentials must never follow a JSON pagination link to another host.
        Redirects are independently guarded by the request hook.
        """
        parsed = urlparse(url)
        base = urlparse(self.base_url)
        if parsed.scheme and (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            raise SourceConnectorError("The source returned a pagination link on another host")
        if not parsed.scheme:
            return url
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, self._url(path), **kwargs)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise SourceConnectorError(f"Could not reach {self.base_url}: {exc}") from exc
        if response.status_code in (401, 403):
            raise SourceConnectorError(
                f"Authentication failed ({response.status_code}). Check the credentials and access role."
            )
        if response.status_code == 404:
            raise SourceConnectorError(
                f"The source endpoint was not found: {response.request.url}. Check the server URL."
            )
        if response.status_code >= 400:
            text = response.text[:400].strip()
            raise SourceConnectorError(
                f"{PROVIDER_LABELS.get(self.provider, self.provider)} returned "
                f"{response.status_code}: {text or response.reason_phrase}"
            )
        return response

    def _json(self, path: str, **kwargs: Any) -> Any:
        response = self._request("GET", path, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceConnectorError("The source did not return JSON where JSON was expected") from exc

    def test_connection(self) -> dict[str, Any]:
        resources = self.list_resources()
        return {
            "ok": True,
            "provider": self.provider,
            "resource_count": len(resources),
        }

    def list_resources(self) -> list[SourceResource]:  # pragma: no cover - interface
        raise NotImplementedError

    def export_to_file(self, identity: str, destination: Path) -> Path:  # pragma: no cover
        raise NotImplementedError

    def export_suffix(self, identity: str) -> str:
        return ".csv"


class SurveySolutionsConnector:
    provider = "survey_solutions"

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        secret: str,
        workspace: str = "primary",
        verify_ssl: bool = True,
        **_: Any,
    ) -> None:
        self.client = SurveySolutionsClient(
            base_url=base_url,
            username=username,
            password=secret,
            workspace=workspace or "primary",
            verify_ssl=verify_ssl,
        )

    def __enter__(self):
        self.client.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.client.__exit__(*exc_info)

    def close(self) -> None:
        self.client.close()

    def test_connection(self) -> dict[str, Any]:
        try:
            info = self.client.test_connection()
        except SurveySolutionsError as exc:
            raise SourceConnectorError(str(exc)) from exc
        info["provider"] = self.provider
        info["resource_count"] = info.get("questionnaire_count", 0)
        return info

    def list_resources(self) -> list[SourceResource]:
        try:
            rows = self.client.list_questionnaires()
        except SurveySolutionsError as exc:
            raise SourceConnectorError(str(exc)) from exc
        return [
            SourceResource(
                id=q.id,
                version=q.version,
                title=q.title,
                variable=q.variable,
                identity=q.identity,
                last_entry_date=q.last_entry_date,
                kind="questionnaire",
            )
            for q in rows
        ]

    def export_suffix(self, identity: str) -> str:
        return ".zip"

    def export_to_file(self, identity: str, destination: Path) -> Path:
        try:
            return self.client.export_to_file(identity, destination)
        except SurveySolutionsError as exc:
            raise SourceConnectorError(str(exc)) from exc


class ODKCentralConnector(HTTPSourceConnector):
    provider = "odk_central"

    def __init__(self, **kwargs: Any) -> None:
        username = str(kwargs.get("username") or "")
        secret = str(kwargs.get("secret") or "")
        super().__init__(**kwargs, auth=(username, secret))

    def list_resources(self) -> list[SourceResource]:
        configured = str(self.source_config.get("project_id") or "").strip()
        if configured:
            project_ids = [configured]
        else:
            projects = self._json("/v1/projects")
            project_ids = [str(row.get("id")) for row in projects if row.get("id") is not None]
        resources: list[SourceResource] = []
        for project_id in project_ids:
            forms = self._json(f"/v1/projects/{quote(project_id, safe='')}/forms")
            for form in forms:
                xml_id = str(form.get("xmlFormId") or form.get("id") or "")
                if not xml_id:
                    continue
                resources.append(
                    SourceResource(
                        id=xml_id,
                        identity=f"{project_id}::{xml_id}",
                        title=str(form.get("name") or xml_id),
                        variable=str(form.get("version") or ""),
                        kind="form",
                    )
                )
        return resources

    def export_suffix(self, identity: str) -> str:
        return ".zip"

    def export_to_file(self, identity: str, destination: Path) -> Path:
        try:
            project_id, xml_id = identity.split("::", 1)
        except ValueError as exc:
            raise SourceConnectorError("Invalid ODK form identity") from exc
        response = self._request(
            "GET",
            f"/v1/projects/{quote(project_id, safe='')}/forms/"
            f"{quote(xml_id, safe='')}/submissions.csv.zip",
            params={"attachments": "false"},
            headers={"Accept": "application/zip"},
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return destination


class KoboConnector(HTTPSourceConnector):
    provider = "kobotoolbox"

    def __init__(self, **kwargs: Any) -> None:
        secret = str(kwargs.get("secret") or "")
        headers = {"Authorization": f"Token {secret}"} if secret else {}
        super().__init__(**kwargs, headers=headers)

    def list_resources(self) -> list[SourceResource]:
        path = "/api/v2/assets/?asset_type=survey&limit=200"
        resources: list[SourceResource] = []
        while path:
            payload = self._json(path)
            for asset in payload.get("results") or []:
                uid = str(asset.get("uid") or "")
                if not uid:
                    continue
                resources.append(
                    SourceResource(
                        id=uid,
                        identity=uid,
                        title=str(asset.get("name") or uid),
                        kind="form",
                    )
                )
            next_url = payload.get("next")
            path = self._same_origin_path(str(next_url)) if next_url else ""
        return resources

    def export_to_file(self, identity: str, destination: Path) -> Path:
        path = f"/api/v2/assets/{quote(identity, safe='')}/data/?limit=1000"
        rows: list[dict[str, Any]] = []
        while path:
            payload = self._json(path)
            batch = payload.get("results") or []
            rows.extend(row for row in batch if isinstance(row, dict))
            next_url = payload.get("next")
            path = self._same_origin_path(str(next_url)) if next_url else ""
        return write_rows_csv(rows, destination)


class SurveyCTOConnector(HTTPSourceConnector):
    provider = "surveycto"

    def __init__(self, **kwargs: Any) -> None:
        username = str(kwargs.get("username") or "")
        secret = str(kwargs.get("secret") or "")
        super().__init__(**kwargs, auth=(username, secret))

    def list_resources(self) -> list[SourceResource]:
        payload = self._json("/api/v2/forms")
        forms = payload if isinstance(payload, list) else payload.get("forms") or payload.get("results") or []
        resources: list[SourceResource] = []
        for form in forms:
            if isinstance(form, str):
                form_id, title = form, form
            else:
                form_id = str(
                    form.get("id")
                    or form.get("formid")
                    or form.get("form_id")
                    or form.get("name")
                    or ""
                )
                title = str(form.get("title") or form.get("name") or form_id)
            if form_id:
                resources.append(
                    SourceResource(id=form_id, identity=form_id, title=title, kind="form")
                )
        return resources

    def export_to_file(self, identity: str, destination: Path) -> Path:
        response = self._request(
            "GET",
            f"/api/v1/forms/data/wide/csv/{quote(identity, safe='')}",
            params={"date": "0"},
            headers={"Accept": "text/csv"},
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return destination


class CSWebConnector(HTTPSourceConnector):
    provider = "csweb"

    def __init__(self, **kwargs: Any) -> None:
        username = str(kwargs.get("username") or "")
        secret = str(kwargs.get("secret") or "")
        base_url = str(kwargs.get("base_url") or "").rstrip("/")
        if not base_url.endswith("/api"):
            kwargs["base_url"] = f"{base_url}/api"
        super().__init__(**kwargs, auth=(username, secret))

    def list_resources(self) -> list[SourceResource]:
        payload = self._json("/dictionaries")
        resources: list[SourceResource] = []
        for item in payload if isinstance(payload, list) else []:
            if isinstance(item, str):
                name = item
                title = item
            else:
                name = str(item.get("name") or item.get("dictionary") or item.get("id") or "")
                title = str(item.get("label") or item.get("name") or name)
            if name:
                resources.append(
                    SourceResource(id=name, identity=name, title=title, kind="dictionary")
                )
        return resources

    def export_to_file(self, identity: str, destination: Path) -> Path:
        rows: list[dict[str, Any]] = []
        start_after = ""
        page_size = 1000
        while True:
            headers = {"x-csw-case-range-count": str(page_size)}
            if start_after:
                headers["x-csw-case-range-start-after"] = start_after
            response = self._request(
                "GET",
                f"/dictionaries/{quote(identity, safe='')}/cases",
                headers=headers,
            )
            payload = response.json()
            batch = payload if isinstance(payload, list) else payload.get("cases") or []
            batch = [row for row in batch if isinstance(row, dict)]
            rows.extend(batch)
            if not batch or len(batch) < page_size:
                break
            last = batch[-1]
            next_key = str(last.get("uuid") or last.get("guid") or "")
            if not next_key or next_key == start_after:
                break
            start_after = next_key
        return write_rows_csv(rows, destination)


class SDMXConnector(HTTPSourceConnector):
    provider = "sdmx"

    def _configured(self) -> list[SourceResource]:
        resources = self.source_config.get("resources") or []
        out: list[SourceResource] = []
        for index, item in enumerate(resources, start=1):
            if isinstance(item, str):
                path = item.strip()
                title = path
            elif isinstance(item, dict):
                path = str(item.get("path") or item.get("id") or "").strip()
                title = str(item.get("title") or item.get("name") or path)
            else:
                continue
            if not path:
                continue
            out.append(
                SourceResource(
                    id=path,
                    identity=path,
                    title=title or f"SDMX query {index}",
                    kind="data query",
                )
            )
        data_path = str(self.source_config.get("data_path") or "").strip()
        if data_path and all(row.identity != data_path for row in out):
            out.append(
                SourceResource(id=data_path, identity=data_path, title=data_path, kind="data query")
            )
        return out

    def list_resources(self) -> list[SourceResource]:
        return self._configured()

    def test_connection(self) -> dict[str, Any]:
        resources = self._configured()
        path = resources[0].identity if resources else ""
        self._request(
            "GET",
            path,
            headers={
                "Accept": "text/csv, application/vnd.sdmx.data+csv;version=2.0, */*;q=0.1"
            },
        )
        return {
            "ok": True,
            "provider": self.provider,
            "resource_count": len(resources),
            "configured": bool(resources),
        }

    def export_to_file(self, identity: str, destination: Path) -> Path:
        allowed = {resource.identity for resource in self._configured()}
        if identity not in allowed:
            raise SourceConnectorError("That SDMX data query is not configured on this connection")
        response = self._request(
            "GET",
            identity,
            headers={
                "Accept": "text/csv, application/vnd.sdmx.data+csv;version=2.0, "
                "application/vnd.sdmx.data+csv;version=1.0"
            },
        )
        body = response.content.lstrip()
        if body.startswith((b"{", b"[", b"<")):
            raise SourceConnectorError(
                "This SDMX endpoint did not return SDMX-CSV. Configure a data query "
                "that supports CSV responses."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return destination


CONNECTORS = {
    "survey_solutions": SurveySolutionsConnector,
    "odk_central": ODKCentralConnector,
    "kobotoolbox": KoboConnector,
    "surveycto": SurveyCTOConnector,
    "csweb": CSWebConnector,
    "sdmx": SDMXConnector,
}


def make_connector(
    *,
    provider: str,
    base_url: str,
    username: str = "",
    secret: str = "",
    workspace: str = "primary",
    verify_ssl: bool = True,
    source_config: dict[str, Any] | None = None,
):
    """Build the provider adapter, rejecting unknown source types explicitly."""
    connector = CONNECTORS.get(provider)
    if connector is None:
        raise SourceConnectorError(f"Unsupported connection provider: {provider}")
    return connector(
        base_url=base_url,
        username=username,
        secret=secret,
        workspace=workspace,
        verify_ssl=verify_ssl,
        source_config=source_config or {},
    )
