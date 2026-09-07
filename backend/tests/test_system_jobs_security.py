"""System job visibility must not leak work across accounts."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Job, JobStatus, JobType, User


def _headers_for(client, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"******'access_token']}"}


def test_non_admin_only_sees_own_jobs(client, auth_headers, db_session):
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "jobs-viewer@example.com",
            "full_name": "Jobs Viewer",
            "role": "viewer",
            "password": "viewer-password-123",
        },
    )
    assert created.status_code == 201, created.text
    viewer_headers = _headers_for(client, "jobs-viewer@example.com", "viewer-password-123")

    admin = db_session.scalar(select(User).where(User.email == "admin@example.com"))
    viewer = db_session.scalar(select(User).where(User.email == "jobs-viewer@example.com"))
    assert admin is not None and viewer is not None

    admin_job = Job(
        job_type=JobType.ingest,
        status=JobStatus.success,
        title="admin job",
        created_by=admin.id,
        params={"secret": "admin-only"},
    )
    viewer_job = Job(
        job_type=JobType.ingest,
        status=JobStatus.success,
        title="viewer job",
        created_by=viewer.id,
        params={"visible": "self"},
    )
    orphan_job = Job(
        job_type=JobType.monitor,
        status=JobStatus.success,
        title="orphan system job",
        created_by=None,
    )
    db_session.add_all([admin_job, viewer_job, orphan_job])
    db_session.commit()

    viewer_list = client.get("/api/v1/system/jobs?limit=50", headers=viewer_headers)
    assert viewer_list.status_code == 200
    assert [item["id"] for item in viewer_list.json()] == [viewer_job.id]

    assert (
        client.get(f"/api/v1/system/jobs/{viewer_job.id}", headers=viewer_headers).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/system/jobs/{admin_job.id}", headers=viewer_headers).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/system/jobs/{orphan_job.id}", headers=viewer_headers).status_code
        == 404
    )

    admin_list = client.get("/api/v1/system/jobs?limit=50", headers=auth_headers)
    assert admin_list.status_code == 200
    admin_ids = {item["id"] for item in admin_list.json()}
    assert {admin_job.id, viewer_job.id, orphan_job.id}.issubset(admin_ids)
