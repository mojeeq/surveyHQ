"""A shared link's filter dropdowns have to have something in them.

The reported fault: copy a dashboard link, open it in a new tab, and the
filters sometimes offer no options. "Sometimes" was whether that browser
happened to be signed in already - the dropdown asked the dataset endpoint for
its values, and that needs an account, so a reader who had one saw a full list
and everybody else saw an empty box.

The values now come from the dashboard, which answers for the controls its
author put on it and for nothing else. That is the same allowance the shared
render already applies to filters arriving from outside: a choice the page was
built to offer reveals nothing the page does not.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def shared(client, auth_headers, dataset_id) -> dict:
    """A shared dashboard with a region filter on it."""
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "By region",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dataset_id": dataset_id,
                    "dimensions": [{"variable": "region"}],
                    "measures": [{"agg": "count"}],
                }
            },
        },
    ).json()
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Shared filters"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "By region", "widget_type": "chart", "chart_id": chart["id"]},
    )
    saved = client.patch(
        f"/api/v1/dashboards/{dashboard['id']}",
        headers=auth_headers,
        json={
            "filters": [
                {"variable": "region", "dataset_id": dataset_id, "label": "Province"}
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    token = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/share?enable=true", headers=auth_headers
    ).json()["public_token"]
    return {"id": dashboard["id"], "token": token, "dataset_id": dataset_id}


def test_a_visitor_with_no_account_gets_the_dropdown_s_options(client, shared):
    """The fault, from the position the reader of a copied link is actually in."""
    response = client.get(f"/api/v1/public/dashboards/{shared['token']}/filter-values/region")
    assert response.status_code == 200, response.text
    values = {str(item["value"]) for item in response.json()}
    assert values == {"North", "South"}


def test_the_dataset_endpoint_still_needs_an_account(client, shared):
    """Which is why the values could not come from there. Unchanged, deliberately."""
    assert (
        client.get(
            f"/api/v1/datasets/{shared['dataset_id']}/variables/region/values"
        ).status_code
        == 401
    )


def test_only_a_variable_the_author_put_a_control_on_is_answered(client, shared):
    """The dashboard is not a way to read columns it does not show."""
    assert (
        client.get(f"/api/v1/public/dashboards/{shared['token']}/filter-values/age").status_code
        == 404
    )


def test_a_signed_in_reader_asks_the_same_way(client, auth_headers, shared):
    response = client.get(
        f"/api/v1/dashboards/{shared['id']}/filter-values/region", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert {str(item["value"]) for item in response.json()} == {"North", "South"}


def test_someone_else_s_dashboard_is_not_readable_by_id(client, shared):
    assert (
        client.get(f"/api/v1/dashboards/{shared['id']}/filter-values/region").status_code
        == 401
    )
