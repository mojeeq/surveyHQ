"""Getting a dataset back out, and refusing an upload that is too big.

Both are about what happens at the edges of a request: a file large enough to
be worth handing to the worker, and one large enough that nobody should be
made to transfer it before being told no.
"""

from __future__ import annotations

import io

import pandas as pd
import pyreadstat
import pytest

from app.core.config import settings


def test_download_carries_the_labels_into_stata(client, auth_headers, dataset_id, tmp_path):
    """The reason to choose .dta over .csv is that the labels ride along."""
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/download",
        headers=auth_headers,
        params={"format": "dta"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/x-stata-dta"

    path = tmp_path / "out.dta"
    path.write_bytes(response.content)
    frame, meta = pyreadstat.read_dta(str(path))

    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    assert len(frame) == detail["row_count"]
    assert set(frame.columns) == {v["name"] for v in detail["variables"]}
    labelled = {k: v for k, v in meta.column_names_to_labels.items() if v}
    assert labelled, "no variable labels survived the round trip"


@pytest.mark.parametrize("fmt,expected", [("csv", "text/csv"), ("xlsx", "spreadsheet")])
def test_download_in_the_other_formats(client, auth_headers, dataset_id, fmt, expected):
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/download", headers=auth_headers, params={"format": fmt}
    )
    assert response.status_code == 200, response.text
    assert expected in response.headers["content-type"]
    if fmt == "csv":
        frame = pd.read_csv(io.BytesIO(response.content))
        detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
        assert len(frame) == detail["row_count"]


def test_an_unknown_format_is_refused(client, auth_headers, dataset_id):
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/download", headers=auth_headers, params={"format": "sav"}
    )
    assert response.status_code == 422


def test_an_oversized_upload_is_refused_before_it_is_transferred(
    client, auth_headers, monkeypatch
):
    """The case that used to answer 502.

    The size was checked after the whole body had been received and written to
    disk, so a proxy holding a body nobody was reading any more reported a bad
    gateway. The check now happens on the declared length, which means the
    answer names the size and the limit - and the body is never read.
    """
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    body = b"x" * (3 * 1024 * 1024)
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("huge.dta", body, "application/octet-stream")},
        data={"mode": "replace"},
    )
    assert response.status_code == 413, response.text
    detail = response.json()["detail"]
    assert "3 MB" in detail and "1 MB" in detail
