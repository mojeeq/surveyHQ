"""Addresses the platform will not fetch a survey server from.

A connection's base URL is chosen by a manager and fetched by the server, which
is a request made on someone's behalf to wherever they name. Managers are
trusted, so this is not about stopping them working - private LAN ranges are
deliberately allowed, because Survey Solutions is very often installed on an
organisation's own network. It is about the two addresses where a mistyped or
planted URL turns into a credential leak.
"""

from __future__ import annotations

import pytest

from app.services.net_guard import UnsafeAddressError, check_url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # the cloud metadata service
        "http://169.254.169.254",
        "https://[fe80::1]/api",
    ],
)
def test_link_local_is_refused(url):
    """Where cloud providers hand out machine credentials to anyone who asks."""
    with pytest.raises(UnsafeAddressError, match="link-local"):
        check_url(url)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8000/api", "http://localhost:8000", "https://[::1]/"]
)
def test_loopback_is_refused(url):
    """Inside the API container this is the API itself, never a survey server."""
    with pytest.raises(UnsafeAddressError, match="this server itself"):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5/hq",
        "http://192.168.1.20:8080",
        "http://172.16.4.4",
    ],
)
def test_a_server_on_the_organisations_own_network_is_allowed(url):
    """The common case for a statistics office. Refusing it would break them."""
    check_url(url)


@pytest.mark.parametrize("url", ["ftp://survey.example.org", "file:///etc/passwd"])
def test_only_http_is_fetched(url):
    with pytest.raises(UnsafeAddressError, match="not an http"):
        check_url(url)


def test_a_name_that_does_not_resolve_is_left_alone():
    """The guard refuses what it can identify, and invents no other failures.

    A DNS problem should be reported by the thing that actually failed, in its
    own words, rather than arriving as a security message.
    """
    check_url("https://survey.invalid-tld-that-does-not-exist")


def test_a_url_with_no_host_is_refused():
    with pytest.raises(UnsafeAddressError, match="does not name a server"):
        check_url("http:///api/v1")
