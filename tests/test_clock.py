"""Timestamp format pins.

Same reasoning as test_the_hash_of_a_known_row_never_changes in test_ledger.py.
`ts` is one of the fields folded into the ledger hash, so the exact output string
of this module is an input to the chain rule, not a formatting preference. Two
runs that spelled the same instant differently would produce different hashes for
the same event.

If these fail, do not update the constants to match. Work out what changed and
whether every ledger written before it still verifies.
"""

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from recoup.clock import to_iso_z, utc_now_iso

IST = timezone(timedelta(hours=5, minutes=30))


def test_the_output_string_of_a_known_instant_never_changes():
    dt = datetime(2026, 8, 29, 21, 16, 3, 123456, tzinfo=UTC)
    assert to_iso_z(dt) == "2026-08-29T21:16:03.123456Z"


def test_a_whole_second_keeps_its_shape():
    # No microseconds means isoformat() omits the fractional part entirely.
    # Pinned because it is a different string for a perfectly ordinary instant.
    dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert to_iso_z(dt) == "2026-01-01T00:00:00Z"


def test_a_non_utc_instant_is_converted_not_relabelled():
    # 02:46:03.123456 IST is 21:16:03.123456 UTC the previous day. Stamping the
    # local wall clock with a Z would be off by five and a half hours and look
    # completely normal.
    ist = datetime(2026, 8, 30, 2, 46, 3, 123456, tzinfo=IST)
    assert to_iso_z(ist) == "2026-08-29T21:16:03.123456Z"


def test_the_offset_form_never_appears():
    # datetime.isoformat() emits +00:00. That is valid ISO-8601, means the same
    # instant, and is a DIFFERENT STRING, which is the whole problem.
    out = to_iso_z(datetime(2026, 8, 29, 21, 16, 3, tzinfo=UTC))
    assert "+00:00" not in out
    assert out.endswith("Z")


def test_a_naive_datetime_is_refused_rather_than_assumed_utc():
    with pytest.raises(ValueError, match="naive"):
        to_iso_z(datetime(2026, 8, 29, 21, 16, 3))


def test_utc_now_iso_matches_the_pinned_shape():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?Z", utc_now_iso())


def test_utc_now_iso_is_actually_utc():
    before = datetime.now(UTC)
    parsed = datetime.fromisoformat(utc_now_iso().replace("Z", "+00:00"))
    after = datetime.now(UTC)
    assert before <= parsed <= after
