"""Giving a shared dashboard a name people can type.

A shared link is a 64-character token: unguessable, and unrepeatable down a
phone line. A published results page wants to be `labour-force.dash.gov.vu`,
which is a different thing in one important way - the address is no longer the
secret. Anyone who guesses the name reaches the dashboard, so assigning one is
publishing, and the interface says so.

Everything here is one subdomain of one configured base domain, which is what
makes the deployment side a single wildcard DNS record and a single wildcard
certificate rather than work per dashboard.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.config import settings

# A DNS label: letters, digits and inner hyphens, up to 63 characters.
LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

# Names that belong to the deployment rather than to anybody's dashboard.
# Handing one of these out would point a name people rely on at a dashboard.
RESERVED = frozenset(
    {
        "www",
        "api",
        "app",
        "admin",
        "mail",
        "smtp",
        "imap",
        "ftp",
        "static",
        "assets",
        "cdn",
        "dashboard",
        "dashboards",
        "login",
        "auth",
        "status",
        "health",
    }
)


class HostnameError(ValueError):
    """The requested name cannot be given to a dashboard."""


def base_domain() -> str:
    """The domain dashboards are named under, or "" when none is configured."""
    return (settings.dashboard_domain or "").strip().lower().strip(".")


def enabled() -> bool:
    return bool(base_domain())


def platform_host() -> str:
    """The host the platform itself answers on, which is never available."""
    parsed = urlparse(settings.public_url or "")
    return (parsed.hostname or "").lower()


def normalise(value: str) -> str:
    """Turn what somebody typed into the full hostname it means.

    Both a bare label and the whole name are accepted, because both are what
    people paste: "labour-force" and "labour-force.dash.gov.vu" are the same
    request, and refusing one of them is a puzzle rather than a rule.
    """
    domain = base_domain()
    if not domain:
        raise HostnameError(
            "No dashboard domain is configured. An administrator sets "
            "DASHBOARD_DOMAIN in .env, alongside the wildcard DNS record and "
            "certificate for it."
        )

    text = (value or "").strip().lower().strip(".")
    # Pasted with a scheme, or with a path on the end: take the host out of it.
    if "//" in text:
        text = urlparse(text).hostname or ""
    text = text.split("/")[0].strip(".")
    if not text:
        raise HostnameError("Give the dashboard a name")

    if text == domain:
        raise HostnameError(f"'{domain}' is the domain itself, not a name within it")
    if text.endswith(f".{domain}"):
        label = text[: -len(domain) - 1]
    else:
        label = text

    if "." in label:
        raise HostnameError(
            f"Use a single name under {domain}, e.g. labour-force.{domain}"
        )
    if not LABEL.match(label):
        raise HostnameError(
            "A name can hold letters, digits and hyphens, and cannot start or "
            "end with a hyphen"
        )
    if label in RESERVED:
        raise HostnameError(f"'{label}' is reserved for the platform itself")

    hostname = f"{label}.{domain}"
    if hostname == platform_host():
        raise HostnameError("That is the platform's own address")
    return hostname


def label_of(hostname: str | None) -> str:
    """The label part, for showing in a field that appends the domain."""
    domain = base_domain()
    if not hostname:
        return ""
    if domain and hostname.endswith(f".{domain}"):
        return hostname[: -len(domain) - 1]
    return hostname
