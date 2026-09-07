"""Listing datasets one project at a time.

Anything built on a dataset belongs to whatever project that dataset belongs
to, so the pickers that start such a thing - a new indicator, most of all - ask
for the datasets of the project the page is filtered to. Choosing from every
dataset on the server was a list to hunt through, and an indicator built from
the wrong one quietly ends up in the wrong project.

The shared area is spelled "none" here, because an empty project_id on this
endpoint is an absent filter rather than a place. Endpoints that list what
hangs off a dataset read an empty string as the shared area instead, so the two
conventions are pinned in their own tests and neither can drift onto the other.
"""

from __future__ import annotations

import pytest


def upload(client, auth_headers, name: str, project_id: str = "") -> str:
    response = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": (f"{name}.csv", b"id,region\n1,North\n2,South\n", "text/csv")},
        data={"project_id": project_id} if project_id else {},
    )
    assert response.status_code in (200, 201), response.text
    body = response.json()
    # One file comes back as the dataset; several come back as a list of them.
    return (body["datasets"][0] if "datasets" in body else body)["id"]


def names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return sorted(item["name"] for item in response.json()["items"])


@pytest.fixture
def spread(client, auth_headers):
    """One dataset in a project and one in the shared area."""
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Filtered"}
    ).json()
    inside = upload(client, auth_headers, "inside_the_project", project["id"])
    outside = upload(client, auth_headers, "out_in_the_open")
    return {"project": project["id"], "inside": inside, "outside": outside}


def test_a_project_id_lists_only_that_project_s_datasets(client, auth_headers, spread):
    listed = names(
        client.get(f"/api/v1/datasets?limit=200&project_id={spread['project']}", headers=auth_headers)
    )
    assert "inside_the_project" in listed
    assert "out_in_the_open" not in listed


def test_none_lists_the_shared_area(client, auth_headers, spread):
    """The shared area is a real place, and this is how it is named."""
    listed = names(client.get("/api/v1/datasets?limit=200&project_id=none", headers=auth_headers))
    assert "out_in_the_open" in listed
    assert "inside_the_project" not in listed


def test_no_project_id_lists_everything(client, auth_headers, spread):
    """The unfiltered list, which is what "All projects" asks for."""
    listed = names(client.get("/api/v1/datasets?limit=200", headers=auth_headers))
    assert "inside_the_project" in listed
    assert "out_in_the_open" in listed


def test_the_filter_still_narrows_to_what_is_ready(client, auth_headers, spread):
    """The indicator picker asks for both at once, so they have to compose."""
    listed = names(
        client.get(
            f"/api/v1/datasets?limit=200&status=ready&project_id={spread['project']}",
            headers=auth_headers,
        )
    )
    assert listed == ["inside_the_project"]
