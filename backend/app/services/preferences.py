"""The settings an administrator can change without a restart.

Everything this platform does is configured in `.env`, which is the right
place for it: a deployment's secrets, its database, the addresses it answers
on. But a handful of those settings are not deployment facts at all - how
large an upload may be, how often fieldwork is looked at, how long an answer
stays cached - and changing one of those meant editing a file on the server
and restarting five containers, which an office that runs the platform but
does not run the server cannot do.

So those few are stored, and read through here. What is stored wins; what is
not falls back to `.env`, which goes on being the defaults. Nothing here can
reach the settings that would lock somebody out or lose data - the secret
key, the encryption key, the database - because a web page is not where those
belong.

Every process holds what it read for a few seconds before asking again, which
is what makes this cheap: the API alone reads the upload limit on every
request. The cost is that a change takes a moment to reach the workers, and
the page says so rather than pretending otherwise.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import SystemSetting

logger = get_logger(__name__)

#: How long a process keeps what it read. Long enough that the upload limit is
#: not a database query per request; short enough that an administrator who
#: changes something sees it take hold while they are still looking at it.
CACHE_SECONDS = 20


@dataclass(frozen=True)
class Knob:
    """One setting, and everything the page needs to show it properly."""

    name: str
    group: str
    label: str
    about: str
    kind: str = "int"  # int | bool | text | secret
    minimum: int | None = None
    maximum: int | None = None
    unit: str = ""
    #: Said on the page where a value has consequences somebody should weigh
    #: before typing it, rather than discovered afterwards.
    warning: str = ""


FILES = "Files and uploads"
REFRESH = "How often things run"
ANALYTICS = "Analytics and caching"
EMAIL = "Email"
ACCESS = "Access and disclosure"

KNOBS: tuple[Knob, ...] = (
    Knob(
        name="max_upload_mb",
        group=FILES,
        label="Largest upload",
        unit="MB",
        minimum=1,
        maximum=1024 * 1024,
        about=(
            "The biggest file this platform will accept. A census export of a "
            "whole country in Stata form runs to several gigabytes, and the "
            "point of a limit this large is that such a file goes in without "
            "being split by hand."
        ),
        warning=(
            "An upload costs disk twice over while it is in flight: once in the "
            "temporary file it is spooled to, once where it lands."
        ),
    ),
    Knob(
        name="max_extracted_gb",
        group=FILES,
        label="Most an archive may expand to",
        unit="GB",
        minimum=1,
        maximum=4096,
        about=(
            "A zip only caps what was uploaded, not what comes out of it: "
            "survey data compresses ten to one and a deliberately built archive "
            "can hold effectively unbounded amounts. This is the ceiling on "
            "what one is allowed to become on disk."
        ),
    ),
    Knob(
        name="sync_tick_minutes",
        group=REFRESH,
        label="Look for due imports every",
        unit="minutes",
        minimum=1,
        maximum=1440,
        about=(
            "How often the scheduler asks which Survey Solutions connections "
            "are due. Each connection has its own schedule; this is how often "
            "they are read, so it sets how late an import can be."
        ),
    ),
    Knob(
        name="monitor_tick_minutes",
        group=REFRESH,
        label="Recompute indicators every",
        unit="minutes",
        minimum=1,
        maximum=1440,
        about=(
            "How often every indicator is recomputed, its trend given a point, "
            "and the alert rules evaluated. An import already refreshes the "
            "indicators that read what it changed, so this is for the figures "
            "that move on their own - and it is the only thing that writes the "
            "trends, so a long interval is a coarse trend."
        ),
    ),
    Knob(
        name="analytics_cache_enabled",
        group=ANALYTICS,
        kind="bool",
        label="Keep answers in Redis",
        about=(
            "A chart asked the same question twice is answered from memory the "
            "second time. The dataset's version is part of every key, so an "
            "import moves every query onto fresh entries by itself - there is "
            "nothing to clear."
        ),
    ),
    Knob(
        name="analytics_cache_ttl_seconds",
        group=ANALYTICS,
        label="Keep each answer for",
        unit="seconds",
        minimum=1,
        maximum=60 * 60 * 24 * 7,
        about=(
            "How long a cached answer lives. It can be hours rather than "
            "minutes without going stale, because an import invalidates by "
            "version rather than by age - the limit is what Redis can hold."
        ),
    ),
    Knob(
        name="duckdb_csv_above_mb",
        group=ANALYTICS,
        label="Read delimited files through DuckDB above",
        unit="MB",
        minimum=1,
        maximum=1024 * 64,
        about=(
            "A .csv or .tab larger than this is parsed straight into Parquet by "
            "DuckDB rather than through pandas, which is several times faster "
            "and holds far less of it in memory at once."
        ),
    ),
    Knob(
        name="monitoring_precompute_enabled",
        group=ANALYTICS,
        kind="bool",
        label="Summarise fieldwork after each import",
        about=(
            "Builds a small summary of a dataset's monitoring fields when it is "
            "imported, so the fieldwork page does not scan the whole interview "
            "file every time somebody opens it."
        ),
    ),
    Knob(
        name="smtp_host",
        group=EMAIL,
        kind="text",
        label="Server",
        about="The mail server alerts and invitations are sent through. Empty turns email off.",
    ),
    Knob(
        name="smtp_port",
        group=EMAIL,
        label="Port",
        minimum=1,
        maximum=65535,
        about="587 for STARTTLS, which is the usual choice; 465 and 25 also occur.",
    ),
    Knob(
        name="smtp_user",
        group=EMAIL,
        kind="text",
        label="Username",
        about="Left empty for a server on the same network that needs no sign-in.",
    ),
    Knob(
        name="smtp_password",
        group=EMAIL,
        kind="secret",
        label="Password",
        about=(
            "Stored encrypted, the same way a Survey Solutions password is, and "
            "never sent back to this page."
        ),
    ),
    Knob(
        name="smtp_tls",
        group=EMAIL,
        kind="bool",
        label="Use STARTTLS",
        about=(
            "On for port 587. A server that wants no encryption at all is "
            "rare and worth asking about."
        ),
    ),
    Knob(
        name="smtp_from",
        group=EMAIL,
        kind="text",
        label="From address",
        about='What a recipient sees it came from, as "Name <address>".',
    ),
    Knob(
        name="signup_enabled",
        group=ACCESS,
        kind="bool",
        label="Let people create their own accounts",
        about=(
            "Anyone who can reach the sign-in page may make an account, as a "
            "viewer."
        ),
        warning=(
            "Only for a sign-in page the public cannot reach. A self-service "
            "account is a foothold inside the platform, and the surveys on this "
            "server are what is behind it."
        ),
    ),
    Knob(
        name="rate_limit_enabled",
        group=ACCESS,
        kind="bool",
        label="Limit repeated sign-in attempts",
        about=(
            "Ten attempts a minute from one address and five against one "
            "account, right or wrong. Turn it off only behind a proxy that "
            "collapses every visitor onto one address."
        ),
    ),
    Knob(
        name="disclosure_threshold",
        group=ACCESS,
        label="Withhold any cell below",
        unit="people",
        minimum=0,
        maximum=1000,
        about=(
            "A published table whose cell rests on two households can identify "
            "them. Below this count a cell is withheld and says so. Zero is off; "
            "5 is the common floor, 3 and 10 both occur."
        ),
        warning=(
            "This is a rule of the office rather than a preference. Every change "
            "to it is recorded with who made it."
        ),
    ),
)

BY_NAME: dict[str, Knob] = {knob.name: knob for knob in KNOBS}

#: Settings held here but never sent back out. A password that a page can read
#: is a password on everybody's screen.
SECRET_KINDS = {"secret"}

#: Kept encrypted at rest, like a connection's password.
ENCRYPTED = {"smtp_password"}


def default(name: str) -> Any:
    """What `.env` says, which is what applies until somebody stores something."""
    return getattr(settings, name)


_held: dict[str, Any] = {}
_read_at: float = 0.0


def _stored() -> dict[str, Any]:
    """Everything an administrator has set, from this process's brief memory."""
    global _read_at
    if _held and time.monotonic() - _read_at < CACHE_SECONDS:
        return _held
    try:
        from app.db.session import session_scope

        with session_scope() as db:
            rows = db.scalars(select(SystemSetting)).all()
            fresh = {
                row.key: (row.value or {}).get("value")
                for row in rows
                if row.key in BY_NAME
            }
    except Exception as exc:  # noqa: BLE001 - no database, no overrides
        # Every caller has a default to fall back on, and a platform that
        # would not start because a settings table was unreadable would be a
        # worse platform than one that runs on what .env says.
        logger.debug("Could not read the stored settings: %s", exc)
        return _held
    _held.clear()
    _held.update(fresh)
    _read_at = time.monotonic()
    return _held


def forget() -> None:
    """Drop what this process is holding, so the next read goes to the database.

    Called after a change so the administrator who made it sees it at once,
    rather than within the ordinary few seconds like everybody else.
    """
    global _read_at
    _held.clear()
    _read_at = 0.0


def value(name: str) -> Any:
    """What this setting is now: what was stored, or what `.env` says."""
    if name not in BY_NAME:
        raise KeyError(f"{name} is not a setting that can be changed here")
    stored = _stored().get(name)
    if stored is None:
        return default(name)
    if name in ENCRYPTED:
        from app.core.crypto import decrypt

        try:
            return decrypt(str(stored))
        except Exception:  # noqa: BLE001 - a key changed under a stored secret
            logger.warning("The stored %s could not be decrypted; using .env", name)
            return default(name)
    return stored


class NotAllowed(Exception):
    """A value this setting will not take, said so the page can show why."""


def _checked(knob: Knob, given: Any) -> Any:
    """`given` as this setting's own type, or a refusal saying what was wrong."""
    if knob.kind == "bool":
        if isinstance(given, bool):
            return given
        if isinstance(given, str) and given.lower() in {"true", "false"}:
            return given.lower() == "true"
        raise NotAllowed(f"{knob.label} is on or off.")

    if knob.kind in {"text", "secret"}:
        text = "" if given is None else str(given)
        if len(text) > 500:
            raise NotAllowed(f"{knob.label} is longer than this platform will store.")
        return text

    try:
        number = int(given)
    except (TypeError, ValueError) as exc:
        raise NotAllowed(f"{knob.label} has to be a whole number.") from exc
    if knob.minimum is not None and number < knob.minimum:
        raise NotAllowed(
            f"{knob.label} cannot be below {knob.minimum}{' ' + knob.unit if knob.unit else ''}."
        )
    if knob.maximum is not None and number > knob.maximum:
        raise NotAllowed(
            f"{knob.label} cannot be above {knob.maximum}{' ' + knob.unit if knob.unit else ''}."
        )
    return number


def put(db: Session, name: str, given: Any) -> Any:
    """Store one setting. Returns what was stored, for the audit entry.

    A secret is stored encrypted and reported as the word "set", because what
    goes in the audit log is read by everybody who can read the audit log.
    """
    knob = BY_NAME.get(name)
    if knob is None:
        raise NotAllowed(f"{name} is not a setting that can be changed here.")
    checked = _checked(knob, given)

    kept: Any = checked
    if name in ENCRYPTED:
        from app.core.crypto import encrypt

        try:
            kept = encrypt(str(checked)) if checked else ""
        except RuntimeError as exc:
            # No key, or one that is not a key: said on the page, where the
            # administrator is, rather than as a server error with the real
            # reason in a log they would have to go and find.
            raise NotAllowed(str(exc)) from exc

    row = db.get(SystemSetting, name)
    if row is None:
        db.add(SystemSetting(key=name, value={"value": kept}))
    else:
        row.value = {"value": kept}
    db.flush()
    forget()
    return "set" if name in ENCRYPTED else checked


def clear(db: Session, name: str) -> None:
    """Put a setting back to what `.env` says."""
    if name not in BY_NAME:
        raise NotAllowed(f"{name} is not a setting that can be changed here.")
    row = db.get(SystemSetting, name)
    if row is not None:
        db.delete(row)
        db.flush()
    forget()


def catalogue() -> list[dict[str, Any]]:
    """Every setting, what it is now, and whether that came from here or .env.

    A secret says whether it is set rather than what it is.
    """
    stored = _stored()
    listed: list[dict[str, Any]] = []
    for knob in KNOBS:
        overridden = stored.get(knob.name) is not None
        entry: dict[str, Any] = {
            "name": knob.name,
            "group": knob.group,
            "label": knob.label,
            "about": knob.about,
            "warning": knob.warning,
            "kind": knob.kind,
            "unit": knob.unit,
            "minimum": knob.minimum,
            "maximum": knob.maximum,
            "overridden": overridden,
        }
        if knob.kind in SECRET_KINDS:
            entry["value"] = bool(value(knob.name))
            entry["default"] = bool(default(knob.name))
        else:
            entry["value"] = value(knob.name)
            entry["default"] = default(knob.name)
        listed.append(entry)
    return listed


def upload_label() -> str:
    """The upload ceiling as a person would say it.

    Every message that names the limit says it through here, and reads the
    limit the same way everything else does. It lived on the settings object
    until an administrator lowered the limit from this platform and was told
    the file exceeded a ceiling that was no longer in force - a property on
    the configuration is a read the store cannot reach.

    Spelled in megabytes it was fine at 512 and absurd at 20480, and an error
    quoting an absurd number reads as a bug in the platform rather than as a
    file that is too big.
    """
    megabytes = int(value("max_upload_mb"))
    if megabytes >= 1024 and megabytes % 1024 == 0:
        return f"{megabytes // 1024} GB"
    if megabytes >= 1024:
        return f"{megabytes / 1024:.1f} GB"
    return f"{megabytes} MB"


def mail_enabled() -> bool:
    """Whether there is a server to send through.

    Here rather than on the configuration for the same reason the upload
    label is: the mail server is one of the settings an administrator can
    fill in from the platform, and a deployment that had none in `.env` would
    otherwise go on believing it had none.
    """
    return bool(value("smtp_host"))
