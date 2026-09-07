"""A "tick all that apply" question, tabulated from the columns it arrived as.

Survey Solutions does not export a multiple-select as one column. It writes one
per option - toilet__1, toilet__2, toilet__3 - each holding 1 where the option
was chosen. Every tool here tabulates one variable at a time, so the question
that was actually asked could not be charted: you could count how many
households ticked option 2, one option at a time, and never see the question.

The shares add to more than 100 on purpose. More than one answer is allowed,
which is the whole point of the question.
"""

from __future__ import annotations

import pytest

BASE = "/api/v1/analytics/datasets"


@pytest.fixture
def multi(client, auth_headers) -> str:
    """Six households and what each one has: water from more than one source."""
    rows = [
        # key, piped, well, rain, river, province
        ("h1", 1, 0, 1, 0, "Shefa"),
        ("h2", 1, 0, 0, 0, "Shefa"),
        ("h3", 0, 1, 1, 0, "Tafea"),
        ("h4", 0, 0, 1, 1, "Tafea"),
        ("h5", 1, 1, 1, 0, "Shefa"),
        # Asked and chose nothing: still a respondent.
        ("h6", 0, 0, 0, 0, "Tafea"),
    ]
    body = "interview__key,water__1,water__2,water__3,water__4,province\n" + "\n".join(
        ",".join(str(value) for value in row) for row in rows
    )
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("water.csv", body.encode(), "text/csv")},
    )
    assert response.status_code in (200, 201), response.text
    payload = response.json()
    return (payload["datasets"][0] if "datasets" in payload else payload)["id"]


def tabulate(client, auth_headers, dataset_id, **body):
    response = client.post(
        f"{BASE}/{dataset_id}/multiselect",
        headers=auth_headers,
        json={"columns": ["water__1", "water__2", "water__3", "water__4"], **body},
    )
    assert response.status_code == 200, response.text
    return response.json()


def counts(result) -> dict[str, int]:
    return {row[0]: row[1] for row in result["rows"]}


def shares(result) -> dict[str, float]:
    return {row[0]: row[2] for row in result["rows"]}


def test_each_option_is_counted_across_its_own_column(client, auth_headers, multi):
    """The fault this exists for: one row per option, not one column at a time."""
    result = tabulate(client, auth_headers, multi)
    assert counts(result) == {
        "Option 1": 3,
        "Option 2": 2,
        "Option 3": 4,
        "Option 4": 1,
    }


def test_the_shares_are_of_respondents_and_may_pass_one_hundred(
    client, auth_headers, multi
):
    """Six households, ten answers between them. That is the question working."""
    result = tabulate(client, auth_headers, multi)
    assert result["total_rows_scanned"] == 6
    assert shares(result)["Option 3"] == pytest.approx(66.7, abs=0.1)
    assert sum(shares(result).values()) > 100


def test_the_options_are_ordered_by_how_often_they_were_chosen(
    client, auth_headers, multi
):
    result = tabulate(client, auth_headers, multi)
    assert [row[0] for row in result["rows"]] == [
        "Option 3",
        "Option 1",
        "Option 2",
        "Option 4",
    ]
    ascending = tabulate(client, auth_headers, multi, sort="value_asc")
    assert [row[1] for row in ascending["rows"]] == [1, 2, 3, 4]


def test_a_filter_narrows_the_respondents_and_the_base_with_them(
    client, auth_headers, multi
):
    """Filtering to one province must move the denominator, not only the counts."""
    result = tabulate(
        client,
        auth_headers,
        multi,
        filters={
            "op": "and",
            "conditions": [{"variable": "province", "operator": "eq", "value": "Shefa"}],
            "groups": [],
        },
    )
    assert result["total_rows_scanned"] == 3
    assert counts(result)["Option 1"] == 3
    assert shares(result)["Option 1"] == pytest.approx(100.0, abs=0.1)


def test_the_sets_of_columns_are_found_for_the_person_building_the_chart(
    client, auth_headers, multi
):
    response = client.get(f"{BASE}/{multi}/multiselect-groups", headers=auth_headers)
    assert response.status_code == 200, response.text
    found = {group["stem"]: group["columns"] for group in response.json()}
    assert found["water"] == ["water__1", "water__2", "water__3", "water__4"]


def test_a_variable_that_merely_ends_in_a_digit_is_not_a_group(
    client, auth_headers, dataset_id
):
    """One underscore is a name; two and a number is Survey Solutions' convention."""
    response = client.get(f"{BASE}/{dataset_id}/multiselect-groups", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_a_column_that_is_not_in_the_dataset_is_refused(client, auth_headers, multi):
    response = client.post(
        f"{BASE}/{multi}/multiselect",
        headers=auth_headers,
        json={"columns": ["water__1", "nonsense__9"]},
    )
    assert response.status_code == 400
    assert "nonsense__9" in response.json()["detail"]


def test_no_columns_at_all_is_refused(client, auth_headers, multi):
    response = client.post(
        f"{BASE}/{multi}/multiselect", headers=auth_headers, json={"columns": []}
    )
    assert response.status_code == 400


def test_it_renders_as_a_dashboard_widget(client, auth_headers, multi):
    """Saved as a chart, it has to draw on a board like any other."""
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Water sources",
            "dataset_id": multi,
            "chart_type": "bar",
            "spec": {
                "multiselect": {
                    "columns": ["water__1", "water__2", "water__3", "water__4"],
                    "percent_of": "respondents",
                    "sort": "value_desc",
                }
            },
        },
    )
    assert chart.status_code == 201, chart.text

    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Water"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "Water sources", "widget_type": "chart", "chart_id": chart.json()["id"]},
    )
    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data", headers=auth_headers, json={}
    )
    assert rendered.status_code == 200, rendered.text
    payload = next(iter(rendered.json()["widgets"].values()))
    assert payload["type"] == "chart"
    assert {row[0]: row[1] for row in payload["result"]["rows"]}["Option 3"] == 4
    # No variable behind the categories, so nothing for a click to filter by.
    assert payload["grouped_on"] == []


def test_a_dashboard_filter_reaches_it(client, auth_headers, multi):
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Water by province",
            "dataset_id": multi,
            "chart_type": "bar",
            "spec": {"multiselect": {"columns": ["water__1", "water__2"]}},
        },
    ).json()
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Filtered water"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "Water", "widget_type": "chart", "chart_id": chart["id"]},
    )
    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data",
        headers=auth_headers,
        json={
            "op": "and",
            "conditions": [{"variable": "province", "operator": "eq", "value": "Tafea"}],
            "groups": [],
        },
    )
    assert rendered.status_code == 200, rendered.text
    payload = next(iter(rendered.json()["widgets"].values()))
    assert payload["result"]["total_rows_scanned"] == 3
    assert {row[0]: row[1] for row in payload["result"]["rows"]}["Option 1"] == 0


def test_a_chart_can_ask_for_one_number_rather_than_both(client, auth_headers, multi):
    """A count in the hundreds beside a percentage under one is two scales.

    Drawn together the second series lies flat on the axis, so a bar chart asks
    for the one it is drawing. A table is the case that wants both, which is
    why both is what it does when nothing says otherwise.
    """
    both = tabulate(client, auth_headers, multi)
    assert [column["name"] for column in both["columns"]] == ["option", "chose", "percent"]

    only_counts = tabulate(client, auth_headers, multi, show="count")
    assert [column["name"] for column in only_counts["columns"]] == ["option", "chose"]
    assert {row[0]: row[1] for row in only_counts["rows"]}["Option 3"] == 4

    only_shares = tabulate(client, auth_headers, multi, show="percent")
    assert [column["name"] for column in only_shares["columns"]] == ["option", "percent"]
    assert {row[0]: row[1] for row in only_shares["rows"]}["Option 3"] == pytest.approx(
        66.7, abs=0.1
    )
