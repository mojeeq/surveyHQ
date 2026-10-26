"""Other ways to read a "tick all that apply" question.

One bar per option answers what was chosen. The same columns also answer how
the choices differ between groups, which options go together, and how many
each respondent chose - and each of those is a different chart. Pinned here
against the six households of the multi fixture, worked by hand:

    h1  piped, rain          Northern
    h2  piped                Northern
    h3  well, rain           Southern
    h4  rain, river          Southern
    h5  piped, well, rain    Northern
    h6  nothing              Southern
"""

from __future__ import annotations

import pytest

from tests.test_multiselect import BASE, multi  # noqa: F401 - a fixture


def view(client, auth_headers, dataset_id, **body):
    response = client.post(
        f"{BASE}/{dataset_id}/multiselect",
        headers=auth_headers,
        json={"columns": ["water__1", "water__2", "water__3", "water__4"], **body},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_by_group_is_a_share_of_each_groups_own_respondents(client, auth_headers, multi):  # noqa: F811
    result = view(client, auth_headers, multi, view="by_group", by="province", show="both")
    assert [c["name"] for c in result["columns"]] == ["option", "group", "chose", "percent"]
    cells = {(row[0], row[1]): (row[2], row[3]) for row in result["rows"]}
    # Three households in each province: all three Northern ones have piped
    # water, none of the Southern ones do.
    assert cells[("Option 1", "Northern")] == (3, 100.0)
    assert cells[("Option 1", "Southern")] == (0, 0.0)
    assert cells[("Option 3", "Northern")] == (2, 66.7)
    assert cells[("Option 4", "Southern")] == (1, 33.3)
    # Options most chosen overall first, each with its groups in order.
    assert [row[0] for row in result["rows"][::2]] == [
        "Option 3", "Option 1", "Option 2", "Option 4"
    ]
    assert result["total_rows_scanned"] == 6


def test_by_group_needs_a_variable_that_is_not_an_option(client, auth_headers, multi):  # noqa: F811
    for by, said in (("", "Choose the variable"), ("water__1", "is one of the options")):
        response = client.post(
            f"{BASE}/{multi}/multiselect",
            headers=auth_headers,
            json={"columns": ["water__1", "water__2"], "view": "by_group", "by": by},
        )
        assert response.status_code == 400
        assert said in response.json()["detail"]


def test_combinations_add_to_every_respondent(client, auth_headers, multi):  # noqa: F811
    result = view(client, auth_headers, multi, view="combinations", show="both", top=3)
    assert [row[0] for row in result["rows"]] == [
        "None of these",
        "Option 1 only",
        "Option 1 + Option 2 + Option 3",
        "Other combinations (3)",
    ]
    # Each household has exactly one combination, so these make the whole.
    assert sum(row[1] for row in result["rows"]) == 6
    assert result["rows"][-1][1:] == [3, 50.0]


def test_how_many_counts_each_respondents_choices_in_order(client, auth_headers, multi):  # noqa: F811
    result = view(client, auth_headers, multi, view="how_many", show="both")
    assert result["columns"][0]["data_type"] == "numeric"
    assert result["rows"] == [[0, 1, 16.7], [1, 1, 16.7], [2, 3, 50.0], [3, 1, 16.7]]


def test_together_reads_across_from_those_who_chose_one(client, auth_headers, multi):  # noqa: F811
    result = view(client, auth_headers, multi, view="together", show="both")
    cells = {(row[0], row[1]): (row[2], row[3]) for row in result["rows"]}
    # Of the three with piped water, two collect rain too...
    assert cells[("Option 1", "Option 3")] == (2, 66.7)
    # ...and of the four who collect rain, two have piped water: not the same.
    assert cells[("Option 3", "Option 1")] == (2, 50.0)
    assert cells[("Option 3", "Option 4")] == (1, 25.0)
    # Its own option is left empty rather than a hundred per cent.
    assert cells[("Option 1", "Option 1")] == (3, None)
    assert len(result["rows"]) == 16


def test_the_shares_say_they_are_shares(client, auth_headers, multi):  # noqa: F811
    """So a chart does not fold the ninth group into a sum of percentages."""
    for name in ("options", "by_group", "combinations", "how_many", "together"):
        result = view(client, auth_headers, multi, view=name, by="province", show="percent")
        assert result["columns"][-1]["data_type"] == "percent", name


@pytest.mark.parametrize("name", ["by_group", "combinations", "how_many", "together"])
def test_each_view_renders_as_a_dashboard_widget(client, auth_headers, multi, name):  # noqa: F811
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": f"Water {name}",
            "dataset_id": multi,
            "chart_type": "heatmap" if name in ("by_group", "together") else "horizontal_bar",
            "spec": {
                "multiselect": {
                    "columns": ["water__1", "water__2", "water__3", "water__4"],
                    "view": name,
                    "by": "province",
                    "show": "percent",
                }
            },
        },
    )
    assert chart.status_code == 201, chart.text
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": f"Water {name}"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "Water", "widget_type": "chart", "chart_id": chart.json()["id"]},
    )
    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data",
        headers=auth_headers,
        json={
            "op": "and",
            "conditions": [{"variable": "province", "operator": "eq", "value": "Northern"}],
            "groups": [],
        },
    )
    assert rendered.status_code == 200, rendered.text
    payload = next(iter(rendered.json()["widgets"].values()))
    assert payload["type"] == "chart", payload
    # The page's filter reaches every view: three Northern households.
    assert payload["result"]["total_rows_scanned"] == 3
