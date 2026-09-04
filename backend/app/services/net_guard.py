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
itself, never a survey server - and link-local, which is where cloud providers
put the unauthenticated metadata service that hands out machine credentials.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeAddressError(ValueError):
    """The URL points somewhere this platform will not fetch from."""


def _refused(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if address.is_loopback:
        return (
            "points at this server itself. Enter the address of the Survey "
            "Solutions server as it is reached from here."
        )
    if address.is_link_local:
        # 169.254.169.254 and its IPv6 equivalent; also everything else in the
        # range, none of which is a survey server.
        return "is a link-local address, which cannot be a Survey Solutions server."
    if address.is_multicast or address.is_reserved or address.is_unspecified:
        return "is not a routable address."
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
