"""The Stata command line over a dataset.

The idioms are the ones anybody who has prepared survey data types without
thinking - gen, replace, egen, label, drop if - and the point here is that they
mean on this platform what they mean in Stata, and that what they create
survives the next export replacing the file underneath.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.test_api_analytics import _stata_bytes, _zip_bytes


@pytest.fixture
def workbench(client, auth_headers, request) -> str:
    """A dataset of this test's own, since these commands change the data.

    Named after the test, so one test's drop is not the next one's surprise.
    """
    name = request.node.name[:40]
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(6)],
            "age": [17.0, 25.0, 40.0, 63.0, 12.0, None],
            "sex": [1.0, 2.0, 1.0, 2.0, 1.0, 2.0],
            "region": ["North", "North", "South", "South", "South", "North"],
            "income": [100.0, 200.0, 300.0, None, 500.0, 600.0],
        }
    )
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                f"{name}.zip",
                _zip_bytes({f"{name}.dta": _stata_bytes(frame)}),
                "application/zip",
            )
        },
    ).json()
    return uploaded["datasets"][0]["id"]


def command(client, auth_headers, dataset_id: str, text: str):
    return client.post(
        f"/api/v1/datasets/{dataset_id}/command", headers=auth_headers, json={"command": text}
    )


def values(client, auth_headers, dataset_id: str, variable: str) -> list:
    preview = client.get(
        f"/api/v1/datasets/{dataset_id}/preview?limit=50", headers=auth_headers
    ).json()
    index = preview["columns"].index(variable)
    return [row[index] for row in preview["rows"]]


def test_gen_creates_a_variable_from_an_expression(client, auth_headers, workbench):
    response = command(client, auth_headers, workbench, "gen adult = age >= 18")
    assert response.status_code == 200, response.text
    assert response.json()["variables_added"] == ["adult"]

    # The missing age stays missing rather than becoming false
    assert values(client, auth_headers, workbench, "adult") == [
        False, True, True, True, False, None
    ]


def test_gen_with_an_if_leaves_the_other_rows_missing(client, auth_headers, workbench):
    """Which is what Stata does, and not what a spreadsheet formula does."""
    assert command(client, auth_headers, workbench, "gen band = 1 if age < 18").status_code == 200
    assert values(client, auth_headers, workbench, "band") == [1, None, None, None, 1, None]


def test_replace_changes_only_the_rows_the_if_names(client, auth_headers, workbench):
    command(client, auth_headers, workbench, "gen band = 0")
    response = command(client, auth_headers, workbench, "replace band = 1 if region == \"North\"")
    assert response.status_code == 200, response.text
    assert "3 row(s)" in response.json()["message"]
    assert values(client, auth_headers, workbench, "band") == [1, 1, 0, 0, 0, 1]


def test_egen_aggregates_within_a_group(client, auth_headers, workbench):
    response = command(
        client, auth_headers, workbench, "egen n = count(age), by(region)"
    )
    assert response.status_code == 200, response.text
    # North has three rows but one missing age; count() counts the non-missing
    assert values(client, auth_headers, workbench, "n") == [2, 2, 3, 3, 3, 2]


def test_egen_works_across_a_row_too(client, auth_headers, workbench):
    assert command(
        client, auth_headers, workbench, "egen both = rowtotal(age income)"
    ).status_code == 200
    assert values(client, auth_headers, workbench, "both") == [117, 225, 340, 63, 512, 600]


def test_label_names_a_variable_and_its_codes(client, auth_headers, workbench):
    assert command(
        client, auth_headers, workbench, 'label variable sex "Sex of respondent"'
    ).status_code == 200
    assert command(
        client, auth_headers, workbench, 'label define sexlbl 1 "Male" 2 "Female"'
    ).status_code == 200
    assert command(client, auth_headers, workbench, "label values sex sexlbl").status_code == 200

    dataset = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    variable = next(v for v in dataset["variables"] if v["name"] == "sex")
    assert variable["label"] == "Sex of respondent"
    assert variable["value_labels"] == {"1": "Male", "2": "Female"}

    # And the names reach the numbers
    frequency = client.get(
        f"/api/v1/analytics/datasets/{workbench}/frequency/sex", headers=auth_headers
    ).json()
    assert {row["label"] for row in frequency["rows"]} == {"Male", "Female"}


def test_drop_and_keep(client, auth_headers, workbench):
    assert command(client, auth_headers, workbench, "drop if age < 18").status_code == 200
    after = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    assert after["row_count"] == 4  # two under-18s go; the missing age stays

    assert command(client, auth_headers, workbench, "drop income").status_code == 200
    after = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    assert "income" not in {v["name"] for v in after["variables"]}


def test_rename_carries_the_label_with_it(client, auth_headers, workbench):
    command(client, auth_headers, workbench, 'label variable age "Age in years"')
    assert command(client, auth_headers, workbench, "rename age years").status_code == 200
    dataset = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    variable = next(v for v in dataset["variables"] if v["name"] == "years")
    assert variable["label"] == "Age in years"


def test_a_generated_variable_survives_the_next_export(client, auth_headers):
    """The reason the commands are recorded at all.

    A variable somebody generated is not in the export file, so a replacement
    would drop it - and every chart standing on it - on exactly the upload this
    platform is built around.
    """
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Replayed commands"}
    ).json()

    def archive(rows: int):
        return _zip_bytes(
            {
                "replayed.dta": _stata_bytes(
                    pd.DataFrame(
                        {
                            "interview__key": [f"k{i}" for i in range(rows)],
                            "age": [20.0 + i for i in range(rows)],
                        }
                    )
                )
            }
        )

    first = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("first.zip", archive(3), "application/zip")},
        data={"project_id": project["id"]},
    ).json()
    dataset_id = first["datasets"][0]["id"]

    command(client, auth_headers, dataset_id, "gen decade = int(age / 10)")
    command(client, auth_headers, dataset_id, 'label variable decade "Decade of life"')
    assert client.get(
        f"/api/v1/datasets/{dataset_id}/commands", headers=auth_headers
    ).json() == ["gen decade = int(age / 10)", 'label variable decade "Decade of life"']

    later = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("later.zip", archive(5), "application/zip")},
        data={"project_id": project["id"]},
    )
    assert later.status_code == 201, later.text

    after = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    assert after["row_count"] == 5
    decade = next((v for v in after["variables"] if v["name"] == "decade"), None)
    assert decade is not None, "the generated variable did not survive the replacement"
    assert decade["label"] == "Decade of life"
    # And it is not reported lost on the way: the replay puts it back before
    # the import checks what the new file no longer has.
    assert not any("decade" in w for w in later.json()["warnings"]), later.json()["warnings"]


def test_a_command_that_no_longer_applies_is_reported_not_fatal(client, auth_headers):
    """A later export without the variable must not fail the import itself."""
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Dropped underneath"}
    ).json()

    def archive(with_income: bool):
        columns = {"interview__key": ["k1", "k2"], "age": [20.0, 30.0]}
        if with_income:
            columns["income"] = [100.0, 200.0]
        return _zip_bytes({"shrinking.dta": _stata_bytes(pd.DataFrame(columns))})

    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("full.zip", archive(True), "application/zip")},
        data={"project_id": project["id"]},
    ).json()
    dataset_id = uploaded["datasets"][0]["id"]
    command(client, auth_headers, dataset_id, "gen per_year = income * 12")

    later = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("thin.zip", archive(False), "application/zip")},
        data={"project_id": project["id"]},
    )
    assert later.status_code == 201, later.text
    assert any("could not be re-applied" in w for w in later.json()["warnings"]), later.json()


def test_a_command_that_is_not_understood_says_which_part(client, auth_headers, workbench):
    response = command(client, auth_headers, workbench, "gen x = height + 1")
    assert response.status_code == 422
    assert "'height' is not a variable" in response.json()["detail"]

    response = command(client, auth_headers, workbench, "summarize age")
    assert response.status_code == 422
    assert "not a command" in response.json()["detail"]


def test_a_name_already_in_use_is_refused(client, auth_headers, workbench):
    response = command(client, auth_headers, workbench, "gen age = 1")
    assert response.status_code == 422
    assert "already exists" in response.json()["detail"]


def test_the_history_can_be_cleared_without_undoing_the_work(client, auth_headers, workbench):
    command(client, auth_headers, workbench, "gen adult = age >= 18")
    cleared = client.delete(f"/api/v1/datasets/{workbench}/commands", headers=auth_headers)
    assert cleared.status_code == 200
    assert client.get(
        f"/api/v1/datasets/{workbench}/commands", headers=auth_headers
    ).json() == []

    dataset = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    assert "adult" in {v["name"] for v in dataset["variables"]}


def test_a_script_runs_its_lines_in_order(client, auth_headers, workbench):
    """A do-file, not a prompt: several commands, top to bottom."""
    script = """
* Age bands, as anybody would write them
gen band = 1 if age < 18
replace band = 2 if age >= 18 & age < 60
replace band = 3 if age >= 60
label define bandlbl 1 "Child" 2 "Adult" 3 "Older"  // three of them
label values band bandlbl
"""
    response = command(client, auth_headers, workbench, script)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["error"] is None
    assert [step["command"] for step in body["results"]] == [
        "gen band = 1 if age < 18",
        "replace band = 2 if age >= 18 & age < 60",
        "replace band = 3 if age >= 60",
        'label define bandlbl 1 "Child" 2 "Adult" 3 "Older"',
        "label values band bandlbl",
    ]
    assert values(client, auth_headers, workbench, "band") == [1, 2, 2, 3, 1, None]

    dataset = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    variable = next(v for v in dataset["variables"] if v["name"] == "band")
    assert variable["value_labels"] == {"1": "Child", "2": "Adult", "3": "Older"}


def test_a_line_that_fails_stops_the_script_and_says_which(client, auth_headers, workbench):
    """What ran above it has already changed the data, as in a do-file."""
    script = "gen ok = 1\ngen bad = height + 1\ngen never = 2"
    response = command(client, auth_headers, workbench, script)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "Line 2" in body["error"]
    assert "'height' is not a variable" in body["error"]
    assert [step["command"] for step in body["results"]] == ["gen ok = 1"]

    names = {
        v["name"]
        for v in client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()[
            "variables"
        ]
    }
    assert "ok" in names and "never" not in names


def test_a_script_whose_first_line_fails_changes_nothing(client, auth_headers, workbench):
    before = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    response = command(client, auth_headers, workbench, "gen bad = height + 1\ngen ok = 1")
    assert response.status_code == 422
    after = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    assert after["column_count"] == before["column_count"]


def test_a_long_line_can_be_continued(client, auth_headers, workbench):
    """/// joins a line to the next, so a long generate needs no scrollbar."""
    script = "gen wealthy = 1 if income > 250 ///\n    & age > 18"
    assert command(client, auth_headers, workbench, script).status_code == 200
    # Only the row with both: income 500 belongs to a 12-year-old, and the
    # 600 to a row with no age at all.
    assert values(client, auth_headers, workbench, "wealthy") == [
        None, None, 1, None, None, None
    ]


def test_only_the_lines_that_ran_are_kept_for_replay(client, auth_headers, workbench):
    command(client, auth_headers, workbench, "gen a = 1\ngen b = nope\ngen c = 3")
    kept = client.get(f"/api/v1/datasets/{workbench}/commands", headers=auth_headers).json()
    assert kept == ["gen a = 1"]
