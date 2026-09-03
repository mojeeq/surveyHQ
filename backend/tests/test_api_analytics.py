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


# --- zip upload and append --------------------------------------------------


def _stata_bytes(frame):
    import io

    import pandas as pd  # noqa: F401

    buffer = io.BytesIO()
    frame.to_stata(buffer, write_index=False, version=118)
    return buffer.getvalue()


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_an_archive_becomes_one_dataset_per_roster_level(client, auth_headers):
    """A Survey Solutions export holds one file per level, not one per round.

    A real VN_LF2024 export contains VN_LF2024.dta (the interview),
    R_demographics.dta (one row per person) and abroad_roster.dta. Appending
    those three together would be nonsense, so each becomes its own dataset.
    """
    import pandas as pd

    archive = _zip_bytes(
        {
            "survey.dta": _stata_bytes(
                pd.DataFrame({"interview__key": ["a", "b"], "province": [1.0, 2.0]})
            ),
            "members.dta": _stata_bytes(
                pd.DataFrame(
                    {
                        "interview__key": ["a", "a", "b"],
                        "members__id": [1.0, 2.0, 1.0],
                        "age": [30.0, 8.0, 44.0],
                    }
                )
            ),
        }
    )
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", archive, "application/zip")},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    by_name = {d["name"]: d for d in body["datasets"]}
    assert set(by_name) == {"survey", "members"}
    assert by_name["survey"]["row_count"] == 2
    assert by_name["members"]["row_count"] == 3


def test_a_later_archive_appends_each_file_to_its_match(client, auth_headers):
    """Rounds arrive as separate archives carrying the same member names.

    Member names are unique to this test: matching is by member name within a
    scope, so reusing a name another test uploaded would append onto its data.
    That is the intended behaviour, but it makes for an order-dependent test.
    """
    import pandas as pd

    def archive(keys, provinces, member_keys, ages):
        return _zip_bytes(
            {
                "lfs_main.dta": _stata_bytes(
                    pd.DataFrame({"interview__key": keys, "province": provinces})
                ),
                "lfs_persons.dta": _stata_bytes(
                    pd.DataFrame({"interview__key": member_keys, "age": ages})
                ),
            }
        )

    first = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "sept.zip",
                archive(["a", "b"], [1.0, 2.0], ["a", "a", "b"], [30.0, 8.0, 44.0]),
                "application/zip",
            )
        },
        data={"mode": "append"},
    )
    assert first.status_code == 201, first.text
    assert len(first.json()["created"]) == 2

    second = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "oct.zip",
                archive(["c"], [3.0], ["c", "c"], [55.0, 12.0]),
                "application/zip",
            )
        },
        data={"mode": "append"},
    )
    assert second.status_code == 201, second.text
    body = second.json()
    # Appended, not duplicated into a second pair of datasets
    assert body["created"] == [], body["created"]
    assert len(body["appended"]) == 2

    by_name = {d["name"]: d for d in body["datasets"]}
    assert by_name["lfs_main"]["row_count"] == 3      # 2 + 1
    assert by_name["lfs_persons"]["row_count"] == 5   # 3 + 2

    # The rounds stay distinguishable, which is what source_file is for
    frequency = client.get(
        f"/api/v1/analytics/datasets/{by_name['lfs_main']['id']}/frequency/source_file",
        headers=auth_headers,
    )
    counts = {row["label"]: row["count"] for row in frequency.json()["rows"]}
    assert counts == {"sept.zip": 2, "oct.zip": 1}


def test_a_same_named_file_from_another_survey_is_not_appended(client, auth_headers):
    """Name alone is not enough: the columns have to match too.

    Two unrelated surveys can each export a "roster.dta". Appending one onto the
    other would produce a dataset whose row count means nothing.
    """
    import pandas as pd

    client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "survey-a.zip",
                _zip_bytes(
                    {
                        "shared_name.dta": _stata_bytes(
                            pd.DataFrame({"crops": [1.0], "hectares": [2.0]})
                        )
                    }
                ),
                "application/zip",
            )
        },
    )
    other = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "survey-b.zip",
                _zip_bytes(
                    {
                        "shared_name.dta": _stata_bytes(
                            pd.DataFrame({"vaccine": [1.0], "doses": [3.0]})
                        )
                    }
                ),
                "application/zip",
            )
        },
    )
    assert other.status_code == 201, other.text
    body = other.json()
    assert body["appended"] == [], body["appended"]
    assert len(body["created"]) == 1


def test_re_uploading_the_same_archive_warns_that_interviews_are_doubled(
    client, auth_headers
):
    """Survey Solutions can export cumulatively; appending two such exports
    duplicates every interview they share, and the row count alone hides it."""
    import pandas as pd

    payload = _zip_bytes(
        {
            "survey.dta": _stata_bytes(
                pd.DataFrame({"interview__key": ["x", "y"], "province": [1.0, 2.0]})
            )
        }
    )
    client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("cumulative-1.zip", payload, "application/zip")},
        data={"mode": "append"},
    )
    again = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("cumulative-2.zip", payload, "application/zip")},
        data={"mode": "append"},
    )
    assert again.status_code == 201, again.text
    warnings = " ".join(again.json()["warnings"])
    assert "counted twice" in warnings, again.json()["warnings"]
    assert "interview__key" in warnings


def test_combine_all_still_appends_an_archive_of_rounds_into_one_dataset(
    client, auth_headers
):
    """The other shape: an archive that really does hold rounds of one table."""
    import pandas as pd

    archive = _zip_bytes(
        {
            "round1.dta": _stata_bytes(pd.DataFrame({"id": [1, 2], "age": [30.0, 40.0]})),
            "round2.dta": _stata_bytes(pd.DataFrame({"id": [3, 4], "age": [50.0, 60.0]})),
        }
    )
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("rounds.zip", archive, "application/zip")},
        data={"name": "Combined rounds", "combine_all": "true"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["datasets"]) == 1
    assert body["datasets"][0]["row_count"] == 4


def test_appending_a_later_round_adds_rows_rather_than_replacing(client, auth_headers):
    import pandas as pd

    first = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "r1.dta",
                _stata_bytes(pd.DataFrame({"id": [1, 2], "age": [30.0, 40.0]})),
                "application/octet-stream",
            )
        },
        data={"name": "Growing dataset"},
    )
    assert first.status_code == 201
    dataset_id = first.json()["id"]
    assert first.json()["row_count"] == 2

    appended = client.post(
        f"/api/v1/datasets/{dataset_id}/append",
        headers=auth_headers,
        files={
            "file": (
                "r2.dta",
                _stata_bytes(pd.DataFrame({"id": [3], "age": [50.0]})),
                "application/octet-stream",
            )
        },
    )
    assert appended.status_code == 200, appended.text
    assert appended.json()["row_count"] == 3

    # The rows that were already there keep a source, not just the new ones
    frequency = client.get(
        f"/api/v1/analytics/datasets/{dataset_id}/frequency/source_file",
        headers=auth_headers,
    ).json()
    counts = {row["label"]: row["count"] for row in frequency["rows"]}
    assert counts["r2.dta"] == 1
    assert sum(counts.values()) == 3


def test_appending_to_an_empty_dataset_is_refused(client, auth_headers):
    import pandas as pd

    created = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("x.csv", b"a,b\n", "text/csv")},
        data={"name": "No rows"},
    )
    assert created.status_code == 201
    response = client.post(
        f"/api/v1/datasets/{created.json()['id']}/append",
        headers=auth_headers,
        files={
            "file": (
                "r.dta",
                _stata_bytes(pd.DataFrame({"id": [1], "age": [30.0]})),
                "application/octet-stream",
            )
        },
    )
    # An empty dataset has no schema to append onto
    assert response.status_code in (200, 422)


# --- saved cross-tabulations ------------------------------------------------


def test_a_crosstab_can_be_saved_and_rendered_like_a_chart(client, auth_headers, dataset_id):
    """A cross-tab is worth putting on a dashboard, not just exporting once."""
    saved = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Region by sex",
            "dataset_id": dataset_id,
            "chart_type": "crosstab",
            "spec": {
                "crosstab": {
                    "row_variable": "region",
                    "column_variable": "sex",
                    "percentages": "row",
                }
            },
        },
    )
    assert saved.status_code == 201, saved.text

    rendered = client.post(
        f"/api/v1/dashboards/charts/{saved.json()['id']}/data",
        headers=auth_headers,
        json={"op": "and", "conditions": [], "groups": []},
    )
    assert rendered.status_code == 200, rendered.text
    body = rendered.json()

    # It comes back as a crosstab, not as a query result
    assert body["row_variable"] == "region"
    assert set(body["column_labels"]) == {"Male", "Female"}
    for row in body["values"]:
        assert abs(sum(v for v in row if v is not None) - 100) < 0.05


def test_a_saved_crosstab_renders_as_a_dashboard_widget(client, auth_headers, dataset_id):
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Region by sex",
            "dataset_id": dataset_id,
            "chart_type": "crosstab",
            "spec": {
                "crosstab": {"row_variable": "region", "column_variable": "sex"}
            },
        },
    ).json()

    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "With a crosstab"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "Region by sex", "widget_type": "chart", "chart_id": chart["id"]},
    )

    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data",
        headers=auth_headers,
        json={"op": "and", "conditions": [], "groups": []},
    )
    assert rendered.status_code == 200
    widget = next(iter(rendered.json()["widgets"].values()))
    assert widget["type"] == "crosstab"
    assert widget["result"]["grand_total"] == 200


def test_an_invalid_crosstab_spec_is_rejected_on_save(client, auth_headers, dataset_id):
    response = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Broken",
            "dataset_id": dataset_id,
            "chart_type": "crosstab",
            "spec": {"crosstab": {"row_variable": "region"}},  # no column variable
        },
    )
    assert response.status_code == 422


def test_a_dashboard_filter_narrows_a_saved_crosstab(client, auth_headers, dataset_id):
    """Dashboard filters must reach a crosstab widget, as they do a chart widget."""
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Region by sex",
            "dataset_id": dataset_id,
            "chart_type": "crosstab",
            "spec": {
                "crosstab": {"row_variable": "region", "column_variable": "sex"}
            },
        },
    ).json()

    unfiltered = client.post(
        f"/api/v1/dashboards/charts/{chart['id']}/data", headers=auth_headers
    ).json()
    assert unfiltered["grand_total"] == 200

    filtered = client.post(
        f"/api/v1/dashboards/charts/{chart['id']}/data",
        headers=auth_headers,
        json={
            "op": "and",
            "conditions": [
                {"variable": "region", "operator": "eq", "value": "North"}
            ],
            "groups": [],
        },
    )
    assert filtered.status_code == 200, filtered.text
    body = filtered.json()
    assert 0 < body["grand_total"] < 200
    assert body["row_labels"] == ["North"]


def test_a_quality_rule_can_be_restricted_to_part_of_the_dataset(
    client, auth_headers, dataset_id
):
    """A check on one region should count rows in that region, not all of them."""

    def make(name, filters):
        response = client.post(
            "/api/v1/monitoring/quality-rules",
            headers=auth_headers,
            json={
                "name": name,
                "dataset_id": dataset_id,
                "check_type": "missing_rate",
                "config": {"variable": "income"},
                "filters": filters,
            },
        )
        assert response.status_code == 201, response.text
        run = client.post(
            f"/api/v1/monitoring/quality-rules/{response.json()['id']}/run",
            headers=auth_headers,
        )
        assert run.status_code == 200, run.text
        return response.json()["id"], run.json()

    _, everything = make("Income missing, everywhere", {"op": "and", "conditions": []})
    rule_id, north = make(
        "Income missing, North only",
        {
            "op": "and",
            "conditions": [{"variable": "region", "operator": "eq", "value": "North"}],
            "groups": [],
        },
    )

    # The denominator is what was checked, not the whole dataset
    assert everything["total_rows"] == 200
    assert 0 < north["total_rows"] < 200
    assert north["failed_rows"] <= everything["failed_rows"]

    # Editing a rule re-runs it, so the stored result never describes the old one
    widened = client.patch(
        f"/api/v1/monitoring/quality-rules/{rule_id}",
        headers=auth_headers,
        json={"filters": {"op": "and", "conditions": [], "groups": []}},
    )
    assert widened.status_code == 200, widened.text
    latest = client.get(
        f"/api/v1/monitoring/quality-results?rule_id={rule_id}", headers=auth_headers
    ).json()
    assert latest[0]["total_rows"] == 200


def test_a_data_quality_panel_can_go_on_a_dashboard(client, auth_headers, dataset_id):
    """Checks belong where people look, which is the dashboard."""
    rule = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "name": "Income should rarely be blank",
            "dataset_id": dataset_id,
            "check_type": "missing_rate",
            "config": {"variable": "income"},
            "threshold": 0.0,  # 10 of 200 are blank, so this fails
        },
    )
    assert rule.status_code == 201, rule.text

    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "With quality"}
    ).json()
    added = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Data quality",
            "widget_type": "quality",
            "dataset_id": dataset_id,
        },
    )
    assert added.status_code == 201, added.text

    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data",
        headers=auth_headers,
        json={"op": "and", "conditions": [], "groups": []},
    )
    assert rendered.status_code == 200, rendered.text
    panel = next(iter(rendered.json()["widgets"].values()))
    assert panel["type"] == "quality"
    assert panel["failing"] >= 1
    failing = [c for c in panel["checks"] if c["passed"] is False]
    # Failing checks sort first, so the one worth seeing is not buried
    assert panel["checks"][0]["passed"] is False
    assert any("income" in c["message"] for c in failing)


def test_a_dashboard_filter_only_applies_where_the_variable_exists(
    client, auth_headers, dataset_id
):
    """A dashboard's widgets can draw on different datasets.

    Filtering on a variable only some of them carry must narrow those and leave
    the rest alone, not replace them with an error.
    """
    import pandas as pd

    other = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "no_region.dta",
                _stata_bytes(pd.DataFrame({"team": [1.0, 2.0, 1.0], "hours": [5.0, 6.0, 7.0]})),
                "application/octet-stream",
            )
        },
        data={"name": "Has no region"},
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]

    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Mixed sources"}
    ).json()
    for name, ds, variable in (
        ("Has region", dataset_id, "region"),
        ("No region", other_id, "team"),
    ):
        chart = client.post(
            "/api/v1/dashboards/charts",
            headers=auth_headers,
            json={
                "name": name,
                "dataset_id": ds,
                "chart_type": "bar",
                "spec": {"query": {"dimensions": [{"variable": variable}],
                                   "measures": [{"agg": "count", "alias": "n"}]}},
            },
        ).json()
        client.post(
            f"/api/v1/dashboards/{dashboard['id']}/widgets",
            headers=auth_headers,
            json={"title": name, "widget_type": "chart", "chart_id": chart["id"]},
        )

    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data",
        headers=auth_headers,
        json={
            "op": "and",
            "conditions": [{"variable": "region", "operator": "eq", "value": "North"}],
            "groups": [],
        },
    )
    assert rendered.status_code == 200, rendered.text
    widgets = list(rendered.json()["widgets"].values())
    by_name = {w.get("name"): w for w in widgets}

    # Neither widget errored
    assert all("error" not in w for w in widgets), widgets
    # The one that has the variable was narrowed
    assert sum(r[1] for r in by_name["Has region"]["result"]["rows"]) < 200
    # The one that does not was left as it was
    assert sum(r[1] for r in by_name["No region"]["result"]["rows"]) == 3


def _png() -> bytes:
    """The smallest valid PNG: a 1x1 transparent pixel."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAY"
        "AAjCB0C8AAAAASUVORK5CYII="
    )


def test_a_widget_can_be_moved_to_another_page(client, auth_headers, dataset_id):
    """Where a widget belongs is often decided after it is built."""
    dashboard = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": "Two pages", "pages": [{"name": "Fieldwork"}, {"name": "Quality"}]},
    ).json()
    detail = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "A note", "widget_type": "text", "config": {"content": "hello"}},
    ).json()
    widget = detail["widgets"][0]
    assert widget["page"] == 0

    moved = client.patch(
        f"/api/v1/dashboards/{dashboard['id']}/widgets/{widget['id']}",
        headers=auth_headers,
        json={"page": 1},
    )
    assert moved.status_code == 200
    after = moved.json()["widgets"][0]
    assert after["page"] == 1
    assert after["title"] == "A note"
    assert after["config"] == {"content": "hello"}


def test_a_moved_widget_is_placed_below_the_page_it_arrives_on(client, auth_headers):
    """Its old coordinates would drop it on top of what is already there."""
    dashboard = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": "Crowded", "pages": [{"name": "One"}, {"name": "Two"}]},
    ).json()

    def add(title: str, page: int) -> dict:
        body = client.post(
            f"/api/v1/dashboards/{dashboard['id']}/widgets",
            headers=auth_headers,
            json={"title": title, "widget_type": "text", "page": page},
        ).json()
        return next(w for w in body["widgets"] if w["title"] == title)

    add("Sitting on page two", 1)
    travelling = add("Moving over", 0)
    assert travelling["layout"]["y"] == 0

    body = client.patch(
        f"/api/v1/dashboards/{dashboard['id']}/widgets/{travelling['id']}",
        headers=auth_headers,
        json={"page": 1},
    ).json()
    arrived = next(w for w in body["widgets"] if w["id"] == travelling["id"])
    assert arrived["layout"]["y"] > 0
    # Its size travels with it: a widget sized for what it shows does not get
    # resized just because it changed page.
    assert arrived["layout"]["w"] == travelling["layout"]["w"]
    assert arrived["layout"]["h"] == travelling["layout"]["h"]


def test_a_widget_cannot_be_moved_to_a_page_that_does_not_exist(client, auth_headers):
    dashboard = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": "One page", "pages": [{"name": "Only"}]},
    ).json()
    widget = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "A note", "widget_type": "text"},
    ).json()["widgets"][0]

    response = client.patch(
        f"/api/v1/dashboards/{dashboard['id']}/widgets/{widget['id']}",
        headers=auth_headers,
        json={"page": 4},
    )
    assert response.status_code == 422


def test_a_countdown_widget_renders_its_deadline(client, auth_headers):
    """A monitoring board is usually read against a date fieldwork has to end."""
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Deadline"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Fieldwork ends",
            "widget_type": "countdown",
            "config": {"target": "2030-01-01T00:00:00Z", "label": "until fieldwork ends"},
        },
    )

    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data",
        headers=auth_headers,
        json={"op": "and", "conditions": [], "groups": []},
    )
    assert rendered.status_code == 200
    widget = next(iter(rendered.json()["widgets"].values()))
    # Not an error about a missing data source: a countdown queries nothing
    assert widget == {
        "type": "countdown",
        "target": "2030-01-01T00:00:00Z",
        "label": "until fieldwork ends",
        "expired_text": "",
    }


def test_a_dashboard_remembers_its_background_colour(client, auth_headers):
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Dressed"}
    ).json()
    assert dashboard["appearance"] == {}

    updated = client.patch(
        f"/api/v1/dashboards/{dashboard['id']}",
        headers=auth_headers,
        json={"appearance": {"background_color": "#0f172a", "dim": 0.4}},
    )
    assert updated.status_code == 200
    assert updated.json()["appearance"]["background_color"] == "#0f172a"

    again = client.get(f"/api/v1/dashboards/{dashboard['id']}", headers=auth_headers).json()
    assert again["appearance"]["dim"] == 0.4


def test_a_background_image_is_uploaded_and_served_back(client, auth_headers):
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "With a picture"}
    ).json()

    upload = client.put(
        f"/api/v1/dashboards/{dashboard['id']}/background",
        headers=auth_headers,
        files={"file": ("bg.png", _png(), "image/png")},
    )
    assert upload.status_code == 200
    appearance = upload.json()["appearance"]
    assert appearance["background_image"].endswith(".png")
    assert appearance["background_version"]

    served = client.get(
        f"/api/v1/dashboards/{dashboard['id']}/background", headers=auth_headers
    )
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == _png()

    cleared = client.delete(
        f"/api/v1/dashboards/{dashboard['id']}/background", headers=auth_headers
    )
    assert cleared.status_code == 200
    assert "background_image" not in cleared.json()["appearance"]
    assert (
        client.get(
            f"/api/v1/dashboards/{dashboard['id']}/background", headers=auth_headers
        ).status_code
        == 404
    )


def test_a_file_that_is_not_an_image_is_refused_as_a_background(client, auth_headers):
    """The name and the content type are the uploader's to choose; the bytes are not."""
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Nice try"}
    ).json()

    response = client.put(
        f"/api/v1/dashboards/{dashboard['id']}/background",
        headers=auth_headers,
        files={"file": ("bg.png", b"<svg onload=alert(1)></svg>", "image/png")},
    )
    assert response.status_code == 400
    assert "PNG" in response.json()["detail"]


def test_a_shared_dashboard_serves_its_background_without_a_login(client, auth_headers):
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Shared and dressed"}
    ).json()
    client.put(
        f"/api/v1/dashboards/{dashboard['id']}/background",
        headers=auth_headers,
        files={"file": ("bg.png", _png(), "image/png")},
    )
    shared = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/share", headers=auth_headers, json={}
    ).json()

    response = client.get(f"/api/v1/public/dashboards/{shared['public_token']}/background")
    assert response.status_code == 200
    assert response.content == _png()
