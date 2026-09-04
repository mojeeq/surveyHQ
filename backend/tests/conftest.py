"""Shared fixtures.

Tests default to SQLite in a temporary directory, which needs no services and is
fast. Setting DATABASE_URL_OVERRIDE before running points the same suite at a
real PostgreSQL instead — CI does that, because some faults only appear there
(a shared enum type emitting CREATE TYPE twice, for one).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TMP_ROOT = Path(tempfile.mkdtemp(prefix="surveyhq-tests-"))
# An empty value counts as unset: a CI matrix that passes DATABASE_URL_OVERRIDE=""
# for its SQLite leg leaves the name defined, which setdefault would not replace,
# and the app would then fall back to its default PostgreSQL host.
if not os.environ.get("DATABASE_URL_OVERRIDE"):
    os.environ["DATABASE_URL_OVERRIDE"] = f"sqlite:///{TMP_ROOT / 'test.db'}"
os.environ.update(
    STORAGE_DIR=str(TMP_ROOT / "storage"),
    SECRET_KEY="test-secret-key-not-for-production-use",
    FIRST_ADMIN_EMAIL="admin@example.com",
    FIRST_ADMIN_PASSWORD="test-password-123",
    ENVIRONMENT="test",
    # Off by default, or a suite that signs in more than a handful of times
    # would start refusing its own logins. The tests that cover the limiter
    # turn it back on around themselves.
    RATE_LIMIT_ENABLED="false",
)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "test-password-123"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def auth_headers(client) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def stata_file() -> Path:
    """A small Stata file shaped like a Survey Solutions export."""
    rng = np.random.default_rng(42)
    size = 200
    frame = pd.DataFrame(
        {
            "interview__key": [f"key-{i:04d}" for i in range(size)],
            "interview__status": rng.choice([100, 120], size),
            "interviewer": rng.choice(["ana", "ben", "cara"], size),
            "region": rng.choice(["North", "South"], size),
            "age": rng.integers(18, 70, size).astype(float),
            "sex": rng.choice([1, 2], size),
            "income": rng.normal(1000, 200, size).round(2),
            "duration": rng.gamma(4, 6, size).round(1),
            "interview__date": pd.to_datetime("2026-02-01")
            + pd.to_timedelta(rng.integers(0, 30, size), unit="D"),
        }
    )
    frame.loc[0:9, "income"] = np.nan
    path = TMP_ROOT / "sample.dta"
    frame.to_stata(
        path,
        write_index=False,
        variable_labels={"age": "Age of respondent", "sex": "Sex of respondent"},
        value_labels={
            "sex": {1: "Male", 2: "Female"},
            "interview__status": {100: "Completed", 120: "ApprovedBySupervisor"},
        },
        version=118,
    )
    return path


@pytest.fixture(scope="session")
def dataset_id(client, auth_headers, stata_file) -> str:
    with open(stata_file, "rb") as handle:
        response = client.post(
            "/api/v1/datasets/upload",
            headers=auth_headers,
            files={"file": ("sample.dta", handle, "application/octet-stream")},
            data={"name": "Test Survey"},
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def db_session():
    """A session for tests that need to set up rows the API cannot create.

    A sync run, for instance: those are written by the worker, and the point of
    the test is what the API does with one that already exists.
    """
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
