"""Moving and deleting dashboard pages.

A widget records which page it is on as an index into the page list, so both
halves have to move together. Deleting a page used to renumber neither, which
left every widget after the hole on the page that took its old number.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def dashboard(client, auth_headers) -> dict:
    created = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={
            "name": "Three pages",
            "pages": [{"name": "Fieldwork"}, {"name": "Quality"}, {"name": "Coverage"}],
        },
    )
    assert created.status_code == 201, created.text
    detail = created.json()
    # One text widget per page, named for the page it starts on.
    for index, page in enumerate(["Fieldwork", "Quality", "Coverage"]):
        added = client.post(
            f"/api/v1/dashboards/{detail['id']}/widgets",
            headers=auth_headers,
            json={
                "widget_type": "text",
                "title": page,
                "page": index,
                "config": {"text": page},
            },
        )
        assert added.status_code == 201, added.text
    yield client.get(f"/api/v1/dashboards/{detail['id']}", headers=auth_headers).json()
    client.delete(f"/api/v1/dashboards/{detail['id']}", headers=auth_headers)


def _placement(detail: dict) -> dict[str, str]:
    """Which page name each widget sits on, by the widget's own title."""
    pages = [page.get("name") for page in detail["pages"]]
    return {w["title"]: pages[w.get("page") or 0] for w in detail["widgets"]}


def test_a_page_takes_its_widgets_with_it(client, auth_headers, dashboard):
    before = _placement(dashboard)
    assert before == {"Fieldwork": "Fieldwork", "Quality": "Quality", "Coverage": "Coverage"}

    moved = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/pages/move",
        headers=auth_headers,
        json={"from": 0, "to": 2},
    )
    assert moved.status_code == 200, moved.text
    detail = moved.json()
    assert [p["name"] for p in detail["pages"]] == ["Quality", "Coverage", "Fieldwork"]
    # Every widget is still on the page it started on, wherever that page went.
    assert _placement(detail) == before


@pytest.mark.parametrize("source,target", [(0, 1), (2, 0), (1, 2), (0, 2), (2, 1)])
def test_every_move_keeps_every_widget_on_its_own_page(
    client, auth_headers, dashboard, source, target
):
    moved = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/pages/move",
        headers=auth_headers,
        json={"from": source, "to": target},
    )
    assert moved.status_code == 200, moved.text
    assert _placement(moved.json()) == {
        "Fieldwork": "Fieldwork",
        "Quality": "Quality",
        "Coverage": "Coverage",
    }


def test_deleting_a_page_renumbers_the_ones_after_it(client, auth_headers, dashboard):
    """The old bug: the pages closed up and the widgets did not follow."""
    # Empty the middle page so it may be deleted.
    quality = next(w for w in dashboard["widgets"] if w["title"] == "Quality")
    client.delete(
        f"/api/v1/dashboards/{dashboard['id']}/widgets/{quality['id']}", headers=auth_headers
    )

    deleted = client.delete(
        f"/api/v1/dashboards/{dashboard['id']}/pages/1", headers=auth_headers
    )
    assert deleted.status_code == 200, deleted.text
    detail = deleted.json()
    assert [p["name"] for p in detail["pages"]] == ["Fieldwork", "Coverage"]
    assert _placement(detail) == {"Fieldwork": "Fieldwork", "Coverage": "Coverage"}


def test_a_page_with_widgets_on_it_is_not_deleted(client, auth_headers, dashboard):
    refused = client.delete(
        f"/api/v1/dashboards/{dashboard['id']}/pages/1", headers=auth_headers
    )
    assert refused.status_code == 409, refused.text


def test_the_last_page_stays(client, auth_headers):
    created = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "One page"}
    ).json()
    refused = client.delete(
        f"/api/v1/dashboards/{created['id']}/pages/0", headers=auth_headers
    )
    assert refused.status_code == 409, refused.text
    client.delete(f"/api/v1/dashboards/{created['id']}", headers=auth_headers)


def test_a_click_filter_leaves_the_widget_it_was_clicked_on_alone(
    client, auth_headers, dataset_id
):
    """Cross-filtering: every widget narrows except the one holding the marks.

    Narrowing the clicked chart to the one bar just chosen would take away the
    means of choosing another, so it renders unfiltered while the rest follow.
    """
    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    grouping = next(
        v for v in detail["variables"] if v["var_type"] == "categorical" and v["n_unique"] > 1
    )
    values = client.get(
        f"/api/v1/datasets/{dataset_id}/variables/{grouping['name']}/values",
        headers=auth_headers,
    ).json()
    chosen = str(values[0]["label"] or values[0]["value"])

    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "By category",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": grouping["name"]}],
                    "measures": [{"agg": "count", "alias": "n"}],
                    "limit": 100,
                }
            },
        },
    ).json()

    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Click filter"}
    ).json()
    ids = []
    for title in ("Clicked", "Follows"):
        added = client.post(
            f"/api/v1/dashboards/{dashboard['id']}/widgets",
            headers=auth_headers,
            json={"widget_type": "chart", "title": title, "chart_id": chart["id"]},
        )
        assert added.status_code == 201, added.text
        ids.append(added.json()["widgets"][-1]["id"])
    clicked, follows = ids

    filters = {
        "op": "and",
        "conditions": [
            {"variable": grouping["name"], "operator": "eq", "value": chosen, "use_label": True}
        ],
        "groups": [],
    }
    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data",
        headers=auth_headers,
        json=filters,
        params={"every_widget_but": clicked},
    )
    assert rendered.status_code == 200, rendered.text
    widgets = rendered.json()["widgets"]

    # The one that was clicked still shows every category to click next.
    assert len(widgets[clicked]["result"]["rows"]) == len(
        client.post(
            f"/api/v1/dashboards/{dashboard['id']}/data", headers=auth_headers, json={}
        ).json()["widgets"][clicked]["result"]["rows"]
    )
    # The other one is down to the category that was clicked.
    assert len(widgets[follows]["result"]["rows"]) == 1

    # The chart says what it groups on, which is how a click knows what it means.
    assert widgets[clicked]["grouped_on"] == [grouping["name"]]

    client.delete(f"/api/v1/dashboards/{dashboard['id']}", headers=auth_headers)
    client.delete(f"/api/v1/dashboards/charts/{chart['id']}", headers=auth_headers)
