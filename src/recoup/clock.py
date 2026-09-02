"""The single source of timestamps.

Every timestamp in this system is ISO-8601 UTC with a trailing `Z`. Only display
and policy evaluation convert to IST.

`datetime.now(timezone.utc).isoformat()` produces `+00:00`, not `Z`. Both are
valid ISO-8601 and both mean the same instant, but they are different strings --
and ledger rows are hashed over their canonical JSON. A run that emitted one form
and a run that emitted the other would produce different hashes for the same
event, so the format is fixed here rather than at each call site.
"""

from datetime import UTC, datetime


def now_utc() -> datetime:
    """Current time as an aware UTC datetime.

    Here rather than at the call site for the same reason `utc_now_iso()` is: a
    batch that needs to do arithmetic on 'now' (day offsets across a horizon)
    needs a datetime rather than a string, and letting it reach for
    `datetime.now()` itself is how a naive one enters the system. Everything that
    formats goes through `to_iso_z`, which rejects naive input.
    """
    return datetime.now(UTC)


def utc_now_iso() -> str:
    """Current UTC time as `2026-08-29T21:16:03.123456Z`."""
    return to_iso_z(now_utc())


def to_iso_z(dt: datetime) -> str:
    """Format an aware datetime as ISO-8601 UTC with `Z`.

    Naive datetimes are rejected: guessing that one meant UTC is how an IST
    timestamp ends up silently recorded three and a half hours early.
    """
    if dt.tzinfo is None:
        raise ValueError("refusing to format a naive datetime; attach a timezone")
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
