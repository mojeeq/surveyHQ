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


def test_a_crosstab_is_not_cut_at_fifty_categories(client, auth_headers, dataset_id):
    """The old ceiling was 50 rows, which hid most of an interview-key table."""
    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    wide = max(detail["variables"], key=lambda v: v["n_unique"])
    if wide["n_unique"] <= 50:
        pytest.skip("this dataset has no variable with more than 50 categories")

    response = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab",
        headers=auth_headers,
        json={"row_variable": wide["name"], "column_variable": detail["variables"][0]["name"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["row_labels"]) > 50, "the table is still being cut at the old ceiling"
    # Nothing was quietly dropped either.
    assert body["rows_omitted"] == 0


def test_a_cut_crosstab_says_how_much_it_left_out(client, auth_headers, dataset_id):
    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    wide = max(detail["variables"], key=lambda v: v["n_unique"])
    if wide["n_unique"] <= 5:
        pytest.skip("nothing wide enough to cut")

    response = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab",
        headers=auth_headers,
        json={
            "row_variable": wide["name"],
            "column_variable": detail["variables"][0]["name"],
            "max_rows": 5,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["row_labels"]) == 5
    assert body["rows_omitted"] > 0, "a cut table has to say so"


def test_a_dashboard_carries_a_logo_as_well_as_a_background(client, auth_headers):
    """Both images at once, each its own file, and the logo on the shared link."""
    created = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Branded board"}
    )
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]

    png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    for kind in ("background", "logo"):
        uploaded = client.put(
            f"/api/v1/dashboards/{dashboard_id}/{kind}",
            headers=auth_headers,
            files={"file": (f"{kind}.png", png, "image/png")},
        )
        assert uploaded.status_code == 200, uploaded.text

    appearance = client.get(
        f"/api/v1/dashboards/{dashboard_id}", headers=auth_headers
    ).json()["appearance"]
    assert appearance["logo_image"] and appearance["background_image"]

    for kind in ("background", "logo"):
        assert (
            client.get(
                f"/api/v1/dashboards/{dashboard_id}/{kind}", headers=auth_headers
            ).status_code
            == 200
        ), f"{kind} did not come back"

    shared = client.post(
        f"/api/v1/dashboards/{dashboard_id}/share", headers=auth_headers, params={"enable": True}
    ).json()
    token = shared["public_token"]
    # No credentials: a shared link is read by people without accounts.
    assert client.get(f"/api/v1/public/dashboards/{token}/logo").status_code == 200

    assert (
        client.delete(
            f"/api/v1/dashboards/{dashboard_id}/logo", headers=auth_headers
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/dashboards/{dashboard_id}/logo", headers=auth_headers).status_code
        == 404
    )
    # The background is untouched by removing the logo.
    assert (
        client.get(
            f"/api/v1/dashboards/{dashboard_id}/background", headers=auth_headers
        ).status_code
        == 200
    )
    client.delete(f"/api/v1/dashboards/{dashboard_id}", headers=auth_headers)
