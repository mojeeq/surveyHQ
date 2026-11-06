"""Records alike enough to be one person entered twice.

The exact duplicate check finds a key that repeats. A person listed twice
rarely repeats anything exactly: "Mary Smith, 34" in one household and "Marie
Smith, 35" in another share no value at all. This check scores pairs field by
field and flags the ones alike enough to be the same person.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services import likely_duplicates
from app.services.query_engine import DatasetContext, QueryError, VariableInfo

PEOPLE = [
    # id, first, last, age, dob, sex, ea
    ("p1", "Mary", "Smith", 34, "1990-03-05", "F", "01"),
    # Mary again: a letter changed, a year older on the form.
    ("p2", "Marie", "Smith", 35, "1990-03-05", "F", "01"),
    # A different woman in the same family: same surname and sex, not her.
    ("p3", "Teresa", "Smith", 61, "1963-11-20", "F", "01"),
    # John, and John with his names the other way round and the day and month
    # of his birth swapped.
    ("p4", "John", "Baker", 40, "1984-07-02", "M", "02"),
    ("p5", "Baker John", "", 40, "1984-02-07", "M", "02"),
    # Peter, entered twice - once in each of two areas.
    ("p6", "Peter", "Brown", 22, "2002-01-15", "M", "01"),
    ("p7", "Petr", "Brown", 22, "2002-01-15", "M", "03"),
    # Grace with no age recorded: compared on what she has.
    ("p8", "Grace", "Lee", None, "1995-09-09", "F", "03"),
    ("p9", "Grace", "Lee", 29, "1995-09-09", "F", "03"),
    # Alone.
    ("p10", "Paul", "Taylor", 50, "1974-04-04", "M", "02"),
]

COLUMNS = ["pid", "first", "last", "age", "dob", "sex", "ea"]


@pytest.fixture
def ctx(tmp_path) -> DatasetContext:
    frame = pd.DataFrame(PEOPLE, columns=COLUMNS)
    # p5 holds both names in one field, as a form with one name box does.
    frame["name"] = (frame["first"] + " " + frame["last"]).str.strip()
    path = tmp_path / "people.parquet"
    frame.to_parquet(path, index=False)
    return DatasetContext(
        "people",
        str(path),
        {name: VariableInfo(name, name, "text") for name in frame.columns},
    )


FIELDS = [
    {"variable": "name", "compare": "text", "weight": 2},
    {"variable": "age", "compare": "number", "tolerance": 1},
    {"variable": "dob", "compare": "date"},
    {"variable": "sex", "compare": "exact"},
]


def pairs(ctx, **config) -> list[tuple[str, str, float]]:
    """The flagged pairs, by person id, with their similarity in percent."""
    the_config = {"fields": FIELDS, "id_variables": ["pid"], **config}
    _, found = likely_duplicates.find(ctx, the_config, "", [])
    return [
        (*row[1].split(" ↔ "), row[0]) for row in found.examples["rows"]
    ]


def flagged(ctx, **config) -> set[frozenset[str]]:
    return {frozenset(pair[:2]) for pair in pairs(ctx, **config)}


def test_finds_a_person_entered_twice_with_a_name_spelled_differently(ctx):
    found = flagged(ctx)
    assert frozenset({"p1", "p2"}) in found
    # Her relative shares a surname and a sex, and nothing else.
    assert frozenset({"p1", "p3"}) not in found
    assert frozenset({"p10", "p4"}) not in found


def test_names_in_either_order_and_a_day_and_month_swapped(ctx):
    assert frozenset({"p4", "p5"}) in flagged(ctx)


def test_a_blank_is_left_out_rather_than_counted_against(ctx):
    found = pairs(ctx)
    grace = next(pair for pair in found if {pair[0], pair[1]} == {"p8", "p9"})
    # Alike on everything both have; the missing age is not a disagreement.
    assert grace[2] == 100.0


def test_a_name_kept_in_two_boxes_is_joined_before_it_is_compared(ctx):
    # p4 and p5 as two boxes: John / Baker, and Baker John / (blank). "Baker"
    # sorts before "John", so the first boxes don't share a start either.
    # Field by field they share nothing; joined, they are one name.
    split = [
        {"variable": "first", "compare": "text", "weight": 2},
        {"variable": "last", "compare": "text", "weight": 2},
        *FIELDS[1:],
    ]
    joined = [
        {"variable": "first", "also": ["last"], "compare": "text", "weight": 3},
        *FIELDS[1:],
    ]
    assert frozenset({"p4", "p5"}) not in flagged(ctx, fields=split)
    found = pairs(ctx, fields=joined)
    john = next(pair for pair in found if {pair[0], pair[1]} == {"p4", "p5"})
    assert john[2] == 100.0


def test_grouping_compares_only_records_that_share_something(ctx):
    # Peter's two entries are in different areas: compared freely, a pair...
    assert frozenset({"p6", "p7"}) in flagged(ctx)
    # ...and held to the same area, never compared at all.
    within = flagged(ctx, block=[{"variable": "ea"}])
    assert frozenset({"p6", "p7"}) not in within
    assert frozenset({"p1", "p2"}) in within
    # The first letter of a name is a coarser group that still finds them.
    assert frozenset({"p6", "p7"}) in flagged(ctx, block=[{"variable": "last", "how": "first_letter"}])


def test_the_threshold_decides_how_alike_is_alike(ctx):
    strict = flagged(ctx, min_similarity=0.99)
    assert frozenset({"p1", "p2"}) not in strict
    assert frozenset({"p8", "p9"}) in strict


def test_the_counts_are_of_records_and_of_pairs(ctx):
    _, found = likely_duplicates.find(ctx, {"fields": FIELDS}, "", [])
    assert found.pairs == len(flagged(ctx))
    assert found.records == len({pid for pair in flagged(ctx) for pid in pair})


def test_too_many_pairs_is_refused_with_what_to_do(ctx, monkeypatch):
    monkeypatch.setattr(likely_duplicates, "MAX_PAIRS", 20)
    with pytest.raises(QueryError, match=r"45 pairs of records.*same enumeration area"):
        likely_duplicates.find(ctx, {"fields": FIELDS}, "", [])
    # Grouped by area, the same records are 12 pairs: few enough to compare.
    likely_duplicates.find(ctx, {"fields": FIELDS, "block": [{"variable": "ea"}]}, "", [])


def test_settings_are_checked_before_anything_runs(ctx):
    with pytest.raises(QueryError, match="at least two fields"):
        likely_duplicates.find(ctx, {"fields": FIELDS[:1]}, "", [])
    with pytest.raises(QueryError, match="not a way to compare"):
        likely_duplicates.find(
            ctx, {"fields": [{"variable": "name", "compare": "sounds"}, FIELDS[1]]}, "", []
        )
    with pytest.raises(QueryError, match="weight has to be between"):
        likely_duplicates.find(
            ctx, {"fields": [{"variable": "name", "weight": 1e9}, FIELDS[1]]}, "", []
        )
    with pytest.raises(QueryError):
        likely_duplicates.find(
            ctx, {"fields": [{"variable": "name; DROP TABLE x"}, FIELDS[1]]}, "", []
        )


# --- Through the platform ---------------------------------------------------------


def _upload(client, auth_headers, frame: pd.DataFrame) -> str:
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("people.csv", frame.to_csv(index=False).encode(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return (body["datasets"][0] if "datasets" in body else body)["id"]


def test_a_rule_runs_and_lists_its_pairs(client, auth_headers):
    frame = pd.DataFrame(PEOPLE, columns=COLUMNS)
    frame["name"] = (frame["first"] + " " + frame["last"]).str.strip()
    dataset_id = _upload(client, auth_headers, frame)
    created = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "name": "People entered twice",
            "check_type": "likely_duplicates",
            "threshold": 0,
            "config": {"fields": FIELDS, "id_variables": ["pid"], "min_similarity": 0.9},
        },
    )
    assert created.status_code == 201, created.text
    rule = created.json()

    run = client.post(f"/api/v1/monitoring/quality-rules/{rule['id']}/run", headers=auth_headers)
    assert run.status_code == 200, run.text
    result = run.json()
    assert result["passed"] is False
    assert result["details"]["pairs"] >= 3
    assert "look like duplicates of another" in result["message"]

    failures = client.get(
        f"/api/v1/monitoring/quality-rules/{rule['id']}/failures", headers=auth_headers
    )
    assert failures.status_code == 200, failures.text
    body = failures.json()
    columns = body["columns"]
    # The pair, then who they are, then what they were compared on.
    assert columns[:7] == [
        "likely_duplicate_pair", "similarity_percent", "pid", "name", "age", "dob", "sex",
    ]
    assert len(columns) == len(set(columns))
    assert "file_row_number" not in columns and not any(c.startswith("__") for c in columns)
    rows = body["rows"]
    assert body["total"] == 2 * result["details"]["pairs"]
    # Each pair's two records sit together, the closest pair first.
    numbers = [row[0] for row in rows]
    assert numbers == sorted(numbers) and numbers[0] == numbers[1] == 1
    assert rows[0][1] >= rows[-1][1]


def test_a_rule_scoped_by_a_filter_compares_only_inside_it(client, auth_headers):
    frame = pd.DataFrame(PEOPLE, columns=COLUMNS)
    frame["name"] = (frame["first"] + " " + frame["last"]).str.strip()
    dataset_id = _upload(client, auth_headers, frame)
    created = client.post(
        "/api/v1/monitoring/quality-rules",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "name": "Men entered twice",
            "check_type": "likely_duplicates",
            "threshold": 0,
            "config": {"fields": FIELDS, "id_variables": ["pid"]},
            "filters": {
                "op": "and",
                "conditions": [{"variable": "sex", "operator": "eq", "value": "M"}],
                "groups": [],
            },
        },
    )
    rule = created.json()
    result = client.post(
        f"/api/v1/monitoring/quality-rules/{rule['id']}/run", headers=auth_headers
    ).json()
    # Only the men: John twice and Peter twice.
    assert result["details"]["pairs"] == 2
    assert result["total_rows"] == 5


def test_it_is_suggested_where_there_are_names_and_ages(client, auth_headers):
    frame = pd.DataFrame(PEOPLE, columns=COLUMNS).rename(
        columns={"first": "first_name", "last": "surname"}
    )
    frame["interviewer_name"] = "Agent"
    dataset_id = _upload(client, auth_headers, frame)
    suggestions = client.get(
        f"/api/v1/monitoring/datasets/{dataset_id}/quality/suggestions", headers=auth_headers
    ).json()
    likely = next(one for one in suggestions if one["check_type"] == "likely_duplicates")
    compared = {field["variable"]: field for field in likely["config"]["fields"]}
    # The person's name, its parts joined and compared by spelling; the
    # interviewer's name is not the person's.
    assert compared["first_name"]["compare"] == "text"
    assert compared["first_name"]["also"] == ["surname"]
    assert {name: field["compare"] for name, field in compared.items()} == {
        "first_name": "text",
        "age": "number",
        "dob": "date",
        "sex": "exact",
    }


def test_it_is_not_suggested_without_names(client, auth_headers):
    frame = pd.DataFrame({"age": [1, 2, 3], "sex": ["M", "F", "M"]})
    dataset_id = _upload(client, auth_headers, frame)
    suggestions = client.get(
        f"/api/v1/monitoring/datasets/{dataset_id}/quality/suggestions", headers=auth_headers
    ).json()
    assert not any(one["check_type"] == "likely_duplicates" for one in suggestions)
