"""Refusing to fetch addresses a survey server has no business living at.

A connection's base URL is supplied by a manager and fetched by the server, so
it is a request the platform makes on someone's behalf to wherever they name -
the shape of a server-side request forgery. Managers are trusted, so this is not
about stopping them doing their job; it is about the two addresses where a
mistyped or planted URL turns into a credential leak.

Private LAN ranges are deliberately allowed. Survey Solutions is very often
installed on an organisation's own network, and a monitoring tool that could not
reach 10.0.0.5 would be useless to exactly the statistics offices this is for.
What is refused is loopback - which inside the API container means the API
itself, never a survey server - and the unauthenticated metadata services that
hand out machine credentials to anything able to make a request from the
instance.

Those are named one address at a time, and cannot be a range. The IPv4 one is
link-local, so refusing that whole range costs nothing; the others are not.
AWS answers on fd00:ec2::254, which sits in the same fd00::/7 an organisation
numbers its own IPv6 network from, and Alibaba answers on 100.100.100.200,
which looks like an ordinary routable address. Refusing either range would
break exactly the installations this platform is for.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeAddressError(ValueError):
    """The URL points somewhere this platform will not fetch from."""


# The unauthenticated instance metadata services. Each hands out the machine's
# own credentials to anything that can make an HTTP request from it, which is
# what turns a planted URL into a credential leak.
#
# 169.254.169.254 is also link-local and would be refused below regardless. It
# is named here anyway: what makes it refused should be that it is the metadata
# service, not a property of the range it happens to sit in.
METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(address)
    for address in (
        "169.254.169.254",  # AWS, Azure, GCP, DigitalOcean, Hetzner, Oracle
        "fd00:ec2::254",  # AWS over IPv6, which is not a link-local address
        "100.100.100.200",  # Alibaba Cloud, in a range that looks routable
        "192.0.0.192",  # Oracle Cloud's older endpoint
    )
)


def _candidates(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """The address, and any IPv4 address carried inside it.

    `::ffff:100.100.100.200` and `2002:6464:64c8::1` both end up at
    100.100.100.200. Python's own `is_loopback` and `is_link_local` see through
    the first of those; nothing sees through the second, and comparing against a
    list of addresses sees through neither. So each form is judged on its own as
    well as whole.

    Not exhaustive - NAT64 and other tunnels can carry an address in ways this
    does not unpick. This is a guard against a mistyped or planted URL, not a
    sandbox, and it says so here rather than implying more than it does.
    """
    found = [address]
    for embedded in (
        getattr(address, "ipv4_mapped", None),
        getattr(address, "sixtofour", None),
    ):
        if embedded is not None:
            found.append(embedded)
    # teredo is (server, client); the client is the host behind the tunnel.
    teredo = getattr(address, "teredo", None)
    if teredo:
        found.append(teredo[1])
    return found


def _verdict(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if address.is_loopback:
        return (
            "points at this server itself. Enter the address of the Survey "
            "Solutions server as it is reached from here."
        )
    if address.is_link_local:
        # Everything else in the range, none of which is a survey server.
        return "is a link-local address, which cannot be a Survey Solutions server."
    if address.is_multicast or address.is_reserved or address.is_unspecified:
        return "is not a routable address."
    return ""


def _refused(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    candidates = _candidates(address)
    # Asked of every form first, and before anything else, so that an address
    # which is both - ::ffff:169.254.169.254 is link-local as well - is refused
    # for the reason worth telling somebody about.
    if any(candidate in METADATA_ADDRESSES for candidate in candidates):
        return (
            "is a cloud provider's metadata service, which hands out this "
            "machine's own credentials rather than survey data."
        )
    for candidate in candidates:
        reason = _verdict(candidate)
        if reason:
            return reason
    return ""


def check_url(url: str) -> None:
    """Raise UnsafeAddressError if url points somewhere we will not fetch.

    Only refuses what it can positively identify as unsafe. A name that does not
    resolve is left alone rather than rejected here: the connection attempt that
    follows will fail on its own and say so in the words of the thing that
    actually failed, and a guard that turned every DNS hiccup into a security
    message would be read as one.

    Every address a name resolves to is checked, not just the first: a name
    answering with both a public and a loopback address would otherwise pass
    here and connect to the wrong one.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeAddressError(
            f"'{parsed.scheme or url}' is not an http or https address."
        )
    host = parsed.hostname
    if not host:
        raise UnsafeAddressError(f"'{url}' does not name a server.")

    try:
        resolved = socket.getaddrinfo(host, parsed.port or 0, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return

    for entry in resolved:
        try:
            address = ipaddress.ip_address(entry[4][0])
        except ValueError:  # pragma: no cover - getaddrinfo always gives one
            continue
        reason = _refused(address)
        if reason:
            raise UnsafeAddressError(f"'{host}' {reason}")
