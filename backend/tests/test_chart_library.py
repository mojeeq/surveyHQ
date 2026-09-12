from __future__ import annotations


def test_chart_library_reports_and_filters_source_context(client, auth_headers):
    project = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Chart library scope"},
    )
    assert project.status_code == 201, project.text
    project = project.json()

    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "chart-library.csv",
                b"region,value\nCentral,1\nWestern,2\n",
                "text/csv",
            )
        },
        data={
            "name": "Chart library dataset",
            "project_id": project["id"],
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    dataset = uploaded.json()

    created = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Chart library test",
            "dataset_id": dataset["id"],
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "region"}],
                    "measures": [{"agg": "count", "alias": "count"}],
                    "filters": {"op": "and", "conditions": [], "groups": []},
                    "sort": [],
                    "limit": 50,
                    "use_labels": True,
                    "drop_missing": False,
                }
            },
        },
    )
    assert created.status_code == 201, created.text
    chart = created.json()

    response = client.get(
        "/api/v1/dashboards/chart-library",
        headers=auth_headers,
        params={"project_id": project["id"]},
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    row = next(item for item in rows if item["id"] == chart["id"])
    assert row["dataset_id"] == dataset["id"]
    assert row["dataset_name"] == "Chart library dataset"
    assert row["project_id"] == project["id"]
    assert row["project_name"] == "Chart library scope"

    shared = client.get(
        "/api/v1/dashboards/chart-library",
        headers=auth_headers,
        params={"project_id": "none"},
    )
    assert shared.status_code == 200, shared.text
    assert chart["id"] not in {item["id"] for item in shared.json()}

    client.delete(
        f"/api/v1/projects/{project['id']}",
        headers=auth_headers,
        params={"contents": "delete"},
    )
