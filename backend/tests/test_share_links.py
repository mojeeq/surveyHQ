"""Several links to one dashboard, each closable, some with a password.

One board goes to a minister, to the field supervisors, and to a donor, and
those audiences do not end together. With a single link, closing the donor's
access closed everybody's, so the way to do it was to build the dashboard
again. Each audience gets its own address now, and closing one leaves the rest
alone.

A password is not a login. Everyone who has it is the same anonymous reader; it
is there so a forwarded link is not a public one.
"""

from __future__ import annotations

import pytest

PASSWORD = "vanuatu-lfs-2026"


@pytest.fixture
def board(client, auth_headers, dataset_id) -> str:
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "By region",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dataset_id": dataset_id,
                    "dimensions": [{"variable": "region"}],
                    "measures": [{"agg": "count"}],
                }
            },
        },
    ).json()
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Many audiences"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "By region", "widget_type": "chart", "chart_id": chart["id"]},
    )
    return dashboard["id"]


def make_link(client, auth_headers, board, name="Link", password=""):
    response = client.post(
        f"/api/v1/dashboards/{board}/share-links",
        headers=auth_headers,
        json={"name": name, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


def opens(client, token, grant="") -> int:
    return client.get(
        f"/api/v1/public/dashboards/{token}",
        headers={"X-Share-Grant": grant} if grant else {},
    ).status_code


def test_a_dashboard_can_have_several_links_at_once(client, auth_headers, board):
    minister = make_link(client, auth_headers, board, "Minister")
    field = make_link(client, auth_headers, board, "Field supervisors")
    assert minister["token"] != field["token"]
    assert opens(client, minister["token"]) == 200
    assert opens(client, field["token"]) == 200


def test_closing_one_link_leaves_the_others_open(client, auth_headers, board):
    """The whole point: the donor's access ends without ending anybody else's."""
    donor = make_link(client, auth_headers, board, "Donor")
    field = make_link(client, auth_headers, board, "Field supervisors")

    closed = client.patch(
        f"/api/v1/dashboards/{board}/share-links/{donor['id']}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["is_active"] is False

    assert opens(client, donor["token"]) == 404
    assert opens(client, field["token"]) == 200


def test_a_closed_link_reopens_at_the_same_address(client, auth_headers, board):
    """Closed rather than deleted, because the link is already in someone's inbox."""
    link = make_link(client, auth_headers, board, "Seasonal")
    client.patch(
        f"/api/v1/dashboards/{board}/share-links/{link['id']}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert opens(client, link["token"]) == 404
    client.patch(
        f"/api/v1/dashboards/{board}/share-links/{link['id']}",
        headers=auth_headers,
        json={"is_active": True},
    )
    assert opens(client, link["token"]) == 200


def test_a_password_is_needed_before_the_dashboard_is_readable(
    client, auth_headers, board
):
    link = make_link(client, auth_headers, board, "Donor", password=PASSWORD)
    assert link["has_password"] is True
    # The hash is never handed out.
    assert "password" not in link and "password_hash" not in link

    assert opens(client, link["token"]) == 401

    refused = client.post(
        f"/api/v1/public/dashboards/{link['token']}/unlock", json={"password": "wrong"}
    )
    assert refused.status_code == 401

    unlocked = client.post(
        f"/api/v1/public/dashboards/{link['token']}/unlock", json={"password": PASSWORD}
    )
    assert unlocked.status_code == 200, unlocked.text
    grant = unlocked.json()["grant"]
    assert grant
    assert opens(client, link["token"], grant) == 200


def test_a_grant_is_good_for_its_own_link_only(client, auth_headers, board):
    """Otherwise unlocking the cheap link would open the guarded one."""
    guarded = make_link(client, auth_headers, board, "Guarded", password=PASSWORD)
    other = make_link(client, auth_headers, board, "Other", password="something-else")

    grant = client.post(
        f"/api/v1/public/dashboards/{other['token']}/unlock",
        json={"password": "something-else"},
    ).json()["grant"]
    assert opens(client, other["token"], grant) == 200
    assert opens(client, guarded["token"], grant) == 401


def test_every_route_behind_a_password_is_shut_not_just_the_first(
    client, auth_headers, board
):
    """A locked dashboard whose data endpoint answered would not be locked."""
    link = make_link(client, auth_headers, board, "Donor", password=PASSWORD)
    token = link["token"]
    assert client.post(f"/api/v1/public/dashboards/{token}/data").status_code == 401
    assert client.get(f"/api/v1/public/dashboards/{token}/logo").status_code == 401
    assert (
        client.get(f"/api/v1/public/dashboards/{token}/filter-values/region").status_code
        == 401
    )


def test_a_password_can_be_taken_off_and_put_back(client, auth_headers, board):
    link = make_link(client, auth_headers, board, "Donor", password=PASSWORD)
    assert opens(client, link["token"]) == 401

    cleared = client.patch(
        f"/api/v1/dashboards/{board}/share-links/{link['id']}",
        headers=auth_headers,
        json={"password": ""},
    ).json()
    assert cleared["has_password"] is False
    assert opens(client, link["token"]) == 200

    client.patch(
        f"/api/v1/dashboards/{board}/share-links/{link['id']}",
        headers=auth_headers,
        json={"password": "another-one"},
    )
    assert opens(client, link["token"]) == 401


def test_renaming_a_link_leaves_its_password_alone(client, auth_headers, board):
    """exclude_unset: a field not mentioned is untouched, not cleared."""
    link = make_link(client, auth_headers, board, "Donor", password=PASSWORD)
    renamed = client.patch(
        f"/api/v1/dashboards/{board}/share-links/{link['id']}",
        headers=auth_headers,
        json={"name": "Donor, final report"},
    ).json()
    assert renamed["name"] == "Donor, final report"
    assert renamed["has_password"] is True
    assert opens(client, link["token"]) == 401


def test_the_original_single_link_still_works(client, auth_headers, board):
    """Every dashboard shared before this existed keeps the address it had."""
    token = client.post(
        f"/api/v1/dashboards/{board}/share?enable=true", headers=auth_headers
    ).json()["public_token"]
    assert opens(client, token) == 200


def test_opening_a_link_is_counted(client, auth_headers, board):
    """So a link nobody uses can be recognised and closed."""
    link = make_link(client, auth_headers, board, "Counted")
    for _ in range(3):
        client.get(f"/api/v1/public/dashboards/{link['token']}")
    listed = client.get(
        f"/api/v1/dashboards/{board}/share-links", headers=auth_headers
    ).json()
    counted = next(item for item in listed if item["id"] == link["id"])
    assert counted["view_count"] == 3
    assert counted["last_viewed_at"]


def test_a_deleted_link_is_gone_for_good(client, auth_headers, board):
    link = make_link(client, auth_headers, board, "Temporary")
    assert (
        client.delete(
            f"/api/v1/dashboards/{board}/share-links/{link['id']}", headers=auth_headers
        ).status_code
        == 200
    )
    assert opens(client, link["token"]) == 404
    listed = client.get(
        f"/api/v1/dashboards/{board}/share-links", headers=auth_headers
    ).json()
    assert link["id"] not in [item["id"] for item in listed]


def test_links_belong_to_their_own_dashboard(client, auth_headers, board, dataset_id):
    """A link id from one board cannot be edited through another."""
    other = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Elsewhere"}
    ).json()
    link = make_link(client, auth_headers, board, "Mine")
    assert (
        client.patch(
            f"/api/v1/dashboards/{other['id']}/share-links/{link['id']}",
            headers=auth_headers,
            json={"is_active": False},
        ).status_code
        == 404
    )
