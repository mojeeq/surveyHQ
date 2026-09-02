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
