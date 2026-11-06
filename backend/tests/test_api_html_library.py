"""The library of reusable HTML embeds.

An embed is usually a map, a video or a bureau's own banner, and the same one
belongs on several dashboards - often across surveys. Pasting the markup into
each widget let the copies drift, so a corrected link was fixed in one place
and left wrong in four.

The scoping rule here is deliberately not the one the widget pickers use. Those
narrow to a project because showing another project's charts would be a leak;
this offers a project's own snippets *and* every shared one, because reuse
across projects is the entire point of a library.
"""

from __future__ import annotations

import pytest

BASE = "/api/v1/dashboards/html-snippets"


@pytest.fixture
def library(client, auth_headers):
    """Two snippets: one shared with everybody, one owned by a project."""
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Library scope"}
    ).json()
    shared = client.post(
        BASE,
        headers=auth_headers,
        json={"name": "Office banner", "html": "<div>NSO</div>"},
    )
    assert shared.status_code == 201, shared.text
    owned = client.post(
        BASE,
        headers=auth_headers,
        json={
            "name": "Fieldwork map",
            "html": "<iframe src='https://example.org/map'></iframe>",
            "project_id": project["id"],
        },
    )
    assert owned.status_code == 201, owned.text
    yield {
        "project_id": project["id"],
        "shared_id": shared.json()["id"],
        "owned_id": owned.json()["id"],
    }
    for snippet_id in (shared.json()["id"], owned.json()["id"]):
        client.delete(f"{BASE}/{snippet_id}", headers=auth_headers)


def names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return sorted(item["name"] for item in response.json())


def test_a_snippet_keeps_the_markup_it_was_given(client, auth_headers, library):
    found = client.get(BASE, headers=auth_headers).json()
    banner = next(s for s in found if s["id"] == library["shared_id"])
    assert banner["html"] == "<div>NSO</div>"
    assert banner["project_id"] is None


def test_a_project_sees_its_own_snippets_and_the_shared_ones(
    client, auth_headers, library
):
    """The point of the library: narrowing to a project must not hide sharing."""
    listing = client.get(
        f"{BASE}?project_id={library['project_id']}", headers=auth_headers
    )
    assert names(listing) == ["Fieldwork map", "Office banner"]


def test_the_shared_area_shows_only_shared_snippets(client, auth_headers, library):
    """A snippet belonging to a project is not everybody's business."""
    assert names(client.get(f"{BASE}?project_id=none", headers=auth_headers)) == [
        "Office banner"
    ]


def test_a_snippet_can_be_renamed_and_rewritten(client, auth_headers, library):
    """Fixing a broken link in one place is why this exists."""
    response = client.patch(
        f"{BASE}/{library['shared_id']}",
        headers=auth_headers,
        json={"name": "Office banner 2026", "html": "<div>NSO 2026</div>"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Office banner 2026"
    assert response.json()["html"] == "<div>NSO 2026</div>"


def test_deleting_a_snippet_leaves_the_dashboards_using_it_alone(
    client, auth_headers, dataset_id, library
):
    """A widget holds its own copy of the markup, on purpose.

    Loading from the library takes a copy rather than a reference: a widget
    that changed under its dashboard because somebody edited a shared snippet
    would be a worse surprise than one that is merely out of date. So removing
    a snippet must not blank the dashboards built from it.
    """
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Embeds"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={
            "title": "Banner",
            "widget_type": "html",
            "config": {"html": "<div>NSO</div>"},
        },
    )

    assert client.delete(f"{BASE}/{library['shared_id']}", headers=auth_headers).status_code == 200

    rendered = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/data", headers=auth_headers
    )
    assert rendered.status_code == 200, rendered.text
    widget = next(iter(rendered.json()["widgets"].values()))
    assert widget["html"] == "<div>NSO</div>"


def test_a_snippet_needs_a_name(client, auth_headers):
    assert client.post(BASE, headers=auth_headers, json={"html": "<b>x</b>"}).status_code == 422
    assert (
        client.post(BASE, headers=auth_headers, json={"name": "", "html": "x"}).status_code
        == 422
    )


def test_a_missing_snippet_is_a_404(client, auth_headers):
    assert client.patch(
        f"{BASE}/does-not-exist", headers=auth_headers, json={"name": "x"}
    ).status_code == 404
    assert client.delete(f"{BASE}/does-not-exist", headers=auth_headers).status_code == 404
