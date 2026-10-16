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
        ("h1", 1, 0, 1, 0, "Northern"),
        ("h2", 1, 0, 0, 0, "Northern"),
        ("h3", 0, 1, 1, 0, "Southern"),
        ("h4", 0, 0, 1, 1, "Southern"),
        ("h5", 1, 1, 1, 0, "Northern"),
        # Asked and chose nothing: still a respondent.
        ("h6", 0, 0, 0, 0, "Southern"),
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
            "conditions": [{"variable": "province", "operator": "eq", "value": "Northern"}],
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
    # Not grouped on a variable: each category is a column of its own. The map
    # beside it is what a click reads instead.
    assert payload["grouped_on"] == []
    assert payload["option_columns"]["Option 3"] == "water__3"


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
            "conditions": [{"variable": "province", "operator": "eq", "value": "Southern"}],
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


# --- naming the options ----------------------------------------------------
#
# "Option 8" on a bar sends the reader to the questionnaire to find out what
# option 8 was, which is the opposite of what a chart is for. The words are
# usually in the file; they were simply not being read.


def _dta(frame, path, **kwargs) -> bytes:
    import pyreadstat

    pyreadstat.write_dta(frame, str(path), **kwargs)
    return path.read_bytes()


def _upload(client, auth_headers, name: str, content: bytes) -> str:
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": (name, content, "application/octet-stream")},
    )
    assert response.status_code in (200, 201), response.text
    payload = response.json()
    return (payload["datasets"][0] if "datasets" in payload else payload)["id"]


def variables_of(client, auth_headers, dataset_id) -> dict[str, str]:
    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    return {v["name"]: v["label"] for v in detail["variables"]}


def test_the_questions_own_codes_name_its_options(client, auth_headers, tmp_path):
    """Where the option text actually lives in a Survey Solutions export.

    The columns are hhld_goods__1 to __3 and carry no labels of their own. The
    file still knows what those codes mean: it has a value-label set named
    after the question, where 1 is Radio and 3 is Bicycle - and the number in
    the column name IS that code. Nothing was reading it, so the chart came out
    numbered.
    """
    import pandas as pd

    frame = pd.DataFrame(
        {
            "hhld_goods__1": [1, 0, 1],
            "hhld_goods__2": [0, 1, 1],
            "hhld_goods__3": [1, 1, 0],
            # The question's own column, holding the codes, which is what
            # puts the set into the file under the question's name.
            "hhld_goods": [1, 2, 3],
        }
    )
    path = tmp_path / "goods.dta"
    content = _dta(
        frame,
        path,
        variable_value_labels={"hhld_goods": {1: "Radio", 2: "Television", 3: "Bicycle"}},
    )
    dataset_id = _upload(client, auth_headers, "hhld_goods.dta", content)

    labels = variables_of(client, auth_headers, dataset_id)
    assert labels["hhld_goods__1"] == "Radio"
    assert labels["hhld_goods__2"] == "Television"
    assert labels["hhld_goods__3"] == "Bicycle"

    # And so the chart is drawn under those names rather than numbers.
    result = client.post(
        f"{BASE}/{dataset_id}/multiselect",
        headers=auth_headers,
        json={"columns": ["hhld_goods__1", "hhld_goods__2", "hhld_goods__3"]},
    ).json()
    assert set(counts(result)) == {"Radio", "Television", "Bicycle"}


def test_a_set_that_does_not_hold_the_codes_is_not_used(client, auth_headers, tmp_path):
    """A name in common is not enough: it has to answer for the options.

    A set holding only 1 and 2 cannot name nineteen options, and naming two of
    them while the rest stay numbered would read as though the file disagreed
    with itself.
    """
    import pandas as pd

    frame = pd.DataFrame(
        {
            "toilet__1": [1, 0],
            "toilet__2": [0, 1],
            "toilet__3": [1, 1],
            "toilet__4": [0, 1],
            "flag": [1, 2],
        }
    )
    path = tmp_path / "toilet.dta"
    content = _dta(frame, path, variable_value_labels={"flag": {1: "Yes", 2: "No"}})
    dataset_id = _upload(client, auth_headers, "toilet.dta", content)
    labels = variables_of(client, auth_headers, dataset_id)
    assert not labels["toilet__1"]
    assert not labels["toilet__3"]


def test_a_label_the_file_carries_is_never_overwritten(client, auth_headers, tmp_path):
    """A file that names its options knows better than this does."""
    import pandas as pd

    frame = pd.DataFrame({"crop__1": [1, 0], "crop__2": [0, 1], "crop": [1, 2]})
    path = tmp_path / "crop.dta"
    content = _dta(
        frame,
        path,
        column_labels={"crop__1": "Kava", "crop__2": "", "crop": ""},
        variable_value_labels={"crop": {1: "Taro", 2: "Yam"}},
    )
    dataset_id = _upload(client, auth_headers, "crop.dta", content)
    labels = variables_of(client, auth_headers, dataset_id)
    # Its own label stands; the one with none is filled in from the codes.
    assert labels["crop__1"] == "Kava"
    assert labels["crop__2"] == "Yam"


def test_a_labelled_yes_no_column_does_not_name_every_bar_yes(
    client, auth_headers, tmp_path
):
    """Some exports label the tick rather than the thing ticked."""
    import pandas as pd

    frame = pd.DataFrame({"asset__1": [1, 0], "asset__2": [0, 1]})
    path = tmp_path / "asset.dta"
    content = _dta(
        frame,
        path,
        variable_value_labels={
            "asset__1": {0: "Not selected", 1: "Yes"},
            "asset__2": {0: "Not selected", 1: "Solar panel"},
        },
    )
    dataset_id = _upload(client, auth_headers, "asset.dta", content)
    result = client.post(
        f"{BASE}/{dataset_id}/multiselect",
        headers=auth_headers,
        json={"columns": ["asset__1", "asset__2"]},
    ).json()
    # "Yes" says nothing about which option this is, so that bar stays
    # numbered; the one that names its option is drawn under that name.
    assert set(counts(result)) == {"Option 1", "Solar panel"}


def test_the_picker_is_told_what_each_option_will_be_called(client, auth_headers, multi):
    """So the person ticking eight boxes out of nineteen can see which is which."""
    groups = client.get(
        f"{BASE}/{multi}/multiselect-groups", headers=auth_headers
    ).json()
    water = next(group for group in groups if group["stem"] == "water")
    assert [option["column"] for option in water["options"]] == water["columns"]
    # This CSV carries no labels at all, which the page is told so it can say
    # so and offer to fix it.
    assert water["unnamed"] is True
    assert water["options"][0]["label"] == "Option 1"


def test_options_labelled_only_with_the_question_are_not_all_drawn_alike(
    client, auth_headers, tmp_path
):
    """Some exports put the question on every option column and nothing else.

    Trimming the question off then leaves nothing, and printing the label as it
    stands draws every bar under the same words - a chart that says the same
    thing four times. The option's own codes are asked instead.
    """
    import pandas as pd

    frame = pd.DataFrame(
        {"fuel__1": [1, 0], "fuel__2": [0, 1], "fuel__3": [1, 1], "fuel": [1, 2]}
    )
    path = tmp_path / "fuel.dta"
    question = "What does the household cook with"
    content = _dta(
        frame,
        path,
        column_labels={
            "fuel__1": question,
            "fuel__2": question,
            "fuel__3": question,
            "fuel": "",
        },
        variable_value_labels={"fuel": {1: "Wood", 2: "Gas", 3: "Electricity"}},
    )
    dataset_id = _upload(client, auth_headers, "fuel.dta", content)
    result = client.post(
        f"{BASE}/{dataset_id}/multiselect",
        headers=auth_headers,
        json={"columns": ["fuel__1", "fuel__2", "fuel__3"]},
    ).json()
    assert set(counts(result)) == {"Wood", "Gas", "Electricity"}


# --- clicking a bar --------------------------------------------------------
#
# A bar on one of these charts used to do nothing. Every other chart on a
# dashboard filters the page when a mark is clicked; this one was left out
# because its categories are columns rather than values of a variable, and
# there was no obvious filter a click could stand for. There is one: the
# households that ticked this box. What it may not be is a plain equality.


@pytest.fixture
def mixed(client, auth_headers) -> str:
    """The same question written the three ways an export can write it.

    A real file is not tidy: Survey Solutions writes 1 and 0, a CSV round trip
    can turn those into "1" and "0", and some tools write Yes and No. The
    tabulation counts all three, so a filter made by clicking its bar has to
    count all three as well.
    """
    body = (
        "interview__key,pick__1,pick__2,province\n"
        "h1,1,1,North\n"       # number
        'h2,"1","1",North\n'   # text
        "h3,Yes,Yes,South\n"   # word
        "h4,0,No,South\n"      # not chosen, two ways
        "h5,,,South\n"         # never asked
    )
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("mixed.csv", body.encode(), "text/csv")},
    )
    assert response.status_code in (200, 201), response.text
    payload = response.json()
    return (payload["datasets"][0] if "datasets" in payload else payload)["id"]


def _rows(client, headers, dataset_id, conditions):
    """How many rows survive a filter, counted the way a widget would."""
    response = client.post(
        "/api/v1/analytics/query",
        headers=headers,
        json={
            "dataset_id": dataset_id,
            "spec": {
                "dimensions": [],
                "measures": [{"agg": "count"}],
                "filters": {"op": "and", "conditions": conditions, "groups": []},
            },
        },
    )
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    return int(rows[0][0]) if rows else 0


def test_filtering_by_an_option_keeps_exactly_what_its_bar_counted(
    client, auth_headers, mixed
):
    """The fault this exists for, and why equality could not do it.

    `= 1` against a column DuckDB read as text matches nothing at all, and
    `= '1'` matches only the rows that happen to be written that way - so a
    page filtered by clicking a bar would have disagreed with the bar, and
    said nothing about it.
    """
    bar = {
        row[0]: row[1]
        for row in client.post(
            f"{BASE}/{mixed}/multiselect",
            headers=auth_headers,
            json={"columns": ["pick__1", "pick__2"]},
        ).json()["rows"]
    }
    assert bar["Option 1"] == 3

    ticked = _rows(
        client, auth_headers, mixed, [{"variable": "pick__1", "operator": "selected"}]
    )
    assert ticked == bar["Option 1"]

    # What it replaces, kept here so the reason stays visible. Against a column
    # holding a mixture, equality either refuses the comparison outright or
    # counts only the rows written one particular way. Neither is the bar.
    assert _failed(
        client, auth_headers, mixed,
        [{"variable": "pick__1", "operator": "eq", "value": 1}],
    )
    assert _rows(
        client, auth_headers, mixed,
        [{"variable": "pick__1", "operator": "eq", "value": "1"}],
    ) == 2


def _failed(client, headers, dataset_id, conditions) -> bool:
    """Whether the engine refused the comparison rather than answering it."""
    response = client.post(
        "/api/v1/analytics/query",
        headers=headers,
        json={
            "dataset_id": dataset_id,
            "spec": {
                "dimensions": [],
                "measures": [{"agg": "count"}],
                "filters": {"op": "and", "conditions": conditions, "groups": []},
            },
        },
    )
    return response.status_code == 400


def test_not_ticked_is_the_rest_of_the_rows(client, auth_headers, mixed):
    """Including the household that was never asked.

    A checkbox has a definite answer for somebody who was not asked: they did
    not tick it. Leaving that row out of both halves would lose it from a
    pair of filters that ought to cover the file.
    """
    chose = _rows(
        client, auth_headers, mixed, [{"variable": "pick__2", "operator": "selected"}]
    )
    did_not = _rows(
        client, auth_headers, mixed,
        [{"variable": "pick__2", "operator": "not_selected"}],
    )
    assert chose == 3
    assert chose + did_not == 5


def test_two_options_with_the_same_words_are_told_apart(client, auth_headers):
    """A click carries the label, so two bars may not share one.

    Two "Other" boxes in one question is ordinary, and it takes a third option
    to reach: with only the two, the words they share become the question's own
    name and both fall back to being numbered, which is distinct already.
    Three, and "Water: " is the shared part, leaving two bars reading "Other".

    Left that way, the map from a clicked bar back to its column would hold one
    of them and quietly filter by the other box.
    """
    body = (
        "interview__key,water__1,water__2,water__3\n"
        "h1,1,0,0\n"
        "h2,0,1,1\n"
    )
    dataset = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("same.csv", body.encode(), "text/csv")},
    ).json()
    dataset_id = (dataset["datasets"][0] if "datasets" in dataset else dataset)["id"]
    for column, label in (
        ("water__1", "Water: Piped"),
        ("water__2", "Water: Other"),
        ("water__3", "Water: Other"),
    ):
        patched = client.patch(
            f"/api/v1/datasets/{dataset_id}/variables/{column}",
            headers=auth_headers,
            json={"label": label},
        )
        assert patched.status_code == 200, patched.text
    result = client.post(
        f"{BASE}/{dataset_id}/multiselect",
        headers=auth_headers,
        json={"columns": ["water__1", "water__2", "water__3"]},
    )
    assert result.status_code == 200, result.text
    labels = [row[0] for row in result.json()["rows"]]
    assert "Piped" in labels, labels
    others = [label for label in labels if label.startswith("Other")]
    assert len(others) == 2 and len(set(others)) == 2, labels
