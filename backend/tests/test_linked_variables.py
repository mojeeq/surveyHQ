"""Variables brought into a dataset from another, without making a new one.

A merge makes a new dataset, and everything already built on the old one -
charts, indicators, quality checks - stays where it was. This brings the
other dataset's variables into the existing one instead: same id, same rows
in the same order, and kept up to date whenever either side gets new data.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import select

from app.models import Dataset
from tests.test_api_analytics import _stata_bytes, _zip_bytes

HOUSEHOLDS = pd.DataFrame(
    {
        "hhid": [1.0, 2.0, 3.0],
        "province": ["Northern", "Highland", "Coastal"],
        "size": [4.0, 2.0, 5.0],
    }
)
# p4 belongs to a household the household file does not have.
PEOPLE = pd.DataFrame(
    {
        "pid": ["p1", "p2", "p3", "p4", "p5"],
        "hhid": [1.0, 1.0, 2.0, 9.0, 3.0],
        "age": [40.0, 9.0, 33.0, 21.0, 60.0],
    }
)


def upload(client, auth_headers, project_id: str, mode: str = "replace", **frames) -> dict:
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "export.zip",
                _zip_bytes({f"{name}.dta": _stata_bytes(frame) for name, frame in frames.items()}),
                "application/zip",
            )
        },
        data={"project_id": project_id, "mode": mode},
    )
    assert response.status_code == 201, response.text
    return response.json()


def named(db_session, project_id: str, name: str) -> Dataset:
    db_session.expire_all()
    return db_session.scalars(
        select(Dataset).where(Dataset.project_id == project_id, Dataset.name == name)
    ).one()


def rows(dataset: Dataset) -> pd.DataFrame:
    return pd.read_parquet(dataset.storage_path)


@pytest.fixture
def project(client, auth_headers, request) -> dict:
    made = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": f"L {request.node.name[:40]}"}
    ).json()
    upload(client, auth_headers, made["id"], people=PEOPLE, households=HOUSEHOLDS)
    return made


def link(client, auth_headers, target: Dataset, source: Dataset, variables, keys=None, **extra):
    return client.post(
        f"/api/v1/datasets/{target.id}/linked-variables",
        headers=auth_headers,
        json={
            "source_dataset_id": source.id,
            "keys": keys if keys is not None else [{"here": "hhid", "there": "hhid"}],
            "variables": variables,
            **extra,
        },
    )


def test_people_gain_household_variables_and_keep_what_is_built_on_them(
    client, auth_headers, project, db_session
):
    people = named(db_session, project["id"], "people")
    households = named(db_session, project["id"], "households")
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "People by age",
            "dataset_id": people.id,
            "chart_type": "bar",
            "spec": {"dimensions": [{"variable": "age"}], "measures": [{"agg": "count"}]},
        },
    ).json()

    # Asked with no keys, the shared id unique in the household file is offered.
    checked = client.post(
        f"/api/v1/datasets/{people.id}/linked-variables/check",
        headers=auth_headers,
        json={"source_dataset_id": households.id},
    ).json()
    assert checked["keys"] == [{"here": "hhid", "there": "hhid"}]
    assert checked["error"] is None
    assert checked["match"]["matched"] == 4 and checked["match"]["unmatched"] == 1

    response = link(client, auth_headers, people, households, ["size", "province"])
    assert response.status_code == 201, response.text
    assert "4 of the 5 rows" in response.json()["message"]

    after = named(db_session, project["id"], "people")
    assert after.id == people.id
    data = rows(after)
    # The same people in the same order, with their household's values beside them.
    assert list(data["pid"]) == ["p1", "p2", "p3", "p4", "p5"]
    assert list(data["size"].fillna(-1)) == [4.0, 4.0, 2.0, -1, 5.0]
    assert list(data["province"].fillna("")) == ["Northern", "Northern", "Highland", "", "Coastal"]
    assert "file_row_number" not in data.columns and "__row" not in data.columns

    # The chart built before still works, and the new variables can be charted.
    assert (
        client.post(
            f"/api/v1/dashboards/charts/{chart['id']}/data", headers=auth_headers, json={}
        ).status_code
        == 200
    )
    listed = client.get(f"/api/v1/datasets/{people.id}/linked-variables", headers=auth_headers)
    assert listed.json()[0]["variables"] == ["size", "province"]
    assert listed.json()[0]["source_name"] == "households"


def test_new_household_data_reaches_the_people(client, auth_headers, project, db_session):
    people = named(db_session, project["id"], "people")
    households = named(db_session, project["id"], "households")
    assert link(client, auth_headers, people, households, ["size"]).status_code == 201

    bigger = HOUSEHOLDS.assign(size=[7.0, 2.0, 5.0])
    upload(client, auth_headers, project["id"], households=bigger)

    assert list(rows(named(db_session, project["id"], "people"))["size"].fillna(-1)) == [
        7.0,
        7.0,
        2.0,
        -1,
        5.0,
    ]


def test_a_newer_export_gets_them_back_and_its_commands_can_use_them(
    client, auth_headers, project, db_session
):
    people = named(db_session, project["id"], "people")
    households = named(db_session, project["id"], "households")
    assert link(client, auth_headers, people, households, ["size"]).status_code == 201
    ran = client.post(
        f"/api/v1/datasets/{people.id}/command",
        headers=auth_headers,
        json={"command": "gen big = size >= 4"},
    )
    assert ran.status_code == 200, ran.text

    # The export has no size, as it never had: it comes back, and the command
    # recorded on the dataset is replayed with it there to use.
    newer = pd.DataFrame({"pid": ["p1", "p6"], "hhid": [1.0, 2.0], "age": [41.0, 3.0]})
    upload(client, auth_headers, project["id"], people=newer)

    after = named(db_session, project["id"], "people")
    data = rows(after)
    assert list(data["size"]) == [4.0, 2.0]
    assert list(data["big"]) == [1, 0]
    # Not reported as a variable the new export lost.
    assert not any("size" in warning for warning in (after.meta or {}).get("warnings") or [])


def test_appended_rows_get_them_too(client, auth_headers, project, db_session):
    people = named(db_session, project["id"], "people")
    households = named(db_session, project["id"], "households")
    assert link(client, auth_headers, people, households, ["size"]).status_code == 201

    more = pd.DataFrame({"pid": ["p9"], "hhid": [3.0], "age": [12.0]})
    upload(client, auth_headers, project["id"], mode="append", people=more)

    data = rows(named(db_session, project["id"], "people"))
    assert list(data["pid"]) == ["p1", "p2", "p3", "p4", "p5", "p9"]
    assert data["size"].iloc[-1] == 5.0


def test_what_would_repeat_rows_or_clash_is_refused(client, auth_headers, project, db_session):
    people = named(db_session, project["id"], "people")
    households = named(db_session, project["id"], "households")

    # Several people per household: their ages cannot sit beside one household row.
    repeated = link(client, auth_headers, households, people, ["age"])
    assert repeated.status_code == 422
    assert "more than one row" in repeated.json()["detail"]

    # A variable the dataset already has of its own.
    clash = link(client, auth_headers, people, households, ["hhid", "size"])
    assert clash.status_code == 201  # the key itself is never brought across
    again = link(
        client,
        auth_headers,
        people,
        households,
        ["size"],
        keys=[{"here": "hhid", "there": "hhid"}],
        key_match="text",
    )
    assert again.status_code == 422 and "already has 'size'" in again.json()["detail"]

    # Each brought in from the other: neither could be brought up to date first.
    ring = link(client, auth_headers, households, people, ["pid"])
    assert ring.status_code == 422 and "built from" in ring.json()["detail"]

    nothing = link(client, auth_headers, people, households, [])
    assert nothing.status_code == 422


def test_asking_again_adds_to_the_same_link(client, auth_headers, project, db_session):
    people = named(db_session, project["id"], "people")
    households = named(db_session, project["id"], "households")
    assert link(client, auth_headers, people, households, ["size"]).status_code == 201
    assert link(client, auth_headers, people, households, ["province"]).status_code == 201
    listed = client.get(
        f"/api/v1/datasets/{people.id}/linked-variables", headers=auth_headers
    ).json()
    assert len(listed) == 1 and listed[0]["variables"] == ["size", "province"]


def test_removing_takes_the_variables_away_or_keeps_them_as_they_are(
    client, auth_headers, project, db_session
):
    people = named(db_session, project["id"], "people")
    households = named(db_session, project["id"], "households")
    made = link(client, auth_headers, people, households, ["size"]).json()["link"]

    kept = client.delete(
        f"/api/v1/datasets/{people.id}/linked-variables/{made['id']}?keep_columns=true",
        headers=auth_headers,
    )
    assert kept.status_code == 200, kept.text
    assert "size" in rows(named(db_session, project["id"], "people")).columns
    # No longer brought up to date.
    upload(client, auth_headers, project["id"], households=HOUSEHOLDS.assign(size=[9.0, 9.0, 9.0]))
    assert rows(named(db_session, project["id"], "people"))["size"].iloc[0] == 4.0

    made = link(client, auth_headers, people, households, ["province"]).json()["link"]
    gone = client.delete(
        f"/api/v1/datasets/{people.id}/linked-variables/{made['id']}", headers=auth_headers
    )
    assert gone.status_code == 200
    data = rows(named(db_session, project["id"], "people"))
    assert "province" not in data.columns and list(data["pid"]) == ["p1", "p2", "p3", "p4", "p5"]


def test_keys_written_differently_can_be_matched_as_numbers(
    client, auth_headers, project, db_session
):
    # A code list keyed "01", "02", "03" against a household id stored as 1, 2, 3.
    people = named(db_session, project["id"], "people")
    regions = pd.DataFrame({"code": ["01", "02", "03"], "district": ["A", "B", "C"]})
    upload(client, auth_headers, project["id"], regions=regions)
    source = named(db_session, project["id"], "regions")

    # Matched on two differently named keys, compared as numbers.
    keys = [{"here": "hhid", "there": "code"}]
    matched = link(
        client, auth_headers, people, source, ["district"], keys=keys, key_match="number"
    )
    assert matched.status_code == 201, matched.text
    assert matched.json()["link"]["key_match"] == "number"
    assert list(rows(named(db_session, project["id"], "people"))["district"].fillna("")) == [
        "A",
        "A",
        "B",
        "",
        "C",
    ]


def test_deleting_the_source_names_the_datasets_that_bring_from_it(
    db_session, client, auth_headers, project
):
    from app.services.datasets import dependents_of

    people = named(db_session, project["id"], "people")
    households = named(db_session, project["id"], "households")
    assert link(client, auth_headers, people, households, ["size"]).status_code == 201
    found = dependents_of(db_session, named(db_session, project["id"], "households"))
    assert found.get("datasets bringing variables in from it") == 1
