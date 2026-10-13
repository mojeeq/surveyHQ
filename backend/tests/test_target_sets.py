"""Quota lists kept as records of their own.

A census carries its targets as a list: so many households in each of two
thousand enumeration areas. The list is prepared before fieldwork by somebody
who is not watching a dashboard, it outlives the indicators that read it, and
several indicators read the same one - households enumerated, questionnaires
received, interviews verified, all against the same area quotas.

Held inside an indicator it had to be retyped for each of them and could only
be looked at through that indicator's tile. These cover it as its own thing:
who can see it, what happens to the indicators when it goes, and that two
thousand categories is an ordinary size rather than a limit.
"""

from __future__ import annotations

import pandas as pd

from tests.test_api_analytics import _stata_bytes, _zip_bytes


def _dataset(client, auth_headers, name: str = "quota") -> str:
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(9)],
            "area": ["EA01"] * 4 + ["EA02"] * 3 + ["EA03"] * 2,
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
    )
    return uploaded.json()["datasets"][0]["id"]


def _set(client, auth_headers, dataset_id: str, **extra) -> dict:
    body = {
        "name": "Area quotas",
        "dataset_id": dataset_id,
        "variable": "area",
        "targets": {"EA01": 5, "EA02": 4, "EA03": 3},
        **extra,
    }
    created = client.post("/api/v1/monitoring/target-sets", headers=auth_headers, json=body)
    assert created.status_code == 201, created.text
    return created.json()


def test_a_set_is_created_and_read_back_whole(client, auth_headers):
    dataset_id = _dataset(client, auth_headers)
    created = _set(client, auth_headers, dataset_id)

    read = client.get(
        f"/api/v1/monitoring/target-sets/{created['id']}", headers=auth_headers
    )

    assert read.status_code == 200
    assert read.json()["targets"] == {"EA01": 5, "EA02": 4, "EA03": 3}
    assert read.json()["variable"] == "area"


def test_the_list_leaves_the_rows_behind(client, auth_headers):
    """Two thousand quotas have no business in a page that lists sets."""
    dataset_id = _dataset(client, auth_headers)
    _set(client, auth_headers, dataset_id)

    listed = client.get("/api/v1/monitoring/target-sets", headers=auth_headers).json()
    mine = next(one for one in listed if one["name"] == "Area quotas")

    assert "targets" not in mine
    assert mine["categories"] == 3
    assert mine["total"] == 12
    assert mine["dataset_name"]
    assert mine["used_by"] == 0


def test_two_thousand_categories_is_an_ordinary_size(client, auth_headers):
    """A census set, which is the case this exists for."""
    dataset_id = _dataset(client, auth_headers)
    many = {f"EA{area:04d}": area % 50 + 1 for area in range(2000)}

    created = _set(client, auth_headers, dataset_id, name="Census areas", targets=many)
    read = client.get(
        f"/api/v1/monitoring/target-sets/{created['id']}", headers=auth_headers
    ).json()

    assert len(read["targets"]) == 2000
    listed = client.get("/api/v1/monitoring/target-sets", headers=auth_headers).json()
    assert next(one for one in listed if one["name"] == "Census areas")["categories"] == 2000


def test_a_paste_replaces_the_list_rather_than_merging_into_it(client, auth_headers):
    """A pasted list is the whole list: merging would make removal impossible."""
    dataset_id = _dataset(client, auth_headers)
    created = _set(client, auth_headers, dataset_id)

    client.patch(
        f"/api/v1/monitoring/target-sets/{created['id']}",
        headers=auth_headers,
        json={"targets": {"EA01": 9}},
    )

    read = client.get(
        f"/api/v1/monitoring/target-sets/{created['id']}", headers=auth_headers
    ).json()
    assert read["targets"] == {"EA01": 9}

# --- What an indicator does with one -----------------------------------------


def _indicator(client, auth_headers, dataset_id: str, **extra) -> dict:
    body = {
        "name": "Interviews",
        "dataset_id": dataset_id,
        "spec": {"measures": [{"agg": "count"}]},
        "target_value": 12,
        "breakdown_variable": "area",
        **extra,
    }
    created = client.post("/api/v1/monitoring/indicators", headers=auth_headers, json=body)
    assert created.status_code == 201, created.text
    return created.json()


def test_an_indicator_is_judged_by_the_set_it_points_at(client, auth_headers):
    dataset_id = _dataset(client, auth_headers)
    quotas = _set(client, auth_headers, dataset_id)
    indicator = _indicator(client, auth_headers, dataset_id, target_set_id=quotas["id"])

    refreshed = client.post(
        f"/api/v1/monitoring/indicators/{indicator['id']}/refresh", headers=auth_headers
    ).json()

    progress = refreshed["breakdown_progress"]
    # Four interviews against a quota of five, not against the headline twelve.
    assert progress["EA01"]["target"] == 5
    assert progress["EA01"]["percent"] == 80.0
    assert progress["EA03"]["target"] == 3


def test_a_set_wins_over_the_indicator_s_own_quotas(client, auth_headers):
    """Two half-applied lists is a number nobody can account for."""
    dataset_id = _dataset(client, auth_headers)
    quotas = _set(client, auth_headers, dataset_id)
    indicator = _indicator(
        client,
        auth_headers,
        dataset_id,
        breakdown_targets={"EA01": 99},
        target_set_id=quotas["id"],
    )

    refreshed = client.post(
        f"/api/v1/monitoring/indicators/{indicator['id']}/refresh", headers=auth_headers
    ).json()

    assert refreshed["breakdown_progress"]["EA01"]["target"] == 5


def test_unlinking_goes_back_to_the_indicator_s_own(client, auth_headers):
    dataset_id = _dataset(client, auth_headers)
    quotas = _set(client, auth_headers, dataset_id)
    indicator = _indicator(
        client,
        auth_headers,
        dataset_id,
        breakdown_targets={"EA01": 99},
        target_set_id=quotas["id"],
    )

    client.patch(
        f"/api/v1/monitoring/indicators/{indicator['id']}",
        headers=auth_headers,
        json={"target_set_id": ""},
    )
    refreshed = client.post(
        f"/api/v1/monitoring/indicators/{indicator['id']}/refresh", headers=auth_headers
    ).json()

    assert refreshed["breakdown_progress"]["EA01"]["target"] == 99


def test_a_set_from_another_dataset_is_refused(client, auth_headers):
    """Its keys are values that cannot appear in this indicator's data."""
    one = _dataset(client, auth_headers, "first")
    other = _dataset(client, auth_headers, "second")
    quotas = _set(client, auth_headers, other)

    refused = client.post(
        "/api/v1/monitoring/indicators",
        headers=auth_headers,
        json={
            "name": "Interviews",
            "dataset_id": one,
            "spec": {"measures": [{"agg": "count"}]},
            "breakdown_variable": "area",
            "target_set_id": quotas["id"],
        },
    )

    assert refused.status_code == 400
    assert "different dataset" in refused.text


def test_deleting_a_set_leaves_its_indicators_working(client, auth_headers):
    """The link clears; nothing that was reading it stops reporting."""
    dataset_id = _dataset(client, auth_headers)
    quotas = _set(client, auth_headers, dataset_id)
    indicator = _indicator(client, auth_headers, dataset_id, target_set_id=quotas["id"])

    deleted = client.delete(
        f"/api/v1/monitoring/target-sets/{quotas['id']}", headers=auth_headers
    )

    assert deleted.status_code == 200
    assert "1 indicator" in deleted.json()["detail"]
    refreshed = client.post(
        f"/api/v1/monitoring/indicators/{indicator['id']}/refresh", headers=auth_headers
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["breakdown_progress"]["EA01"]["target"] is None


def test_the_list_says_how_many_indicators_read_a_set(client, auth_headers):
    dataset_id = _dataset(client, auth_headers)
    quotas = _set(client, auth_headers, dataset_id)
    _indicator(client, auth_headers, dataset_id, target_set_id=quotas["id"])
    _indicator(
        client, auth_headers, dataset_id, name="Verified", target_set_id=quotas["id"]
    )

    listed = client.get("/api/v1/monitoring/target-sets", headers=auth_headers).json()

    assert next(one for one in listed if one["id"] == quotas["id"])["used_by"] == 2


# --- How many groups a breakdown reports -------------------------------------


def test_a_breakdown_reports_thousands_of_groups(client, auth_headers):
    """Two hundred was a dropdown's worth; a census has two thousand areas.

    The ceiling used to cut the breakdown at two hundred groups without a
    word, so a tile broken down by enumeration area reported a tenth of the
    country and looked exactly like one reporting all of it.
    """
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(1200)],
            "area": [f"EA{i % 600:04d}" for i in range(1200)],
        }
    )
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "wide.zip",
                _zip_bytes({"wide.dta": _stata_bytes(frame)}),
                "application/zip",
            )
        },
    )
    dataset_id = uploaded.json()["datasets"][0]["id"]
    indicator = _indicator(client, auth_headers, dataset_id, name="Interviews by area")

    refreshed = client.post(
        f"/api/v1/monitoring/indicators/{indicator['id']}/refresh", headers=auth_headers
    ).json()

    assert len(refreshed["breakdown"]) == 600
    assert refreshed["breakdown_truncated"] is False


def test_a_breakdown_past_the_ceiling_says_so(monkeypatch, client, auth_headers):
    """The ceiling stays - a breakdown by interview key is not a breakdown."""
    from app.services import monitoring

    monkeypatch.setattr(monitoring, "BREAKDOWN_LIMIT", 2)
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(12)],
            "area": [f"EA{i % 5:04d}" for i in range(12)],
        }
    )
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "small.zip",
                _zip_bytes({"small.dta": _stata_bytes(frame)}),
                "application/zip",
            )
        },
    )
    dataset_id = uploaded.json()["datasets"][0]["id"]
    indicator = _indicator(client, auth_headers, dataset_id, name="Capped")

    refreshed = client.post(
        f"/api/v1/monitoring/indicators/{indicator['id']}/refresh", headers=auth_headers
    ).json()

    assert len(refreshed["breakdown"]) == 2
    assert refreshed["breakdown_truncated"] is True
