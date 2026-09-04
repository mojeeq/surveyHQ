"""Naming a shared dashboard.

A name is not a token: it is guessable by design. So what matters here is not
that valid names are accepted but that the platform's own address, another
dashboard's name, and anything outside the one configured domain are not.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.hostnames import HostnameError, base_domain, label_of, normalise


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_domain", "dash.example.org")
    monkeypatch.setattr(settings, "public_url", "https://susodash.example.org")


@pytest.mark.parametrize(
    "typed",
    [
        "labour-force",
        "labour-force.dash.example.org",
        "  Labour-Force  ",
        "https://labour-force.dash.example.org/",
        "labour-force.dash.example.org/some/path",
        "LABOUR-FORCE.DASH.EXAMPLE.ORG",
    ],
)
def test_the_same_name_however_it_was_pasted(typed):
    """A bare label and a whole URL are the same request, not two rules."""
    assert normalise(typed) == "labour-force.dash.example.org"


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "   ",
        "-leading",
        "trailing-",
        "under_score",
        "two.labels",
        "spaces here",
        "dash.example.org",  # the domain itself
        "www",  # reserved
        "api",
        "admin",
        "elsewhere.example.com",  # outside the configured domain
    ],
)
def test_names_that_are_refused(typed):
    with pytest.raises(HostnameError):
        normalise(typed)


def test_a_name_outside_the_domain_is_not_quietly_moved_inside_it():
    """The refusal matters: silently rewriting it would hand out a name the
    certificate does not cover, and the dashboard would be unreachable."""
    with pytest.raises(HostnameError):
        normalise("evil.example.com")


def test_the_platforms_own_address_cannot_be_taken(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://reports.dash.example.org")
    with pytest.raises(HostnameError) as excinfo:
        normalise("reports")
    assert "platform" in str(excinfo.value)


def test_nothing_can_be_named_when_no_domain_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_domain", "")
    assert base_domain() == ""
    with pytest.raises(HostnameError) as excinfo:
        normalise("labour-force")
    assert "DASHBOARD_DOMAIN" in str(excinfo.value)


def test_the_label_comes_back_out_for_the_field_that_appends_the_domain():
    assert label_of("labour-force.dash.example.org") == "labour-force"
    assert label_of(None) == ""


# --- through the API ------------------------------------------------------


@pytest.fixture
def shared_dashboard(client, auth_headers):
    created = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Labour force 2026"}
    )
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    client.post(
        f"/api/v1/dashboards/{dashboard_id}/share",
        headers=auth_headers,
        params={"enable": True},
    )
    yield dashboard_id
    client.delete(f"/api/v1/dashboards/{dashboard_id}", headers=auth_headers)


def test_a_named_dashboard_answers_on_its_own_host(client, auth_headers, shared_dashboard):
    named = client.put(
        f"/api/v1/dashboards/{shared_dashboard}/hostname",
        headers=auth_headers,
        json={"hostname": "labour-force"},
    )
    assert named.status_code == 200, named.text
    assert named.json()["public_hostname"] == "labour-force.dash.example.org"

    # The Host header is what a browser sends when it visits the name.
    resolved = client.get(
        "/api/v1/public/site", headers={"Host": "labour-force.dash.example.org"}
    )
    assert resolved.status_code == 200
    body = resolved.json()["dashboard"]
    assert body and body["token"] == named.json()["public_token"]

    # Any other host is not this dashboard, and says nothing about it existing.
    assert (
        client.get("/api/v1/public/site", headers={"Host": "something-else.dash.example.org"})
        .json()["dashboard"]
        is None
    )


def test_a_name_cannot_be_taken_from_another_dashboard(client, auth_headers, shared_dashboard):
    client.put(
        f"/api/v1/dashboards/{shared_dashboard}/hostname",
        headers=auth_headers,
        json={"hostname": "taken-name"},
    )
    other = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Another board"}
    ).json()["id"]
    client.post(
        f"/api/v1/dashboards/{other}/share", headers=auth_headers, params={"enable": True}
    )
    clash = client.put(
        f"/api/v1/dashboards/{other}/hostname",
        headers=auth_headers,
        json={"hostname": "taken-name"},
    )
    assert clash.status_code == 409, clash.text
    client.delete(f"/api/v1/dashboards/{other}", headers=auth_headers)


def test_a_dashboard_that_is_not_shared_cannot_be_named(client, auth_headers):
    created = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Private board"}
    ).json()["id"]
    refused = client.put(
        f"/api/v1/dashboards/{created}/hostname",
        headers=auth_headers,
        json={"hostname": "private"},
    )
    assert refused.status_code == 409, refused.text
    client.delete(f"/api/v1/dashboards/{created}", headers=auth_headers)


def test_unsharing_takes_the_name_with_it(client, auth_headers, shared_dashboard):
    """Otherwise the DNS record still resolves, to a dashboard nobody may read."""
    client.put(
        f"/api/v1/dashboards/{shared_dashboard}/hostname",
        headers=auth_headers,
        json={"hostname": "closing-soon"},
    )
    stopped = client.post(
        f"/api/v1/dashboards/{shared_dashboard}/share",
        headers=auth_headers,
        params={"enable": False},
    )
    assert stopped.status_code == 200
    assert stopped.json()["public_hostname"] is None
    assert (
        client.get("/api/v1/public/site", headers={"Host": "closing-soon.dash.example.org"})
        .json()["dashboard"]
        is None
    )
