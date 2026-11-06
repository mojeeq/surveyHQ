"""What an anonymous visitor may ask a shared dashboard.

A dashboard's widgets are drawn from a whole dataset, and a filter is evaluated
against that dataset rather than against the widget. So an unrestricted filter
on a public link is a question about any column in the file, including the ones
the dashboard deliberately does not show, and a count is an answer: filter to a
single respondent's identifier and the tile says whether that person is in the
data. Repeat and the link becomes a lookup service for a file nobody agreed to
publish.

What the dashboard already displays is different in kind. Filtering by a
category the visitor can read off an axis tells them nothing the page did not
already show them, and it is the only filter the shared UI can produce - a
click on a bar.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def shared_dashboard(client, auth_headers, dataset_id) -> dict:
    """A public dashboard whose one chart groups by region and nothing else."""
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
    )
    assert chart.status_code == 201, chart.text

    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Public figures"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "By region",
            "widget_type": "chart",
            "chart_id": chart.json()["id"],
        },
    )
    shared = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/share?enable=true", headers=auth_headers
    ).json()
    return {"id": dashboard["id"], "token": shared["public_token"]}


def _one_widget(payload: dict) -> dict:
    return next(iter(payload["widgets"].values()))


def _row_count(response) -> int:
    assert response.status_code == 200, response.text
    return _one_widget(response.json())["result"]["row_count"]


def test_a_visitor_may_filter_by_what_the_dashboard_shows(client, shared_dashboard):
    """Click-to-filter still works: region is on the chart's own axis."""
    unfiltered = _row_count(
        client.post(f"/api/v1/public/dashboards/{shared_dashboard['token']}/data")
    )
    filtered = _row_count(
        client.post(
            f"/api/v1/public/dashboards/{shared_dashboard['token']}/data",
            json={
                "op": "and",
                "conditions": [
                    {"variable": "region", "operator": "eq", "value": "North"}
                ],
            },
        )
    )
    assert unfiltered > 1
    assert filtered == 1  # one region left, so one bar


def test_a_visitor_may_not_filter_by_a_column_the_dashboard_hides(
    client, shared_dashboard
):
    """The attack: interview__key is in the dataset but on no widget.

    The filter is dropped rather than refused. Refusing would answer the
    question it was asked - a 422 for a column that exists and a different
    error for one that does not is itself the lookup - and no honest visitor
    can send this, because the shared page has no way to compose it.
    """
    baseline = _row_count(
        client.post(f"/api/v1/public/dashboards/{shared_dashboard['token']}/data")
    )
    probed = _row_count(
        client.post(
            f"/api/v1/public/dashboards/{shared_dashboard['token']}/data",
            json={
                "op": "and",
                "conditions": [
                    {
                        "variable": "interview__key",
                        "operator": "eq",
                        "value": "key-0001",
                    }
                ],
            },
        )
    )
    assert probed == baseline


def test_a_hidden_column_inside_a_nested_group_is_dropped_too(
    client, shared_dashboard
):
    """A filter tree is pruned all the way down, not just at the top level."""
    baseline = _row_count(
        client.post(f"/api/v1/public/dashboards/{shared_dashboard['token']}/data")
    )
    probed = _row_count(
        client.post(
            f"/api/v1/public/dashboards/{shared_dashboard['token']}/data",
            json={
                "op": "and",
                "conditions": [],
                "groups": [
                    {
                        "op": "or",
                        "conditions": [
                            {
                                "variable": "interview__key",
                                "operator": "eq",
                                "value": "key-0001",
                            }
                        ],
                    }
                ],
            },
        )
    )
    assert probed == baseline


def test_a_signed_in_analyst_keeps_the_whole_filter_grammar(
    client, auth_headers, shared_dashboard
):
    """The restriction belongs to the public link, not to the dashboard.

    Someone signed in already has the dataset; narrowing what they may ask of
    a dashboard built on it would protect nothing and take away a real tool.
    """
    response = client.post(
        f"/api/v1/dashboards/{shared_dashboard['id']}/data",
        headers=auth_headers,
        json={
            "op": "and",
            "conditions": [
                {"variable": "interview__key", "operator": "eq", "value": "key-0001"}
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert _one_widget(response.json())["result"]["row_count"] == 1


def _total(response) -> float:
    """The sum of the one chart's counts, which a filter should reduce."""
    assert response.status_code == 200, response.text
    result = _one_widget(response.json())["result"]
    return sum(row[-1] for row in result["rows"])


def test_a_filter_control_the_author_added_still_works(
    client, auth_headers, shared_dashboard, dataset_id
):
    """The dashboard's own filter bar is a publishing decision, like an axis.

    An author who puts a "sex" dropdown on a public dashboard has chosen to
    offer that question, and no widget need group by it. Left out of the
    allowance, the control would render and then quietly do nothing - which is
    how a security fix becomes a bug report about a broken filter.
    """
    patched = client.patch(
        f"/api/v1/dashboards/{shared_dashboard['id']}",
        headers=auth_headers,
        json={"filters": [{"variable": "sex", "dataset_id": dataset_id}]},
    )
    assert patched.status_code == 200, patched.text

    url = f"/api/v1/public/dashboards/{shared_dashboard['token']}/data"
    everyone = _total(client.post(url))
    one_sex = _total(
        client.post(
            url,
            json={
                "op": "and",
                "conditions": [{"variable": "sex", "operator": "eq", "value": 1}],
            },
        )
    )
    assert 0 < one_sex < everyone
