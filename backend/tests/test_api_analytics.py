"""End-to-end API behaviour for analysis, monitoring and dashboards."""

from __future__ import annotations


def test_upload_reports_shape_and_metadata(client, auth_headers, dataset_id):
    response = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 200
    assert body["status"] == "ready"
    assert body["meta"]["monitoring_fields"]["interviewer"] == "interviewer"


def test_preview_returns_rows(client, auth_headers, dataset_id):
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/preview?limit=5", headers=auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()["rows"]) == 5


def test_frequency_uses_value_labels(client, auth_headers, dataset_id):
    response = client.get(
        f"/api/v1/analytics/datasets/{dataset_id}/frequency/sex", headers=auth_headers
    )
    assert response.status_code == 200
    labels = {row["label"] for row in response.json()["rows"]}
    assert labels == {"Male", "Female"}
    assert sum(row["count"] for row in response.json()["rows"]) == 200


def test_aggregate_query(client, auth_headers, dataset_id):
    response = client.post(
        "/api/v1/analytics/query",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "spec": {
                "dimensions": [{"variable": "region"}],
                "measures": [
                    {"agg": "count", "alias": "n"},
                    {"agg": "mean", "variable": "age", "alias": "avg_age"},
                ],
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert [c["name"] for c in body["columns"]] == ["region", "n", "avg_age"]
    assert sum(row[1] for row in body["rows"]) == 200


def test_query_rejects_unknown_variable(client, auth_headers, dataset_id):
    response = client.post(
        "/api/v1/analytics/query",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "spec": {"dimensions": [{"variable": "nope"}], "measures": [{"agg": "count"}]},
        },
    )
    assert response.status_code == 400
    assert "Unknown variable" in response.json()["detail"]


def test_filters_reduce_the_result(client, auth_headers, dataset_id):
    def total(filters):
        response = client.post(
            "/api/v1/analytics/query",
            headers=auth_headers,
            json={
                "dataset_id": dataset_id,
                "spec": {"measures": [{"agg": "count", "alias": "n"}], "filters": filters},
            },
        )
        assert response.status_code == 200
        return response.json()["rows"][0][0]

    everything = total({"op": "and", "conditions": []})
    adults = total(
        {"op": "and", "conditions": [{"variable": "age", "operator": "gte", "value": 40}]}
    )
    assert everything == 200
    assert 0 < adults < everything


def test_crosstab_row_percentages_sum_to_100(client, auth_headers, dataset_id):
    response = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/crosstab",
        headers=auth_headers,
        json={
            "row_variable": "region",
            "column_variable": "sex",
            "percentages": "row",
        },
    )
    assert response.status_code == 200
    body = response.json()
    for row in body["values"]:
        assert abs(sum(v for v in row if v is not None) - 100) < 0.05
    assert body["chi_square"]["dof"] == (len(body["row_labels"]) - 1) * (
        len(body["column_labels"]) - 1
    )


def test_summary_statistics(client, auth_headers, dataset_id):
    response = client.post(
        f"/api/v1/analytics/datasets/{dataset_id}/summary",
        headers=auth_headers,
        json=["age", "income"],
    )
    assert response.status_code == 200
    stats = {s["variable"]: s for s in response.json()}
    assert stats["income"]["missing"] == 10
    assert stats["age"]["min"] >= 18


def test_csv_and_excel_export(client, auth_headers, dataset_id):
    payload = {
        "dataset_id": dataset_id,
        "spec": {
            "dimensions": [{"variable": "region"}],
            "measures": [{"agg": "count", "alias": "n"}],
        },
    }
    csv_response = client.post(
        "/api/v1/analytics/query/export?format=csv", headers=auth_headers, json=payload
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")

    xlsx_response = client.post(
        "/api/v1/analytics/query/export?format=xlsx", headers=auth_headers, json=payload
    )
    assert xlsx_response.status_code == 200
    assert xlsx_response.content[:2] == b"PK"  # a zip container, i.e. a real xlsx


def test_field_progress_builds_views(client, auth_headers, dataset_id):
    response = client.post(
        f"/api/v1/monitoring/datasets/{dataset_id}/field-progress",
        headers=auth_headers,
        json={"op": "and", "conditions": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert "status_breakdown" in body["available_views"]
    assert "by_interviewer" in body["available_views"]
    assert body["total_records"] == 200


def test_indicator_lifecycle_and_thresholds(client, auth_headers, dataset_id):
    created = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Total interviews",
            "dataset_id": dataset_id,
            "spec": {"measures": [{"agg": "count", "alias": "n"}]},
            "target_value": 400,
            "warning_threshold": 300,
            "critical_threshold": 100,
            "direction": "higher_is_better",
        },
    )
    assert created.status_code == 201
    assert created.json()["last_value"] == 200

    values = client.get("/api/v1/monitoring/indicators/values", headers=auth_headers)
    assert values.status_code == 200
    indicator = next(
        v for v in values.json() if v["indicator_id"] == created.json()["id"]
    )
    # 200 is below the warning threshold of 300 but above critical
    assert indicator["status"] == "warning"
    assert indicator["progress_percent"] == 50.0


def test_alert_rule_fires_and_resolves(client, auth_headers, dataset_id):
    indicator = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Alert source",
            "dataset_id": dataset_id,
            "spec": {"measures": [{"agg": "count", "alias": "n"}]},
        },
    ).json()

    rule = client.post(
        "/api/v1/monitoring/alert-rules",
        headers=auth_headers,
        json={
            "name": "Too few interviews",
            "indicator_id": indicator["id"],
            "condition": {"operator": "lt", "value": 1000},
            "severity": "critical",
            "cooldown_minutes": 0,
        },
    ).json()

    triggered = client.post(
        f"/api/v1/monitoring/alert-rules/{rule['id']}/test", headers=auth_headers
    )
    assert triggered.status_code == 200
    assert triggered.json()["triggered"] is True

    alerts = client.get(
        "/api/v1/monitoring/alerts?status=open", headers=auth_headers
    ).json()
    alert = next(a for a in alerts if a["rule_id"] == rule["id"])
    acknowledged = client.post(
        f"/api/v1/monitoring/alerts/{alert['id']}/acknowledge", headers=auth_headers
    )
    assert acknowledged.json()["status"] == "acknowledged"


def test_quality_suggestions_and_run(client, auth_headers, dataset_id):
    suggestions = client.get(
        f"/api/v1/monitoring/datasets/{dataset_id}/quality/suggestions",
        headers=auth_headers,
    )
    assert suggestions.status_code == 200
    names = [s["name"] for s in suggestions.json()]
    assert "Duplicate interview keys" in names

    created = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "name": "Age within range",
            "dataset_id": dataset_id,
            "check_type": "value_range",
            "config": {"variable": "age", "min": 18, "max": 70},
            "threshold": 0.0,
        },
    )
    assert created.status_code == 201

    result = client.post(
        f"/api/v1/monitoring/quality-rules/{created.json()['id']}/run",
        headers=auth_headers,
    )
    assert result.status_code == 200
    assert result.json()["failed_rows"] == 0
    assert result.json()["passed"] is True


def test_duplicate_check_detects_repeats(client, auth_headers, dataset_id):
    created = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "name": "Unique keys",
            "dataset_id": dataset_id,
            "check_type": "duplicates",
            "config": {"variables": ["interview__key"]},
        },
    )
    result = client.post(
        f"/api/v1/monitoring/quality-rules/{created.json()['id']}/run",
        headers=auth_headers,
    )
    assert result.json()["passed"] is True

    # region repeats by construction, so the same check must fail on it
    other = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "name": "Unique regions",
            "dataset_id": dataset_id,
            "check_type": "duplicates",
            "config": {"variables": ["region"]},
        },
    )
    other_result = client.post(
        f"/api/v1/monitoring/quality-rules/{other.json()['id']}/run", headers=auth_headers
    )
    assert other_result.json()["passed"] is False


def test_dashboard_render_and_public_sharing(client, auth_headers, dataset_id):
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "By region",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "region"}],
                    "measures": [{"agg": "count", "alias": "n"}],
                }
            },
        },
    )
    assert chart.status_code == 201

    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Progress"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "Regions", "widget_type": "chart", "chart_id": chart.json()["id"]},
    )

    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data",
        headers=auth_headers,
        json={"op": "and", "conditions": []},
    )
    assert rendered.status_code == 200
    widget = next(iter(rendered.json()["widgets"].values()))
    assert widget["type"] == "chart"
    assert widget["result"]["row_count"] > 0

    shared = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/share?enable=true", headers=auth_headers
    ).json()
    token = shared["public_token"]

    # No credentials at all for the public route
    public = client.get(f"/api/v1/public/dashboards/{token}")
    assert public.status_code == 200
    assert public.json()["name"] == "Progress"

    client.post(f"/api/v1/dashboards/{dashboard['id']}/share?enable=false", headers=auth_headers)
    assert client.get(f"/api/v1/public/dashboards/{token}").status_code == 404


def test_chart_query_is_validated_on_save(client, auth_headers, dataset_id):
    response = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Broken",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {"query": {"measures": [{"agg": "mean"}]}},
        },
    )
    assert response.status_code == 422


def test_health_endpoint(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
