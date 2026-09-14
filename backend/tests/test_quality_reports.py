"""Regression coverage for quality failure counts, drill-down and exports."""

from __future__ import annotations

import io

import pandas as pd


def _upload(client, auth_headers, frame: pd.DataFrame, name: str = "quality.csv") -> str:
    raw = frame.to_csv(index=False).encode()
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": (name, raw, "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    item = body["datasets"][0] if "datasets" in body else body
    return item["id"]


def _rule(client, auth_headers, dataset_id: str, payload: dict) -> dict:
    response = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={"dataset_id": dataset_id, "threshold": 0, **payload},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_duplicate_count_uses_all_groups_not_only_preview(client, auth_headers):
    frame = pd.DataFrame(
        {
            "key": [f"g{i:02d}" for i in range(25) for _ in range(2)],
            "value": list(range(50)),
        }
    )
    dataset_id = _upload(client, auth_headers, frame, "many_duplicates.csv")
    rule = _rule(
        client,
        auth_headers,
        dataset_id,
        {"name": "Duplicate keys", "check_type": "duplicates", "config": {"variables": ["key"]}},
    )

    result = client.post(
        f"/api/v1/monitoring/quality-rules/{rule['id']}/run",
        headers=auth_headers,
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["failed_rows"] == 25
    assert body["details"]["duplicate_groups"] == 25
    # The stored examples remain deliberately compact.
    assert len(body["details"]["examples"]["rows"]) == 20


def test_duplicate_rule_filter_applies_before_grouping(client, auth_headers):
    frame = pd.DataFrame(
        {
            "key": ["a", "a", "b", "b", "b"],
            "status": ["done", "done", "pending", "pending", "pending"],
            "value": [1, 2, 3, 4, 5],
        }
    )
    dataset_id = _upload(client, auth_headers, frame, "scoped_duplicates.csv")
    rule = _rule(
        client,
        auth_headers,
        dataset_id,
        {
            "name": "Done duplicates",
            "check_type": "duplicates",
            "config": {"variables": ["key"]},
            "filters": {
                "op": "and",
                "conditions": [{"variable": "status", "operator": "eq", "value": "done"}],
            },
        },
    )

    result = client.post(
        f"/api/v1/monitoring/quality-rules/{rule['id']}/run",
        headers=auth_headers,
    ).json()
    assert result["total_rows"] == 2
    assert result["failed_rows"] == 1
    assert result["details"]["duplicate_groups"] == 1

    preview = client.get(
        f"/api/v1/monitoring/quality-rules/{rule['id']}/failures",
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    failures = preview.json()
    # Investigation shows both copies, while the stored failure count remains
    # the number of extra rows (n-1).
    assert failures["total"] == 2
    assert {row[failures["columns"].index("status")] for row in failures["rows"]} == {"done"}
    assert all(
        row[failures["columns"].index("duplicate_group_size")] == 2
        for row in failures["rows"]
    )


def test_quality_failure_csv_excel_and_workbook_exports(client, auth_headers):
    frame = pd.DataFrame({"key": ["a", "a", "b"], "age": [20, 20, 90]})
    dataset_id = _upload(client, auth_headers, frame, "quality_exports.csv")
    duplicate = _rule(
        client,
        auth_headers,
        dataset_id,
        {"name": "Duplicate key", "check_type": "duplicates", "config": {"variables": ["key"]}},
    )
    _rule(
        client,
        auth_headers,
        dataset_id,
        {
            "name": "Age range",
            "check_type": "value_range",
            "config": {"variable": "age", "min": 0, "max": 80},
        },
    )

    csv_response = client.get(
        f"/api/v1/monitoring/quality-rules/{duplicate['id']}/failures/export?format=csv",
        headers=auth_headers,
    )
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    exported = pd.read_csv(io.BytesIO(csv_response.content))
    assert len(exported) == 2
    assert "duplicate_group_size" in exported.columns

    xlsx_response = client.get(
        f"/api/v1/monitoring/quality-rules/{duplicate['id']}/failures/export?format=xlsx",
        headers=auth_headers,
    )
    assert xlsx_response.status_code == 200, xlsx_response.text
    assert xlsx_response.content[:2] == b"PK"

    workbook = client.get(
        f"/api/v1/monitoring/datasets/{dataset_id}/quality/export",
        headers=auth_headers,
    )
    assert workbook.status_code == 200, workbook.text
    assert workbook.content[:2] == b"PK"
    sheets = pd.ExcelFile(io.BytesIO(workbook.content)).sheet_names
    assert "Summary" in sheets
    assert any(name.startswith("Duplicate key") for name in sheets)
    assert any(name.startswith("Age range") for name in sheets)
