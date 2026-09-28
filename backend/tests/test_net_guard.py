"""Addresses the platform will not fetch a survey server from.

A connection's base URL is chosen by a manager and fetched by the server, which
is a request made on someone's behalf to wherever they name. Managers are
trusted, so this is not about stopping them working - private LAN ranges are
deliberately allowed, because Survey Solutions is very often installed on an
organisation's own network. It is about the addresses where a mistyped or planted
URL turns into a credential leak.

Those cannot be refused by range, which is the whole difficulty: AWS answers
over IPv6 from fd00:ec2::254, inside the same fd00::/7 an organisation numbers
its own network from, and Alibaba answers from 100.100.100.200, which looks
like any other routable address. Both have to be named one at a time, and both
were reachable until they were.
"""

from __future__ import annotations

import pytest

from app.services.net_guard import UnsafeAddressError, check_url


@pytest.mark.parametrize(
    "url",
    [
        # AWS, Azure, GCP, DigitalOcean and Hetzner all answer here. This one is
        # link-local as well, and was refused before any of the rest were.
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254",
        # AWS over IPv6. Not a link-local address, and so not refused at all
        # until it was named: fd00::/7 is where an organisation's own IPv6
        # network lives, so the range has to stay allowed.
        "http://[fd00:ec2::254]/latest/meta-data/iam/security-credentials/",
        # The same address written out in full. Compared as an address rather
        # than as text, so how it is spelt does not matter.
        "http://[fd00:0ec2:0000:0000:0000:0000:0000:0254]/",
        # Alibaba Cloud, in a range that looks entirely routable.
        "http://100.100.100.200/latest/meta-data/",
        # Oracle Cloud's older endpoint.
        "http://192.0.0.192/opc/v1/instance/",
    ],
)
def test_the_metadata_service_is_refused(url):
    """Where cloud providers hand out machine credentials to anyone who asks.

    The one thing a survey server is certainly not, and the one address where a
    URL somebody was talked into entering fetches this machine's own keys.
    """
    with pytest.raises(UnsafeAddressError, match="metadata service"):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        # An IPv4 address written as an IPv6 one. Python sees through this for
        # its own is_link_local, and a list of addresses does not, so the
        # mapping is undone before the list is consulted.
        "http://[::ffff:169.254.169.254]/",
        "http://[::ffff:100.100.100.200]/",
        # 6to4, which carries the address in the second and third groups.
        "http://[2002:6464:64c8::1]/",
    ],
)
def test_a_metadata_address_tunnelled_inside_an_ipv6_one_is_refused(url):
    """Written another way, it is still the same machine answering."""
    with pytest.raises(UnsafeAddressError, match="metadata service"):
        check_url(url)


@pytest.mark.parametrize("url", ["https://[fe80::1]/api", "http://169.254.1.5/"])
def test_link_local_is_refused(url):
    """The rest of the range, none of which is a survey server either."""
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
        # The ranges the metadata addresses sit in, which is why they have to be
        # named one at a time: blocking either of these would refuse an
        # organisation's own server.
        "http://[fd00:1234::5]/hq",
        "http://100.100.100.201/hq",
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
