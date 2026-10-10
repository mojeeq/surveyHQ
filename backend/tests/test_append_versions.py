"""Several questionnaire versions appended into one dataset.

A survey revised in the middle of fieldwork exports one archive per version.
They are uploaded together and appended into one dataset per member file, and
two things have to hold for the result to mean anything.

Every value must still be under the variable it was collected in. A round that
adds a question, drops one, writes its columns in a different order or exports
the same question as text still appends on the variable's NAME; lining up on
position instead puts one variable's values in another variable's column, and
nothing afterwards says so - the numbers simply look wrong.

And every code in the data must still carry its meaning. The labels used to be
taken from the round that arrived first and left at that, so an answer option
added later had no label at all: a chart drew "Rented" and "Mortgage or loan"
beside a bare 6, which reads as data from another variable rather than as a
labelling gap.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from app.services.ingest import (
    merge_value_labels,
    retyped_warnings,
    unlabelled_code_warnings,
)

TENURE = {
    1: "Owned outright",
    2: "Mortgage or loan",
    3: "Rented",
    4: "Occupied without payment of rent",
    5: "Provided free with job",
}
# The revision: one more way to answer the same question.
REVISED = {**TENURE, 6: "Other tenure"}
PROVINCE = {1: "Shefa", 2: "Sanma", 3: "Malampa"}


def _archive(frame: pd.DataFrame, value_labels: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        member = io.BytesIO()
        frame.to_stata(member, write_index=False, version=118, value_labels=value_labels)
        bundle.writestr("VN_LFS.dta", member.getvalue())
    return buffer.getvalue()


def _keys(tag: str, rows: int) -> list[str]:
    return [f"{tag}-{index:03d}" for index in range(rows)]


def rounds() -> dict[str, tuple[pd.DataFrame, dict]]:
    """Five versions, each differing from the first the way a real one does."""
    return {
        "v1": (
            pd.DataFrame(
                {
                    "interview__key": _keys("v1", 6),
                    "tenure": [1, 2, 3, 1, 2, 5],
                    "hh_size": [4.0, 2.0, 7.0, 1.0, 3.0, 5.0],
                    "province": [1, 1, 2, 3, 2, 1],
                }
            ),
            {"tenure": TENURE, "province": PROVINCE},
        ),
        # The same questions, written out in a different order.
        "v2": (
            pd.DataFrame(
                {
                    "province": [2, 3],
                    "hh_size": [6.0, 8.0],
                    "interview__key": _keys("v2", 2),
                    "tenure": [4, 3],
                }
            ),
            {"tenure": TENURE, "province": PROVINCE},
        ),
        # A question added mid-fieldwork, and a new answer option on an old one.
        "v3": (
            pd.DataFrame(
                {
                    "interview__key": _keys("v3", 3),
                    "tenure": [6, 1, 3],
                    "hh_size": [2.0, 9.0, 4.0],
                    "province": [1, 2, 3],
                    "water_source": [1, 2, 1],
                }
            ),
            {"tenure": REVISED, "province": PROVINCE},
        ),
        # A question dropped.
        "v4": (
            pd.DataFrame(
                {
                    "interview__key": _keys("v4", 2),
                    "tenure": [2, 5],
                    "hh_size": [3.0, 3.0],
                    "water_source": [2, 2],
                }
            ),
            {"tenure": REVISED},
        ),
        # The same question exported as text, and another question added.
        "v5": (
            pd.DataFrame(
                {
                    "interview__key": _keys("v5", 3),
                    "tenure": [1, 6, 4],
                    "hh_size": ["5", "2", "11"],
                    "province": [3, 3, 1],
                    "water_source": [1, 1, 2],
                    "internet_use": [1, 0, 1],
                }
            ),
            {"tenure": REVISED, "province": PROVINCE},
        ),
    }


@pytest.fixture
def project(client, auth_headers) -> str:
    made = client.post("/api/v1/projects", headers=auth_headers, json={"name": "Versions"})
    project_id = made.json()["id"]
    yield project_id
    client.delete(
        f"/api/v1/projects/{project_id}", headers=auth_headers, params={"contents": "delete"}
    )


@pytest.fixture
def imported(client, auth_headers, project):
    """All five versions uploaded in one go, as the import screen sends them."""
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            ("file", (f"{tag}.zip", _archive(frame, labels), "application/zip"))
            for tag, (frame, labels) in rounds().items()
        ],
        data={
            "project_id": project,
            "labels": '["1", "2", "3", "4", "5"]',
            "version_column": "version",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    dataset_id = next(d["id"] for d in body["datasets"] if d["name"] == "VN_LFS")
    preview = client.get(
        f"/api/v1/datasets/{dataset_id}/preview",
        headers=auth_headers,
        params={"limit": 1000},
    ).json()
    stored = pd.DataFrame(preview["rows"], columns=preview["columns"])
    return dataset_id, stored, body


def test_every_value_is_still_under_its_own_variable(imported):
    """Cell by cell against the files, which is the only way to be sure."""
    _, stored, _ = imported
    assert len(stored) == 16
    by_key = stored.set_index("interview__key")
    for tag, (frame, _labels) in rounds().items():
        for _, row in frame.iterrows():
            key = row["interview__key"]
            assert key in by_key.index, f"{key} from {tag} did not arrive"
            for column, value in row.items():
                if column == "interview__key":
                    continue
                got = by_key.loc[key, column]
                assert float(got) == float(value), (
                    f"{tag} {key}: {column} is {got!r}, the file says {value!r}"
                )


def test_a_version_is_recorded_on_every_row(imported):
    _, stored, _ = imported
    by_key = stored.set_index("interview__key")
    assert by_key.loc["v1-000", "version"] == "1"
    assert by_key.loc["v5-002", "version"] == "5"


def test_a_question_a_round_did_not_ask_is_blank_for_its_rows(imported):
    """Kept in the dataset, blank where it was not asked - not dropped."""
    _, stored, _ = imported
    by_key = stored.set_index("interview__key")
    # water_source arrived with v3; the rounds before it never asked.
    assert pd.isna(by_key.loc["v1-000", "water_source"])
    assert pd.isna(by_key.loc["v2-001", "water_source"])
    assert by_key.loc["v3-000", "water_source"] == 1
    # province was dropped in v4 and came back in v5.
    assert pd.isna(by_key.loc["v4-000", "province"])
    assert by_key.loc["v5-000", "province"] == 3
    # internet_use exists only in the last round.
    assert pd.isna(by_key.loc["v1-000", "internet_use"])
    assert by_key.loc["v5-001", "internet_use"] == 0


def test_an_answer_option_added_later_is_labelled(client, auth_headers, imported):
    """The fault behind "a chart with labels and bare numbers on one axis"."""
    dataset_id, stored, _ = imported
    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    labels = {v["name"]: v["value_labels"] or {} for v in detail["variables"]}
    used = sorted({int(value) for value in stored["tenure"].dropna()})
    unlabelled = [code for code in used if str(code) not in labels["tenure"]]
    assert not unlabelled, f"codes in the data with no label: {unlabelled}"
    # The round that arrived first still decides what a code it knew means.
    assert labels["tenure"]["3"] == "Rented"
    assert labels["tenure"]["6"] == "Other tenure"


def test_the_chart_draws_every_tenure_as_a_label(client, auth_headers, imported):
    """End to end: what the axis of the chart in the bug report reads."""
    dataset_id, _, _ = imported
    answer = client.post(
        "/api/v1/analytics/query",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "spec": {
                "dimensions": [{"variable": "tenure"}],
                "measures": [{"agg": "count", "alias": "n"}],
            },
        },
    )
    assert answer.status_code == 200, answer.text
    axis = [row[0] for row in answer.json()["rows"]]
    assert all(not str(value).isdigit() for value in axis), axis
    assert "Other tenure" in axis


# --- the two decisions, on their own ----------------------------------------


def test_merging_keeps_the_established_meaning_and_adds_the_new_code():
    merged = merge_value_labels(
        {"tenure": {"1": "Owned", "2": "Rented"}},
        {"tenure": {"1": "Owned outright", "6": "Other tenure"}},
    )
    # 1 was already understood; the dataset has been analysed under it.
    assert merged["tenure"]["1"] == "Owned"
    assert merged["tenure"]["6"] == "Other tenure"
    assert merged["tenure"]["2"] == "Rented"


def test_merging_takes_a_variable_the_dataset_had_no_labels_for():
    merged = merge_value_labels({}, {"province": {"1": "Shefa"}})
    assert merged == {"province": {"1": "Shefa"}}


def test_merging_does_not_write_through_to_what_it_was_given():
    kept = {"tenure": {"1": "Owned"}}
    merge_value_labels(kept, {"tenure": {"2": "Rented"}})
    assert kept == {"tenure": {"1": "Owned"}}


def test_a_code_that_changed_meaning_is_still_reported(client, auth_headers, project):
    """Merging must not quietly swallow a questionnaire that recoded an answer."""
    first = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            (
                "file",
                (
                    "a.zip",
                    _archive(
                        pd.DataFrame({"interview__key": ["a"], "status": [1]}),
                        {"status": {1: "Employed", 2: "Unemployed"}},
                    ),
                    "application/zip",
                ),
            )
        ],
        data={"project_id": project},
    )
    assert first.status_code == 201, first.text
    second = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            (
                "file",
                (
                    "b.zip",
                    _archive(
                        pd.DataFrame({"interview__key": ["b"], "status": [2]}),
                        {"status": {1: "Unemployed", 2: "Employed"}},
                    ),
                    "application/zip",
                ),
            )
        ],
        data={"project_id": project, "mode": "append"},
    )
    assert second.status_code == 201, second.text
    assert "labels the same codes differently" in " ".join(second.json()["warnings"])


def test_unlabelled_codes_in_a_coded_question_are_reported():
    frame = pd.DataFrame({"tenure": [1.0, 2.0, 1.0, 97685376234384.0, 449.0]})
    [message] = unlabelled_code_warnings(frame, {"tenure": {"1": "Owned", "2": "Rented"}})
    assert "'tenure' holds 2 value(s) no file labels" in message
    # As a label key is written: a whole number has no decimal point on it.
    assert "449" in message and "97685376234384" in message


def test_a_measurement_with_one_tagged_code_is_not_reported():
    """Age with 999 for "refused" is not a coded question with a labelling gap."""
    frame = pd.DataFrame({"age": [*range(1, 60), 999.0]})
    assert unlabelled_code_warnings(frame, {"age": {"999": "Refused"}}) == []


def test_a_fully_labelled_question_says_nothing():
    frame = pd.DataFrame({"tenure": [1.0, 2.0, 2.0]})
    assert unlabelled_code_warnings(frame, {"tenure": {"1": "Owned", "2": "Rented"}}) == []


def test_a_variable_the_file_does_not_have_says_nothing():
    frame = pd.DataFrame({"tenure": [1.0]})
    assert unlabelled_code_warnings(frame, {"water": {"1": "Piped"}}) == []


def test_the_import_report_names_the_round_whose_codes_have_no_label(
    client, auth_headers, project
):
    """The chart in the bug report, caught at import instead of in a meeting."""
    client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            (
                "file",
                (
                    "round-1.zip",
                    _archive(
                        pd.DataFrame(
                            {"interview__key": _keys("a", 3), "tenure": [1, 2, 3]}
                        ),
                        {"tenure": TENURE},
                    ),
                    "application/zip",
                ),
            )
        ],
        data={"project_id": project},
    )
    # A round holding something that is not a tenure code at all.
    later = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            (
                "file",
                (
                    "round-2.zip",
                    _archive(
                        pd.DataFrame(
                            {
                                "interview__key": _keys("b", 3),
                                "tenure": [1, 2, 97685376234384],
                            }
                        ),
                        {"tenure": TENURE},
                    ),
                    "application/zip",
                ),
            )
        ],
        data={"project_id": project, "mode": "append"},
    )
    assert later.status_code == 201, later.text
    said = later.json()["warnings"]
    assert any(
        "round-2.zip" in text and "97685376234384" in text and "no file labels" in text
        for text in said
    ), said


# --- a round that exports a number as text ----------------------------------


def test_a_numeric_variable_arriving_as_text_is_reported():
    before = {"hh_size", "tenure"}
    frame = pd.DataFrame({"hh_size": ["5", "2"], "tenure": [1, 2]})
    [message] = retyped_warnings(before, frame)
    assert "'hh_size'" in message
    assert "totals, averages and ranges on it stop working" in message


def test_a_variable_arriving_as_numbers_says_nothing():
    frame = pd.DataFrame({"hh_size": [5.0, 2.0]})
    assert retyped_warnings({"hh_size"}, frame) == []


def test_an_empty_column_says_nothing():
    """A round that did not ask the question is not a round that retyped it."""
    frame = pd.DataFrame({"hh_size": [None, None]})
    assert retyped_warnings({"hh_size"}, frame) == []


def test_the_import_report_says_a_question_arrived_as_text(
    client, auth_headers, project
):
    client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            (
                "file",
                (
                    "numbers.zip",
                    _archive(
                        pd.DataFrame(
                            {"interview__key": _keys("a", 2), "hh_size": [4.0, 2.0]}
                        ),
                        {},
                    ),
                    "application/zip",
                ),
            )
        ],
        data={"project_id": project},
    )
    later = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[
            (
                "file",
                (
                    "text.zip",
                    _archive(
                        pd.DataFrame(
                            {"interview__key": _keys("b", 2), "hh_size": ["5", "3"]}
                        ),
                        {},
                    ),
                    "application/zip",
                ),
            )
        ],
        data={"project_id": project, "mode": "append"},
    )
    assert later.status_code == 201, later.text
    said = later.json()["warnings"]
    assert any("'hh_size'" in text and "text.zip" in text for text in said), said
    # And nothing was dropped to say it.
    dataset_id = later.json()["datasets"][0]["id"]
    preview = client.get(
        f"/api/v1/datasets/{dataset_id}/preview", headers=auth_headers
    ).json()
    assert sorted(str(row[1]) for row in preview["rows"]) == ["2", "3", "4", "5"]


def test_a_coded_question_exported_as_text_keeps_its_labels(
    client, auth_headers, project
):
    """One answer must not end up with two spellings on one axis.

    The stored codes are numbers and the arriving ones are text, so the stack
    is text. Unless the numbers are written out the way a code is written,
    half the interviews land under "Rented" and half under a bare "3.0".
    """
    numbers = pd.DataFrame(
        # Floats, which is what a Stata export of a coded question with any
        # missing answer in it comes back as.
        {"interview__key": _keys("a", 3), "tenure": [1.0, 2.0, 2.0]}
    )
    client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[("file", ("coded.zip", _archive(numbers, {"tenure": TENURE}), "application/zip"))],
        data={"project_id": project},
    )
    text = pd.DataFrame({"interview__key": _keys("b", 2), "tenure": ["3", "1"]})
    later = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files=[("file", ("as-text.zip", _archive(text, {}), "application/zip"))],
        data={"project_id": project, "mode": "append"},
    )
    assert later.status_code == 201, later.text
    dataset_id = later.json()["datasets"][0]["id"]
    answer = client.post(
        "/api/v1/analytics/query",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "spec": {
                "dimensions": [{"variable": "tenure"}],
                "measures": [{"agg": "count", "alias": "n"}],
            },
        },
    )
    counted = {row[0]: row[1] for row in answer.json()["rows"]}
    assert counted == {"Owned outright": 2, "Mortgage or loan": 2, "Rented": 1}, counted


def test_the_codes_in_a_warning_read_in_number_order():
    # Mostly answers the file labels, which is what marks it a coded question
    # rather than a measurement with a tagged code or two.
    frame = pd.DataFrame({"tenure": [1.0] * 10 + [64.0, 449.0, 7.0, 65.0, 0.0, 12.0]})
    [message] = unlabelled_code_warnings(frame, {"tenure": {"1": "Owned"}})
    # Sorted as text, 449 would come before 64, which reads as a typo.
    assert "0, 7, 12, 64, 65 and 1 more" in message
