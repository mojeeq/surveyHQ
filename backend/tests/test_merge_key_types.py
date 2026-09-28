"""Merging on a key that is text on one side and a number on the other.

Survey data does this constantly: one export writes the household id as
"H0041" and the next writes 41, or an id column arrives quoted from a CSV and
unquoted from a .dta. DuckDB answers the join by casting the text side to a
number and failing on the first value that is not one - and that failure is a
duckdb.ConversionException, which is not a ValueError, so it went straight past
the endpoint's 422 handler and the merge came back as a bare 500 with nothing
in it to act on.
"""

from __future__ import annotations

import pandas as pd

from tests.test_api_analytics import _stata_bytes, _zip_bytes

# The same households, identified two different ways.
HOUSEHOLDS = pd.DataFrame({"hhid": ["H1", "H2", "H3"], "province": ["Shefa", "Sanma", "Tafea"]})
PEOPLE = pd.DataFrame({"hhid": [1.0, 1.0, 2.0], "age": [40.0, 9.0, 33.0]})


def _project(client, auth_headers, name: str) -> dict:
    made = client.post("/api/v1/projects", headers=auth_headers, json={"name": name}).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "export.zip",
                _zip_bytes(
                    {
                        "mk_households.dta": _stata_bytes(HOUSEHOLDS),
                        "mk_people.dta": _stata_bytes(PEOPLE),
                    }
                ),
                "application/zip",
            )
        },
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    by_name = {row["name"]: row["id"] for row in uploaded.json()["datasets"]}
    return {"id": made["id"], **by_name}


def _matching_project(client, auth_headers, name: str) -> dict:
    """Two tables whose key is a number on both sides, so the join is sound."""
    made = client.post("/api/v1/projects", headers=auth_headers, json={"name": name}).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "sound.zip",
                _zip_bytes(
                    {
                        "sk_people.dta": _stata_bytes(PEOPLE),
                        "sk_wages.dta": _stata_bytes(
                            pd.DataFrame({"hhid": [1.0, 2.0], "wage": [10.0, 20.0]})
                        ),
                    }
                ),
                "application/zip",
            )
        },
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    by_name = {row["name"]: row["id"] for row in uploaded.json()["datasets"]}
    return {"id": made["id"], **by_name}


def _relationship(client, auth_headers, project: dict) -> str:
    made = client.post(
        "/api/v1/relationships",
        headers=auth_headers,
        json={
            "left_dataset_id": project["mk_people"],
            "right_dataset_id": project["mk_households"],
            "left_variable": "hhid",
            "right_variable": "hhid",
            "cardinality": "many_to_one",
        },
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def test_a_text_key_against_a_number_says_so_rather_than_failing(client, auth_headers):
    project = _project(client, auth_headers, "Merge key types")
    relationship = _relationship(client, auth_headers, project)

    refused = client.post(
        "/api/v1/relationships/merge",
        headers=auth_headers,
        json={"name": "People with households", "relationship_id": relationship},
    )
    assert refused.status_code == 422, refused.status_code
    detail = refused.json()["detail"]
    assert "hhid" in detail
    assert "text" in detail and "number" in detail
    assert "mk_households" in detail or "mk_people" in detail


def test_detection_passes_over_a_mismatched_key_rather_than_failing(
    client, auth_headers
):
    """Detection reads values to decide, so it meets the same cast.

    A shared column name with different types in the two files is not a
    relationship, and a list of proposals is not the place to fail: the button
    has to come back with whatever it did find.
    """
    project = _project(client, auth_headers, "Detect key types")
    detected = client.post(
        f"/api/v1/relationships/detect?project_id={project['id']}", headers=auth_headers
    )
    assert detected.status_code == 200, detected.text
    assert detected.json()["proposed"] == []


def test_anything_else_duckdb_refuses_is_a_422_and_not_a_500(
    client, auth_headers, db_session, monkeypatch
):
    """The backstop, pinned on its own.

    The check above foresees the mismatch that actually happens. Whatever it
    does not foresee has to arrive as a message and a 422 all the same, which is
    what the canonical merge has always done by running its join through
    run_sql - so the columnar one is held to the same contract.
    """
    import duckdb

    from app.services import columnar

    def refuse(**_: object) -> None:
        raise duckdb.BinderException("Binder Error: something DuckDB will not do")

    monkeypatch.setattr(columnar, "copy_join_to_parquet", refuse)

    project = _matching_project(client, auth_headers, "Merge backstop")
    # Matching types, so the check passes and the join itself is what fails.
    relationship = client.post(
        "/api/v1/relationships",
        headers=auth_headers,
        json={
            "left_dataset_id": project["sk_people"],
            "right_dataset_id": project["sk_wages"],
            "left_variable": "hhid",
            "right_variable": "hhid",
            "cardinality": "many_to_one",
        },
    )
    assert relationship.status_code == 201, relationship.text

    refused = client.post(
        "/api/v1/relationships/merge",
        headers=auth_headers,
        json={"name": "Backstop", "relationship_id": relationship.json()["id"]},
    )
    assert refused.status_code == 422, refused.status_code
    assert "something DuckDB will not do" in refused.json()["detail"]


# --- saying the two ids are the same household written two ways --------------
#
# A key column only stays text through ingest if something in it is not a
# number: a plain "1" is read as 1 and there is no mismatch left to resolve. So
# these ids are the real shape of the problem - mostly numbers, with a "not
# known" in them, which is what an enumerator writes and what keeps the whole
# column text.
MIXED = pd.DataFrame(
    {"hhid": ["1", "2", "not known"], "province": ["Shefa", "Sanma", "Tafea"]}
)


def _mixed_project(client, auth_headers, name: str) -> dict:
    made = client.post("/api/v1/projects", headers=auth_headers, json={"name": name}).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "mixed.zip",
                _zip_bytes(
                    {
                        "mx_households.dta": _stata_bytes(MIXED),
                        "mx_people.dta": _stata_bytes(PEOPLE),
                    }
                ),
                "application/zip",
            )
        },
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    by_name = {row["name"]: row["id"] for row in uploaded.json()["datasets"]}
    return {"id": made["id"], **by_name}


def _link(client, auth_headers, left_id: str, right_id: str, **extra) -> dict:
    made = client.post(
        "/api/v1/relationships",
        headers=auth_headers,
        json={
            "left_dataset_id": left_id,
            "right_dataset_id": right_id,
            "left_variable": "hhid",
            "right_variable": "hhid",
            "cardinality": "many_to_one",
            **extra,
        },
    )
    assert made.status_code == 201, made.text
    return made.json()


def test_a_relationship_defaults_to_matching_its_keys_exactly(client, auth_headers):
    """The conversion is never the default.

    Making two keys comparable can also make two different keys equal, so it
    only ever happens because somebody said to.
    """
    project = _mixed_project(client, auth_headers, "Key match default")
    link = _link(client, auth_headers, project["mx_people"], project["mx_households"])
    assert link["key_match"] == "exact"


def test_matching_as_text_joins_the_rows_the_ids_agree_on(client, auth_headers):
    project = _mixed_project(client, auth_headers, "Key match text")
    link = _link(
        client,
        auth_headers,
        project["mx_people"],
        project["mx_households"],
        key_match="text",
    )
    merged = client.post(
        "/api/v1/relationships/merge",
        headers=auth_headers,
        json={"name": "People with province", "relationship_id": link["id"], "how": "inner"},
    )
    assert merged.status_code == 201, merged.text
    body = merged.json()
    # Two people in household 1 and one in household 2, all three now carrying a
    # province. The "not known" household matches nobody, which is correct.
    assert body["row_count"] == 3
    assert "province" in {v["name"] for v in body["variables"]}


def test_matching_as_numbers_joins_them_too_and_ignores_what_is_not_one(
    client, auth_headers
):
    """The other direction, and the reason it uses TRY_CAST.

    "not known" is not a number. Converting it has to leave a blank that matches
    nothing, rather than failing the join - which is the 500 this replaced.
    """
    project = _mixed_project(client, auth_headers, "Key match number")
    link = _link(
        client,
        auth_headers,
        project["mx_people"],
        project["mx_households"],
        key_match="number",
    )
    merged = client.post(
        "/api/v1/relationships/merge",
        headers=auth_headers,
        json={"name": "People by number", "relationship_id": link["id"], "how": "inner"},
    )
    assert merged.status_code == 201, merged.text
    assert merged.json()["row_count"] == 3


def test_the_refusal_names_the_option_that_answers_it(client, auth_headers):
    project = _mixed_project(client, auth_headers, "Key match advice")
    link = _link(client, auth_headers, project["mx_people"], project["mx_households"])
    refused = client.post(
        "/api/v1/relationships/merge",
        headers=auth_headers,
        json={"name": "Refused", "relationship_id": link["id"]},
    )
    assert refused.status_code == 422, refused.text
    assert "match its keys as text" in refused.json()["detail"]


def test_the_option_can_be_set_after_the_refusal_and_the_merge_then_runs(
    client, auth_headers
):
    """The path somebody actually walks: try it, read why, say so, try again."""
    project = _mixed_project(client, auth_headers, "Key match retry")
    link = _link(client, auth_headers, project["mx_people"], project["mx_households"])
    client.post(
        "/api/v1/relationships/merge",
        headers=auth_headers,
        json={"name": "Attempt", "relationship_id": link["id"]},
    )
    changed = client.patch(
        f"/api/v1/relationships/{link['id']}",
        headers=auth_headers,
        json={"key_match": "text"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["key_match"] == "text"

    merged = client.post(
        "/api/v1/relationships/merge",
        headers=auth_headers,
        json={"name": "Attempt", "relationship_id": link["id"], "how": "inner"},
    )
    assert merged.status_code == 201, merged.text
    assert merged.json()["row_count"] == 3


def test_a_conversion_that_lines_nothing_up_says_so(client, auth_headers):
    """The bad outcome this has to avoid being silent about.

    Converting the keys makes the merge succeed whether or not it matched
    anything: a left join that matched nothing writes out the left side with a
    column of blanks beside it, and the dataset looks built. Here the ids differ
    by more than how they are written - "H1" is not 1 under any conversion - so
    the merge runs and the warning says what happened.
    """
    project = _project(client, auth_headers, "Key match nothing")
    link = _link(
        client,
        auth_headers,
        project["mk_people"],
        project["mk_households"],
        key_match="text",
    )
    merged = client.post(
        "/api/v1/relationships/merge",
        headers=auth_headers,
        json={"name": "Nothing lines up", "relationship_id": link["id"]},
    )
    assert merged.status_code == 201, merged.text
    warnings = merged.json().get("meta", {}).get("warnings", [])
    assert any("lined up no rows at all" in warning for warning in warnings), warnings
