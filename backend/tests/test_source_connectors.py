"""Provider adapters all present the same resource/export contract."""

from __future__ import annotations

import io
import zipfile

import httpx
import respx

from app.models import Dataset, DatasetSource
from app.services.source_connectors import SourceResource, make_connector
from app.workers.source_sync import _import_external_file


@respx.mock
def test_odk_discovers_forms_and_downloads_csv_zip(tmp_path):
    base = "https://central.example.org"
    respx.get(f"{base}/v1/projects").mock(
        return_value=httpx.Response(200, json=[{"id": 7, "name": "Census"}])
    )
    respx.get(f"{base}/v1/projects/7/forms").mock(
        return_value=httpx.Response(
            200, json=[{"xmlFormId": "hh", "name": "Household", "version": "2026"}]
        )
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hh.csv", "id,name\n1,Ana\n")
    export = respx.get(f"{base}/v1/projects/7/forms/hh/submissions.csv.zip").mock(
        return_value=httpx.Response(200, content=buffer.getvalue())
    )

    with make_connector(
        provider="odk_central",
        base_url=base,
        username="collector@example.org",
        secret="secret",
    ) as source:
        resources = source.list_resources()
        assert resources[0].identity == "7::hh"
        destination = tmp_path / "odk.zip"
        source.export_to_file(resources[0].identity, destination)

    assert destination.read_bytes() == buffer.getvalue()
    assert export.called
    assert export.calls[0].request.url.params["attachments"] == "false"


@respx.mock
def test_kobo_uses_v2_api_token_and_pages_submission_data(tmp_path):
    base = "https://kf.kobotoolbox.org"
    assets = respx.get(f"{base}/api/v2/assets/").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"uid": "a1", "name": "Labour force"}], "next": None},
        )
    )
    data = respx.get(f"{base}/api/v2/assets/a1/data/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"_id": 1, "sex": "M", "members": [{"age": 30}]},
                    {"_id": 2, "sex": "F", "members": []},
                ],
                "next": None,
            },
        )
    )

    with make_connector(
        provider="kobotoolbox", base_url=base, secret="token-123"
    ) as source:
        resources = source.list_resources()
        destination = tmp_path / "kobo.csv"
        source.export_to_file("a1", destination)

    assert resources[0].title == "Labour force"
    assert assets.calls[0].request.headers["Authorization"] == "Token token-123"
    assert data.calls[0].request.headers["Authorization"] == "Token token-123"
    text = destination.read_text(encoding="utf-8-sig")
    assert "_id,sex,members" in text
    assert '"[{""age"":30}]"' in text


@respx.mock
def test_surveycto_discovers_forms_and_downloads_wide_csv(tmp_path):
    base = "https://office.surveycto.com"
    respx.get(f"{base}/api/v2/forms").mock(
        return_value=httpx.Response(200, json=[{"id": "lfs", "title": "LFS 2026"}])
    )
    export = respx.get(f"{base}/api/v1/forms/data/wide/csv/lfs").mock(
        return_value=httpx.Response(200, text="id,age\n1,42\n")
    )

    with make_connector(
        provider="surveycto", base_url=base, username="api", secret="password"
    ) as source:
        resources = source.list_resources()
        destination = tmp_path / "surveycto.csv"
        source.export_to_file("lfs", destination)

    assert resources[0].title == "LFS 2026"
    assert export.calls[0].request.url.params["date"] == "0"
    assert destination.read_text() == "id,age\n1,42\n"


@respx.mock
def test_csweb_discovers_dictionaries_and_exports_cases(tmp_path):
    root = "https://census.example.org/csweb"
    api = f"{root}/api"
    respx.get(f"{api}/dictionaries").mock(
        return_value=httpx.Response(200, json=[{"name": "PHC2027", "label": "Census"}])
    )
    cases = respx.get(f"{api}/dictionaries/PHC2027/cases").mock(
        return_value=httpx.Response(
            200,
            json=[{"uuid": "001", "key": "HH001", "case": {"members": 4}}],
        )
    )

    with make_connector(
        provider="csweb", base_url=root, username="sync", secret="secret"
    ) as source:
        resources = source.list_resources()
        destination = tmp_path / "csweb.csv"
        source.export_to_file("PHC2027", destination)

    assert resources[0].identity == "PHC2027"
    assert cases.calls[0].request.headers["x-csw-case-range-count"] == "1000"
    text = destination.read_text(encoding="utf-8-sig")
    assert "uuid,key,case" in text
    assert "HH001" in text


@respx.mock
def test_sdmx_imports_only_configured_csv_queries(tmp_path):
    base = "https://stats.example.org/rest"
    path = "data/DF_LFS/.?startPeriod=2025"
    route = respx.get(f"{base}/data/DF_LFS/").mock(
        return_value=httpx.Response(
            200,
            text="STRUCTURE,STRUCTURE_ID,FREQ,TIME_PERIOD,OBS_VALUE\ndataflow,DF_LFS,A,2025,64.1\n",
            headers={"content-type": "text/csv"},
        )
    )

    with make_connector(
        provider="sdmx",
        base_url=base,
        source_config={"resources": [{"title": "Labour force", "path": path}]},
    ) as source:
        resources = source.list_resources()
        assert resources[0].title == "Labour force"
        destination = tmp_path / "sdmx.csv"
        source.export_to_file(path, destination)

    assert route.called
    assert route.calls[0].request.url.params["startPeriod"] == "2025"
    assert "OBS_VALUE" in destination.read_text()


def test_external_refresh_keeps_dataset_id(client, auth_headers, tmp_path, db_session):
    connection = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "ODK",
            "provider": "odk_central",
            "base_url": "https://central.example.org",
            "username": "user",
            "password": "secret",
        },
    ).json()
    resource = SourceResource(id="hh", identity="7::hh", title="Household", kind="form")
    source_file = tmp_path / "household.csv"
    source_file.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    first = _import_external_file(
        connection_id=connection["id"],
        provider="odk_central",
        resource=resource,
        source_file=source_file,
        project_id=None,
        mode="replace",
        workdir=tmp_path / "one",
    )
    dataset_id = first["datasets"][0]["id"]

    source_file.write_text("id,age\n1,31\n2,41\n3,20\n", encoding="utf-8")
    second = _import_external_file(
        connection_id=connection["id"],
        provider="odk_central",
        resource=resource,
        source_file=source_file,
        project_id=None,
        mode="replace",
        workdir=tmp_path / "two",
    )

    assert second["datasets"][0]["id"] == dataset_id
    db_session.expire_all()
    dataset = db_session.get(Dataset, dataset_id)
    assert dataset is not None
    assert dataset.row_count == 3
    assert dataset.source == DatasetSource.external
    assert dataset.connection_id == connection["id"]
    assert dataset.source_ref == "7::hh"


def test_connection_api_keeps_provider_config_and_hides_secret(client, auth_headers):
    response = client.post(
        "/api/v1/connections",
        headers=auth_headers,
        json={
            "name": "SDMX dissemination",
            "provider": "sdmx",
            "base_url": "https://stats.example.org/rest",
            "source_config": {
                "resources": [{"title": "Population", "path": "data/DF_POP/."}]
            },
            "password": "optional-secret",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["provider"] == "sdmx"
    assert body["source_config"]["resources"][0]["title"] == "Population"
    assert body["has_password"] is True
    assert "password" not in body
