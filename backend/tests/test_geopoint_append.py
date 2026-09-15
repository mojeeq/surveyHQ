"""Appended interviews keep the coordinates split out of a combined GPS column.

A dataset imported with a combined GPS column holds "<name>__latitude" and
"<name>__longitude" beside it. The rows arriving in a later round have to land
in those same columns. If they do not, the appended interviews are the ones a
map silently leaves out and Missing GPS flags - the newest fieldwork, which is
the fieldwork anybody is watching a monitoring dashboard for.

There are two append implementations and the deployed one is the columnar
append, which writes the incoming rows straight to Parquet without ever seeing
the stored frame. Both are exercised here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services import datasets as dataset_service


def _csv(keys: list[str]) -> bytes:
    frame = pd.DataFrame(
        {
            "interview__key": keys,
            "gps": [f"-17.73{n} 168.32{n} 42.0 5.0" for n in range(1000, 1000 + len(keys))],
        }
    )
    return frame.to_csv(index=False).encode()


@pytest.fixture
def project(client, auth_headers) -> str:
    created = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Combined GPS"}
    )
    project_id = created.json()["id"]
    yield project_id
    client.delete(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers,
        params={"contents": "delete"},
    )


@pytest.fixture(params=["columnar", "pandas"])
def append_implementation(request, monkeypatch):
    """Run the test against each append implementation in turn."""
    if request.param == "pandas":
        pandas_append = getattr(dataset_service, "append_frame_pandas", None)
        if pandas_append is None:  # the runtime was never installed
            pytest.skip("the columnar append is not installed")
        monkeypatch.setattr(
            dataset_service, "append_frame_into_dataset", pandas_append
        )
    return request.param


def test_appended_rows_get_the_coordinates_too(
    client, auth_headers, project, append_implementation
):
    first = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[("file", ("round1.csv", _csv([f"k{i}" for i in range(6)]), "text/csv"))],
        data={"project_id": project},
    )
    assert first.status_code == 201, first.text
    dataset_id = first.json()["id"]

    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    assert "gps__latitude" in [v["name"] for v in detail["variables"]]

    second = client.post(
        f"/api/v1/datasets/{dataset_id}/append",
        headers=auth_headers,
        files={"file": ("round2.csv", _csv([f"n{i}" for i in range(4)]), "text/csv")},
    )
    assert second.status_code == 200, second.text

    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    assert detail["row_count"] == 10
    by_name = {v["name"]: v for v in detail["variables"]}
    assert "gps__latitude" in by_name, list(by_name)
    # The whole point: not one of the ten rows is missing its coordinates.
    # Before the split reached this path, the four appended ones were null.
    assert by_name["gps__latitude"]["n_missing"] == 0
    assert by_name["gps__longitude"]["n_missing"] == 0
