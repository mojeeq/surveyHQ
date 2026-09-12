"""Adapters for external survey/statistical data systems.

SurveyHQ keeps one scheduling/credential/project model for connections and puts
protocol differences here. Every adapter exposes the same two concepts:
resources that can be selected in the UI, and one or more relational tables
when a resource is pulled.

Survey Solutions remains in ``survey_solutions.py`` because its asynchronous
export-archive workflow carries richer metadata than the JSON APIs below.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urljoin

import httpx
import pandas as pd

from app.services.net_guard import UnsafeAddressError, check_url

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=20.0, read=300.0)
PAGE_SIZE = 1000


class SourceError(RuntimeError):
    """A remote source could not be reached, understood or authorised."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class SourceResource:
    id: str
    title: str
    identity: str
    version: int = 0
    variable: str = ""
    last_entry_date: str | None = None
    kind: str = "survey"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RemoteTable:
    name: str
    source_ref: str
    frame: pd.DataFrame


def _guard(request: httpx.Request) -> None:
    try:
        check_url(str(request.url))
    except UnsafeAddressError as exc:
        raise SourceError(str(exc)) from exc


def source_label(source_type: str) -> str:
    return {
        "survey_solutions": "Survey Solutions",
        "odk": "ODK Central",
        "kobo": "KoboToolbox",
        "csweb": "CSPro / CSWeb",
        "surveycto": "SurveyCTO",
        "sdmx": "SDMX API",
    }.get(source_type, source_type)


class ExternalSourceClient:
    """Synchronous client used by connection tests and background sync jobs."""

    def __init__(
        self,
        *,
        source_type: str,
        base_url: str,
        workspace: str = "",
        username: str = "",
        secret: str = "",
        verify_ssl: bool = True,
        config: dict[str, Any] | None = None,
    ):
        self.source_type = source_type
        self.base_url = base_url.rstrip("/")
        self.workspace = workspace.strip()
        self.username = username.strip()
        self.secret = secret
        self.config = dict(config or {})

        headers = {
            "Accept": "application/json",
            "User-Agent": "SurveyHQ/1.0",
        }
        auth: httpx.BasicAuth | None = None
        if source_type == "kobo" and secret:
            headers["Authorization"] = f"Token {secret}"
        elif source_type in {"odk", "csweb", "surveycto", "sdmx"}:
            if self.username and secret:
                auth = httpx.BasicAuth(self.username, secret)

        self._client = httpx.Client(
            auth=auth,
            verify=verify_ssl,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers=headers,
            event_hooks={"request": [_guard]},
        )

    def __enter__(self) -> ExternalSourceClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = self._url(path)
        try:
            response = self._client.request(method, url, **kwargs)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise SourceError(
                f"Could not reach {source_label(self.source_type)} at {self.base_url}: {exc}"
            ) from exc
        if response.status_code in (401, 403):
            raise SourceError(
                f"{source_label(self.source_type)} rejected the credentials or permissions.",
                response.status_code,
            )
        if response.status_code == 404:
            raise SourceError(
                f"Resource not found at {url}. Check the server URL and resource id.",
                404,
            )
        if response.status_code >= 400:
            detail = response.text[:500].strip()
            raise SourceError(
                f"{source_label(self.source_type)} returned "
                f"{response.status_code}: {detail}",
                response.status_code,
            )
        return response

    def _json(self, path: str, **kwargs: Any) -> Any:
        response = self._request("GET", path, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(
                f"{source_label(self.source_type)} did not return JSON from {path}."
            ) from exc

    # -- common surface -------------------------------------------------
    def test_connection(self) -> dict[str, Any]:
        if self.source_type == "sdmx":
            resources = self._sdmx_resources()
            return {
                "ok": True,
                "source": source_label(self.source_type),
                "resource_count": len(resources),
                "workspace": self.workspace,
            }
        resources = self.list_resources()
        return {
            "ok": True,
            "source": source_label(self.source_type),
            "resource_count": len(resources),
            "workspace": self.workspace,
        }

    def list_resources(self) -> list[SourceResource]:
        if self.source_type == "odk":
            return self._odk_resources()
        if self.source_type == "kobo":
            return self._kobo_resources()
        if self.source_type == "csweb":
            return self._csweb_resources()
        if self.source_type == "surveycto":
            return self._surveycto_resources()
        if self.source_type == "sdmx":
            return self._sdmx_resources()
        raise SourceError(f"Unsupported source type '{self.source_type}'")

    def pull(self, resource_id: str) -> list[RemoteTable]:
        if self.source_type == "odk":
            return self._pull_odk(resource_id)
        if self.source_type == "kobo":
            return self._pull_kobo(resource_id)
        if self.source_type == "csweb":
            return self._pull_csweb(resource_id)
        if self.source_type == "surveycto":
            return self._pull_surveycto(resource_id)
        if self.source_type == "sdmx":
            return self._pull_sdmx(resource_id)
        raise SourceError(f"Unsupported source type '{self.source_type}'")

    # -- ODK Central ----------------------------------------------------
    def _odk_project(self) -> str:
        if not self.workspace:
            raise SourceError("ODK Central needs the numeric project id in Workspace / project.")
        return quote(self.workspace, safe="")

    def _odk_resources(self) -> list[SourceResource]:
        payload = self._json(f"v1/projects/{self._odk_project()}/forms")
        items = payload if isinstance(payload, list) else payload.get("forms", [])
        result: list[SourceResource] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            form_id = str(item.get("xmlFormId") or item.get("id") or "")
            if not form_id:
                continue
            raw_version = item.get("version") or 0
            try:
                version = int(raw_version)
            except (TypeError, ValueError):
                version = 0
            result.append(
                SourceResource(
                    id=form_id,
                    identity=form_id,
                    version=version,
                    title=str(item.get("name") or item.get("displayName") or form_id),
                    variable=form_id,
                    last_entry_date=item.get("updatedAt"),
                    kind="form",
                )
            )
        return result

    def _pull_odk(self, form_id: str) -> list[RemoteTable]:
        project = self._odk_project()
        form = quote(form_id, safe="")
        service_path = f"v1/projects/{project}/forms/{form}.svc"
        service = self._json(service_path)
        entities = service.get("value", []) if isinstance(service, dict) else []
        tables: list[RemoteTable] = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_name = str(entity.get("name") or entity.get("url") or "")
            entity_url = str(entity.get("url") or entity_name)
            if not entity_name:
                continue
            path = f"{service_path}/{entity_url.lstrip('/')}"
            records = self._paged_values(path, value_key="value")
            frame = _frame(records)
            table_name = form_id if entity_name == "Submissions" else f"{form_id} - {entity_name}"
            tables.append(
                RemoteTable(
                    name=table_name,
                    source_ref=f"odk:{self.workspace}:{form_id}:{entity_name}",
                    frame=frame,
                )
            )
        if not tables:
            # Every normal form has Submissions, but using the conventional
            # endpoint here also supports Central versions whose service
            # document omitted entity metadata.
            records = self._paged_values(f"{service_path}/Submissions", value_key="value")
            tables.append(
                RemoteTable(
                    name=form_id,
                    source_ref=f"odk:{self.workspace}:{form_id}:Submissions",
                    frame=_frame(records),
                )
            )
        return tables

    # -- KoboToolbox ----------------------------------------------------
    def _kobo_resources(self) -> list[SourceResource]:
        payload = self._json("api/v2/assets/", params={"asset_type": "survey", "limit": 200})
        items = payload.get("results", payload) if isinstance(payload, dict) else payload
        result: list[SourceResource] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("uid") or "")
            if not uid:
                continue
            result.append(
                SourceResource(
                    id=uid,
                    identity=uid,
                    title=str(item.get("name") or item.get("settings", {}).get("sector") or uid),
                    variable=uid,
                    last_entry_date=item.get("date_modified"),
                    kind="form",
                    meta={"deployment_status": item.get("deployment_status")},
                )
            )
        return result

    def _pull_kobo(self, asset_uid: str) -> list[RemoteTable]:
        uid = quote(asset_uid, safe="")
        path = f"api/v2/assets/{uid}/data/?format=json&limit={PAGE_SIZE}"
        records = self._paged_values(path, value_key="results", next_key="next")
        return _tables_from_records(
            records,
            root_name=asset_uid,
            source_ref=f"kobo:{asset_uid}",
        )

    # -- CSPro / CSWeb --------------------------------------------------
    def _csweb_resources(self) -> list[SourceResource]:
        payload = self._json("dictionaries")
        items = payload if isinstance(payload, list) else payload.get("dictionaries", [])
        result: list[SourceResource] = []
        for item in items:
            if isinstance(item, str):
                name = item
                meta: dict[str, Any] = {}
            elif isinstance(item, dict):
                name = str(item.get("name") or item.get("dictionaryName") or item.get("id") or "")
                meta = dict(item)
            else:
                continue
            if name:
                result.append(
                    SourceResource(
                        id=name,
                        identity=name,
                        title=name,
                        variable=name,
                        kind="dictionary",
                        meta=meta,
                    )
                )
        return result

    def _pull_csweb(self, dictionary: str) -> list[RemoteTable]:
        name = quote(dictionary, safe="")
        path = f"dictionaries/{name}/cases"
        response = self._request("GET", path)
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceError("CSWeb did not return its cases as JSON.") from exc
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = payload.get("cases") or payload.get("data") or payload.get("CaseList") or []
            if isinstance(records, dict):
                records = list(records.values())
        else:
            records = []
        if not isinstance(records, list):
            raise SourceError("CSWeb returned an unrecognised case-list format.")
        return _tables_from_records(
            [row for row in records if isinstance(row, dict)],
            root_name=dictionary,
            source_ref=f"csweb:{dictionary}",
        )

    # -- SurveyCTO ------------------------------------------------------
    def _surveycto_resources(self) -> list[SourceResource]:
        payload = self._json("api/v2/forms")
        if isinstance(payload, dict):
            items = payload.get("forms") or payload.get("data") or payload.get("results") or []
        else:
            items = payload
        result: list[SourceResource] = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, str):
                form_id, title, meta = item, item, {}
            elif isinstance(item, dict):
                form_id = str(item.get("id") or item.get("form_id") or item.get("formId") or "")
                title = str(item.get("name") or item.get("title") or form_id)
                meta = dict(item)
            else:
                continue
            if form_id:
                result.append(
                    SourceResource(
                        id=form_id,
                        identity=form_id,
                        title=title,
                        variable=form_id,
                        kind="form",
                        meta=meta,
                    )
                )
        return result

    def _pull_surveycto(self, form_id: str) -> list[RemoteTable]:
        path = f"api/v2/forms/data/wide/json/{quote(form_id, safe='')}"
        review = str(self.config.get("review_status") or "approved")
        response = self._request("GET", path, params={"date": 0, "r": review})
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceError("SurveyCTO did not return JSON form data.") from exc
        if isinstance(payload, dict):
            records = payload.get("data") or payload.get("results") or payload.get("submissions") or []
        else:
            records = payload
        if not isinstance(records, list):
            raise SourceError("SurveyCTO returned an unrecognised form-data format.")
        return _tables_from_records(
            [row for row in records if isinstance(row, dict)],
            root_name=form_id,
            source_ref=f"surveycto:{form_id}",
        )

    # -- SDMX -----------------------------------------------------------
    def _configured_sdmx_resources(self) -> list[SourceResource]:
        configured = self.config.get("resources") or []
        result: list[SourceResource] = []
        for item in configured:
            if isinstance(item, str):
                identity, title = item, item
                meta: dict[str, Any] = {}
            elif isinstance(item, dict):
                identity = str(item.get("path") or item.get("id") or "")
                title = str(item.get("title") or item.get("name") or identity)
                meta = dict(item)
            else:
                continue
            if identity:
                result.append(
                    SourceResource(
                        id=identity,
                        identity=identity,
                        title=title,
                        variable=identity,
                        kind="dataflow",
                        meta=meta,
                    )
                )
        return result

    def _sdmx_resources(self) -> list[SourceResource]:
        configured = self._configured_sdmx_resources()
        if configured:
            return configured
        # Most 2.1/3.0 providers expose dataflows here. Providers differ in
        # response flavour, so discovery is best-effort; users can always add a
        # concrete data query path in the connection's resource list.
        response = self._request(
            "GET",
            "dataflow/all/all/latest",
            params={"references": "none"},
            headers={"Accept": "application/vnd.sdmx.structure+json, application/json"},
        )
        try:
            payload = response.json()
        except ValueError:
            return []
        found = _find_dataflows(payload)
        return [
            SourceResource(
                id=identity,
                identity=identity,
                title=title,
                variable=identity,
                kind="dataflow",
            )
            for identity, title in found
        ]

    def _pull_sdmx(self, resource: str) -> list[RemoteTable]:
        path = resource.strip()
        if not path:
            raise SourceError("Enter an SDMX data query path, for example data/FLOW/...")
        response = self._request(
            "GET",
            path,
            headers={
                "Accept": (
                    "application/vnd.sdmx.data+csv;version=2.0.0, "
                    "text/csv, application/vnd.sdmx.data+json, application/json"
                )
            },
        )
        content_type = response.headers.get("content-type", "").lower()
        if "csv" in content_type or _looks_like_csv(response.text):
            try:
                frame = pd.read_csv(io.StringIO(response.text))
            except Exception as exc:  # noqa: BLE001 - translate parser details
                raise SourceError(f"Could not read SDMX-CSV: {exc}") from exc
        else:
            try:
                payload = response.json()
            except ValueError as exc:
                raise SourceError("The SDMX endpoint returned neither CSV nor JSON data.") from exc
            frame = _sdmx_json_frame(payload)
        title = str(self.config.get("dataset_name") or _short_name(resource) or "SDMX data")
        return [RemoteTable(name=title, source_ref=f"sdmx:{resource}", frame=frame)]

    # -- pagination ------------------------------------------------------
    def _paged_values(
        self,
        path: str,
        *,
        value_key: str,
        next_key: str = "@odata.nextLink",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        next_path: str | None = path
        pages = 0
        while next_path:
            pages += 1
            if pages > 10000:
                raise SourceError("The remote API returned too many pagination links.")
            payload = self._json(next_path)
            if isinstance(payload, list):
                batch = payload
                next_path = None
            elif isinstance(payload, dict):
                batch = payload.get(value_key) or []
                next_path = payload.get(next_key)
            else:
                batch = []
                next_path = None
            rows.extend(row for row in batch if isinstance(row, dict))
        return rows


def _short_name(value: str) -> str:
    clean = value.rstrip("/").split("?")[0]
    return clean.rsplit("/", 1)[-1]


def _looks_like_csv(text: str) -> bool:
    first = text.lstrip("\ufeff \r\n").splitlines()[0] if text.strip() else ""
    return "," in first and not first.startswith(("{", "[", "<"))


def _frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    frame = pd.json_normalize(records, sep="__")
    for column in frame.columns:
        if frame[column].map(lambda value: isinstance(value, (dict, list))).any():
            frame[column] = frame[column].map(
                lambda value: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else value
            )
    return frame


def _record_id(record: dict[str, Any], fallback: str) -> str:
    for key in ("_id", "__id", "KEY", "instanceID", "instanceId", "uuid", "id", "key"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def _tables_from_records(
    records: list[dict[str, Any]],
    *,
    root_name: str,
    source_ref: str,
) -> list[RemoteTable]:
    """Turn nested API records into a root table plus repeat/roster tables."""
    tables: list[RemoteTable] = []

    def walk(rows: list[dict[str, Any]], name: str, ref: str) -> None:
        scalar_rows: list[dict[str, Any]] = []
        children: dict[str, list[dict[str, Any]]] = {}
        for index, record in enumerate(rows):
            parent_id = _record_id(record, str(index + 1))
            scalar: dict[str, Any] = {}
            for key, value in record.items():
                if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
                    bucket = children.setdefault(str(key), [])
                    for child in value:
                        copied = dict(child)
                        copied.setdefault("_surveyhq_parent_id", parent_id)
                        bucket.append(copied)
                else:
                    scalar[key] = value
            scalar_rows.append(scalar)
        tables.append(RemoteTable(name=name, source_ref=ref, frame=_frame(scalar_rows)))
        for child_name, child_rows in children.items():
            safe_name = child_name.replace("/", " - ")
            walk(child_rows, f"{name} - {safe_name}", f"{ref}:{child_name}")

    walk(records, root_name, source_ref)
    return tables


def _find_dataflows(payload: Any) -> list[tuple[str, str]]:
    """Best-effort extraction across the common SDMX-JSON structure shapes."""
    found: dict[str, str] = {}

    def visit(value: Any, inside_dataflows: bool = False) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                lower = str(key).lower()
                in_flows = inside_dataflows or lower in {"dataflows", "dataflow"}
                if in_flows and isinstance(child, dict):
                    ident = child.get("id") or child.get("ID")
                    name = child.get("name") or child.get("Name")
                    if ident:
                        found[str(ident)] = _label(name) or str(ident)
                visit(child, in_flows)
        elif isinstance(value, list):
            for child in value:
                if inside_dataflows and isinstance(child, dict):
                    ident = child.get("id") or child.get("ID")
                    name = child.get("name") or child.get("Name")
                    if ident:
                        found[str(ident)] = _label(name) or str(ident)
                visit(child, inside_dataflows)

    visit(payload)
    return sorted(found.items())


def _label(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("en", "EN", "text", "value"):
            if value.get(key):
                return str(value[key])
        if value:
            return str(next(iter(value.values())))
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("value") or first.get("text") or "")
        return str(first)
    return ""


def _sdmx_json_frame(payload: Any) -> pd.DataFrame:
    """Decode the compact SDMX-JSON data-message representation."""
    if isinstance(payload, list):
        return _frame([row for row in payload if isinstance(row, dict)])
    if not isinstance(payload, dict):
        raise SourceError("The SDMX JSON response is not an object or row array.")

    # Some providers wrap an ordinary row array rather than compact SDMX-JSON.
    for key in ("data", "results", "observations"):
        candidate = payload.get(key)
        if isinstance(candidate, list) and all(isinstance(row, dict) for row in candidate):
            return _frame(candidate)

    data_sets = payload.get("dataSets")
    structure = payload.get("structure")
    if data_sets is None and isinstance(payload.get("data"), dict):
        data_sets = payload["data"].get("dataSets")
        structure = payload["data"].get("structure") or structure
    if not isinstance(data_sets, list) or not isinstance(structure, dict):
        raise SourceError(
            "The SDMX JSON response uses a shape SurveyHQ does not recognise. "
            "Prefer an SDMX-CSV response for this provider."
        )

    dimensions = structure.get("dimensions") or {}
    series_dims = dimensions.get("series") or []
    obs_dims = dimensions.get("observation") or []
    rows: list[dict[str, Any]] = []

    def decode(key: str, dims: list[dict[str, Any]]) -> dict[str, Any]:
        indexes = key.split(":") if key else []
        values: dict[str, Any] = {}
        for position, dim in enumerate(dims):
            dim_id = str(dim.get("id") or dim.get("name") or f"dimension_{position + 1}")
            choices = dim.get("values") or []
            try:
                choice = choices[int(indexes[position])]
            except (IndexError, ValueError, TypeError):
                continue
            values[dim_id] = choice.get("id") if isinstance(choice, dict) else choice
            if isinstance(choice, dict) and choice.get("name"):
                values[f"{dim_id}__label"] = _label(choice.get("name"))
        return values

    for data_set in data_sets:
        if not isinstance(data_set, dict):
            continue
        series = data_set.get("series") or {}
        if isinstance(series, dict) and series:
            for series_key, series_value in series.items():
                if not isinstance(series_value, dict):
                    continue
                base = decode(str(series_key), series_dims)
                observations = series_value.get("observations") or {}
                for obs_key, obs_value in observations.items():
                    row = {**base, **decode(str(obs_key), obs_dims)}
                    row["OBS_VALUE"] = obs_value[0] if isinstance(obs_value, list) else obs_value
                    rows.append(row)
        else:
            observations = data_set.get("observations") or {}
            for obs_key, obs_value in observations.items():
                row = decode(str(obs_key), obs_dims)
                row["OBS_VALUE"] = obs_value[0] if isinstance(obs_value, list) else obs_value
                rows.append(row)
    return pd.DataFrame(rows)
