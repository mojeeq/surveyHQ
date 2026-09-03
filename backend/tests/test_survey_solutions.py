"""Survey Solutions client behaviour, with the HTTP layer mocked."""

from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest
import respx

from app.services.survey_solutions import (
    ExportJob,
    Questionnaire,
    SurveySolutionsClient,
    SurveySolutionsError,
    extract_export_archive,
    pick_main_file,
)

BASE = "https://survey.example.org"


def make_client() -> SurveySolutionsClient:
    return SurveySolutionsClient(BASE, "api_user", "secret", workspace="primary")


def test_questionnaire_identity_format():
    q = Questionnaire(id="abc", version=3, title="Household")
    assert q.identity == "abc$3"


@respx.mock
def test_list_questionnaires_pages_through_results():
    respx.get(f"{BASE}/primary/api/v1/questionnaires").mock(
        return_value=httpx.Response(
            200,
            json={
                "Questionnaires": [
                    {"QuestionnaireId": "q1", "Version": 1, "Title": "A", "Variable": "a"}
                ],
                "TotalCount": 1,
            },
        )
    )
    with make_client() as client:
        questionnaires = client.list_questionnaires()
    assert len(questionnaires) == 1
    assert questionnaires[0].identity == "q1$1"


@respx.mock
def test_authentication_failure_is_explained():
    respx.get(f"{BASE}/primary/api/v1/questionnaires").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )
    with make_client() as client, pytest.raises(SurveySolutionsError) as exc:
        client.list_questionnaires()
    assert "Authentication failed" in str(exc.value)
    assert exc.value.status_code == 401


@respx.mock
def test_missing_workspace_is_explained():
    respx.get(f"{BASE}/primary/api/v1/questionnaires").mock(
        return_value=httpx.Response(403, text="Forbidden")
    )
    with make_client() as client, pytest.raises(SurveySolutionsError) as exc:
        client.list_questionnaires()
    assert "workspace" in str(exc.value)


@respx.mock
def test_unreachable_server_is_explained():
    respx.get(f"{BASE}/primary/api/v1/questionnaires").mock(
        side_effect=httpx.ConnectError("no route to host")
    )
    with make_client() as client, pytest.raises(SurveySolutionsError) as exc:
        client.list_questionnaires()
    assert "Could not reach" in str(exc.value)


@respx.mock
def test_start_export_posts_the_questionnaire_identity():
    route = respx.post(f"{BASE}/primary/api/v2/export").mock(
        return_value=httpx.Response(
            200, json={"JobId": 42, "ExportStatus": "Created", "HasExportFile": False}
        )
    )
    with make_client() as client:
        job = client.start_export("q1$2", export_type="STATA", interview_status="Completed")
    assert job.job_id == 42
    body = json.loads(route.calls[0].request.content)
    assert body["QuestionnaireId"] == "q1$2"
    assert body["ExportType"] == "STATA"
    assert body["InterviewStatus"] == "Completed"


@respx.mock
def test_wait_for_export_raises_on_failure():
    respx.get(f"{BASE}/primary/api/v2/export/7").mock(
        return_value=httpx.Response(200, json={"JobId": 7, "ExportStatus": "Fail", "Error": "boom"})
    )
    with make_client() as client, pytest.raises(SurveySolutionsError, match="Fail"):
        client.wait_for_export(7, poll_seconds=0)


def test_export_job_status_helpers():
    assert ExportJob(1, "Completed").succeeded
    assert ExportJob(1, "Fail").is_finished
    assert not ExportJob(1, "Running").is_finished


def test_extract_archive_keeps_only_data_files(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("household.dta", b"stata")
        archive.writestr("interview__actions.dta", b"stata")
        archive.writestr("readme.txt", b"ignore me")
        archive.writestr("export__readme.pdf", b"ignore me too")
    files = extract_export_archive(buffer.getvalue(), tmp_path)
    names = sorted(f.name for f in files)
    assert names == ["household.dta", "interview__actions.dta"]


def test_extract_archive_rejects_non_zip(tmp_path):
    with pytest.raises(SurveySolutionsError, match="not a valid zip"):
        extract_export_archive(b"definitely not a zip", tmp_path)


def test_extract_archive_reports_empty_export(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", b"nothing useful")
    with pytest.raises(SurveySolutionsError, match="no data files"):
        extract_export_archive(buffer.getvalue(), tmp_path)


def test_pick_main_file_prefers_the_questionnaire_variable(tmp_path):
    main = tmp_path / "household.dta"
    main.write_bytes(b"x" * 10)
    actions = tmp_path / "interview__actions.dta"
    actions.write_bytes(b"x" * 5000)
    assert pick_main_file([actions, main], "household") == main


def test_pick_main_file_falls_back_to_largest_non_system_file(tmp_path):
    big = tmp_path / "roster.dta"
    big.write_bytes(b"x" * 900)
    small = tmp_path / "other.dta"
    small.write_bytes(b"x" * 10)
    system = tmp_path / "interview__actions.dta"
    system.write_bytes(b"x" * 99999)
    assert pick_main_file([system, big, small], "") == big


# --- downloading a finished export -----------------------------------------
#
# A real import failed with "Downloading export 4 failed with 421". The message
# named neither the URL nor the host, so it could not be acted on: 421 is
# "Misdirected Request", which says something answered that does not serve that
# address - a proxy, load balancer or CDN in front of Survey Solutions.


@respx.mock
def test_download_falls_back_to_the_api_route_when_the_link_is_misdirected():
    """A refused download link must not end the attempt: the API route differs."""
    respx.get("https://cdn.example.net/exports/4.zip").mock(
        return_value=httpx.Response(421)
    )
    respx.get(f"{BASE}/primary/api/v2/export/4/file").mock(
        return_value=httpx.Response(200, content=b"PK-zip-bytes")
    )
    job = ExportJob(4, "Completed", download_url="https://cdn.example.net/exports/4.zip")
    with make_client() as client:
        assert client.download_export(job) == b"PK-zip-bytes"


@respx.mock
def test_download_error_names_every_host_and_status_it_tried():
    respx.get("https://cdn.example.net/exports/4.zip").mock(
        return_value=httpx.Response(421)
    )
    respx.get(f"{BASE}/primary/api/v2/export/4/file").mock(
        return_value=httpx.Response(403)
    )
    job = ExportJob(4, "Completed", download_url="https://cdn.example.net/exports/4.zip")
    with make_client() as client, pytest.raises(SurveySolutionsError) as exc:
        client.download_export(job)

    message = str(exc.value)
    assert "cdn.example.net returned 421" in message
    assert "survey.example.org returned 403" in message
    # 421 gets an explanation, because the number alone tells an operator nothing
    assert "Misdirected Request" in message or "does not serve that address" in message


@respx.mock
def test_credentials_are_not_sent_to_a_different_host():
    """Basic auth belongs to the configured server, not to wherever it points."""
    route = respx.get("https://cdn.example.net/exports/9.zip").mock(
        return_value=httpx.Response(200, content=b"zip")
    )
    job = ExportJob(9, "Completed", download_url="https://cdn.example.net/exports/9.zip")
    with make_client() as client:
        client.download_export(job)
    assert "authorization" not in route.calls[0].request.headers


@respx.mock
def test_credentials_are_sent_to_the_configured_server():
    route = respx.get(f"{BASE}/primary/api/v2/export/9/file").mock(
        return_value=httpx.Response(200, content=b"zip")
    )
    with make_client() as client:
        client.download_export(ExportJob(9, "Completed"))
    assert "authorization" in route.calls[0].request.headers


@respx.mock
def test_download_reports_an_unreachable_host_rather_than_raising_transport_error():
    respx.get("https://cdn.example.net/exports/5.zip").mock(
        side_effect=httpx.ConnectError("no route to host")
    )
    respx.get(f"{BASE}/primary/api/v2/export/5/file").mock(
        return_value=httpx.Response(500)
    )
    job = ExportJob(5, "Completed", download_url="https://cdn.example.net/exports/5.zip")
    with make_client() as client, pytest.raises(SurveySolutionsError) as exc:
        client.download_export(job)
    assert "could not be reached" in str(exc.value)


@respx.mock
def test_an_export_is_kept_as_the_zip_it_arrived_as(tmp_path):
    """The whole archive is what the platform imports, and what it hands back.

    Keeping only the first data file threw away every roster level and all the
    paradata; writing the zip down means the import path is the same one an
    uploaded archive takes, and the file can be downloaded afterwards.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("household.dta", b"main")
        archive.writestr("members.dta", b"roster")
        archive.writestr("interview__actions.dta", b"paradata")
    payload = buffer.getvalue()

    respx.post(f"{BASE}/primary/api/v2/export").mock(
        return_value=httpx.Response(
            200, json={"JobId": 9, "ExportStatus": "Created", "HasExportFile": False}
        )
    )
    respx.get(f"{BASE}/primary/api/v2/export/9").mock(
        return_value=httpx.Response(
            200,
            json={
                "JobId": 9,
                "ExportStatus": "Completed",
                "HasExportFile": True,
                "Links": {"Download": f"{BASE}/primary/api/v2/export/9/file"},
            },
        )
    )
    respx.get(f"{BASE}/primary/api/v2/export/9/file").mock(
        return_value=httpx.Response(200, content=payload)
    )

    destination = tmp_path / "nested" / "export.zip"
    with make_client() as client:
        written = client.export_to_file("q1$2", destination, interview_status="All")

    assert written == destination
    assert destination.read_bytes() == payload
    # Every member is still in it, paradata included
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == {
            "household.dta",
            "members.dta",
            "interview__actions.dta",
        }
