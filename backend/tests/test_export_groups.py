"""A widget group's own ground and heading size, kept and carried into the file.

A group could be named and given a frame colour that nothing let anybody
change, and its background and heading size were fixed: a faint grey wash
and a 12px heading, however much the group was the point of the page.
"""

from __future__ import annotations

import json
import re

from app.services.static_export import _group_title_size


def test_a_groups_ground_and_heading_size_are_kept_and_reach_the_file(client, auth_headers):
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Grouped board"}
    ).json()
    group = {
        "id": "g1", "name": "Fieldwork", "page": 0, "x": 0, "y": 0, "w": 12,
        "background": "#0b2545", "title_size": 22, "color": "",
    }
    saved = client.patch(
        f"/api/v1/dashboards/{board['id']}", headers=auth_headers, json={"groups": [group]}
    )
    assert saved.status_code == 200, saved.text
    kept = saved.json()["groups"][0]
    assert (kept["background"], kept["title_size"]) == ("#0b2545", 22)

    html = client.get(f"/api/v1/dashboards/{board['id']}/export.html", headers=auth_headers)
    assert html.status_code == 200, html.text
    payload = json.loads(re.search(r'id="board-data">(.*?)</script>', html.text, re.S).group(1))
    carried = payload["groups"][0]
    assert (carried["background"], carried["title_size"]) == ("#0b2545", 22)


def test_a_value_that_would_break_out_of_a_style_is_not_carried(client, auth_headers):
    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Odd group"}
    ).json()
    client.patch(
        f"/api/v1/dashboards/{board['id']}",
        headers=auth_headers,
        json={"groups": [{"id": "g1", "name": "x", "page": 0, "x": 0, "y": 0, "w": 6,
                          "background": "red;}</style><script>", "title_size": "huge"}]},
    )
    html = client.get(f"/api/v1/dashboards/{board['id']}/export.html", headers=auth_headers)
    carried = json.loads(re.search(r'id="board-data">(.*?)</script>', html.text, re.S).group(1))[
        "groups"
    ][0]
    assert carried["background"] == ""
    assert carried["title_size"] == 0


def test_a_heading_size_is_one_a_page_can_be_drawn_at():
    assert _group_title_size(None) == 0
    assert _group_title_size(0) == 0
    assert _group_title_size(20) == 20
    assert _group_title_size(400) == 48
    assert _group_title_size(2) == 8
    assert _group_title_size(float("nan")) == 0
