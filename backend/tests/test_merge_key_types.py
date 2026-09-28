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
