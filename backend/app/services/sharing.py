"""When a published link is open, and when it has run out.

A dashboard's link outlives the reason it was made. The donor's copy was for
the report that has since been filed; the workshop's was for the workshop. Both
stay open until somebody remembers to close them, and nobody does - so the
useful thing to be able to say when the link is made is when it ends.

Expiry is checked when a reader arrives rather than swept up by a job. A link
that ran out overnight has to be shut to the first person who opens it in the
morning, and a nightly sweep would leave it open until the sweep ran.
"""

from __future__ import annotations

import datetime as dt

from app.db.base import utcnow
from app.models import ShareLink


def as_utc(moment: dt.datetime | None) -> dt.datetime | None:
    """A moment in UTC, whatever zone it arrived in.

    A date chosen in a browser in Port Vila arrives with an offset on it, and
    SQLite hands back what it stored without one. Comparing the two raises
    rather than answering, so both ends of the comparison are made aware and
    put in UTC here: a naive value is read as UTC, which is what this platform
    stores everywhere else.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC)


def link_expired(link: ShareLink, now: dt.datetime | None = None) -> bool:
    """Whether this link's date has passed. A link with no date never expires."""
    ends = as_utc(link.expires_at)
    if ends is None:
        return False
    return (now or utcnow()) >= ends


def link_is_open(link: ShareLink, now: dt.datetime | None = None) -> bool:
    """Whether a reader arriving now should be let in.

    Closed by hand and run out are one answer to the reader and two different
    things to the person who made the link, which is why they are kept apart
    in what the API reports and joined only here.
    """
    return bool(link.is_active) and not link_expired(link, now)
