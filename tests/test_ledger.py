import sqlite3

import pytest

from recoup.ledger.store import (
    _HASHED_FIELDS,
    GENESIS,
    Ledger,
    canonical_json,
    compute_hash,
)


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "test.db"))


def _row(**kw):
    base = {
        "run_id": "run-1",
        "ts": "2026-08-29T10:00:00Z",
        "event_type": "subscription.halted",
        "subscription_id": "sub_001",
        "customer_id": "cust_001",
        "arm": "control",
        "transport": "sim",
        "payload": {"amount_paise": 49900},
    }
    base.update(kw)
    return base


def test_canonical_json_is_stable_across_key_order():
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})
    assert canonical_json({"a": 1, "b": 2}) == '{"a":1,"b":2}'


def test_first_row_chains_from_genesis(ledger):
    h = ledger.append(_row())
    rows = ledger.rows()
    assert len(rows) == 1
    assert rows[0]["prev_hash"] == GENESIS
    assert rows[0]["hash"] == h
    assert len(h) == 64


def test_each_row_chains_to_the_previous(ledger):
    h1 = ledger.append(_row(subscription_id="sub_001"))
    h2 = ledger.append(_row(subscription_id="sub_002"))
    rows = ledger.rows()
    assert rows[1]["prev_hash"] == h1
    assert rows[1]["hash"] == h2
    assert h1 != h2


def test_head_hash_is_the_last_row(ledger):
    assert ledger.head_hash() == GENESIS
    ledger.append(_row())
    h2 = ledger.append(_row(subscription_id="sub_002"))
    assert ledger.head_hash() == h2


def test_identical_payloads_still_produce_different_hashes(ledger):
    # Because prev_hash is folded in, position is part of the identity.
    h1 = ledger.append(_row())
    h2 = ledger.append(_row())
    assert h1 != h2


def test_updates_are_rejected_by_the_database(ledger):
    ledger.append(_row())
    with pytest.raises(Exception, match="append-only"):
        ledger.conn.execute("UPDATE ledger SET arm = 'treatment' WHERE seq = 1")
        ledger.conn.commit()


def test_deletes_are_rejected_by_the_database(ledger):
    ledger.append(_row())
    with pytest.raises(Exception, match="append-only"):
        ledger.conn.execute("DELETE FROM ledger WHERE seq = 1")
        ledger.conn.commit()


def test_rows_can_be_filtered_by_run(ledger):
    ledger.append(_row(run_id="run-a"))
    ledger.append(_row(run_id="run-b"))
    assert len(ledger.rows(run_id="run-a")) == 1
    assert len(ledger.rows()) == 2


# --- append/verify agreement -------------------------------------------------
# `append()` is handed a caller-shaped dict; `verify_chain()` re-hashes rows read
# back out of `rows()`, which carry extra columns (seq, hash, prev_hash) and a
# payload that has been through JSON. These two shapes must project to identical
# hash material or the ledger accuses itself of tampering.


def test_a_row_read_back_rehashes_to_the_same_value(ledger):
    ledger.append(_row())
    stored = ledger.rows()[0]
    assert compute_hash(stored["prev_hash"], stored) == stored["hash"]


def test_a_row_without_a_payload_still_rehashes(ledger):
    # append() stores a missing payload as {} but must also HASH it as {}.
    ledger.append({"run_id": "r", "ts": "2026-08-29T10:00:00Z",
                   "event_type": "e", "transport": "sim"})
    stored = ledger.rows()[0]
    assert stored["payload"] == {}
    assert compute_hash(stored["prev_hash"], stored) == stored["hash"]


def test_optional_fields_absent_and_explicitly_none_are_the_same_row(ledger):
    absent = {"run_id": "r", "ts": "2026-08-29T10:00:00Z",
              "event_type": "e", "transport": "sim"}
    explicit = dict(absent, subscription_id=None, customer_id=None, arm=None, payload={})
    assert compute_hash(GENESIS, absent) == compute_hash(GENESIS, explicit)


# --- the one-way door --------------------------------------------------------
# _HASHED_FIELDS, its order, and canonical_json() are frozen. Changing any of
# them silently produces different-but-internally-valid hashes, so every ledger
# written before the change stops verifying and nothing says why. A comment does
# not fail CI; this does.

GOLDEN_ROW = {
    "run_id": "golden",
    "ts": "2026-01-01T00:00:00Z",
    "event_type": "subscription.halted",
    "subscription_id": "sub_GOLDEN",
    "customer_id": "cust_GOLDEN",
    "arm": "treatment",
    "transport": "sim",
    "payload": {"amount_paise": 49900, "currency": "INR"},
}
GOLDEN_FROM_GENESIS = "ce7379f362902f6c663ce3cee9b58fef644f3abc896c98c4bbe56e628e2ee066"
GOLDEN_FROM_A64 = "b871d28266db009a0c75e5089404e0bc742fcc2b2bf729d2a17b6c155ec13c4a"


def test_the_hash_of_a_known_row_never_changes():
    """If this fails, you changed the chain rule. That invalidates every ledger
    ever written. Do not update the constant to make it pass -- work out which of
    _HASHED_FIELDS, its ordering, or canonical_json() moved, and whether you meant it.
    """
    assert compute_hash(GENESIS, GOLDEN_ROW) == GOLDEN_FROM_GENESIS
    assert compute_hash("a" * 64, GOLDEN_ROW) == GOLDEN_FROM_A64


def test_the_hashed_field_set_is_frozen():
    # Pinned separately so a field added to the tuple names itself in the failure
    # rather than showing up only as an opaque hash mismatch above.
    assert _HASHED_FIELDS == (
        "run_id",
        "ts",
        "event_type",
        "subscription_id",
        "customer_id",
        "arm",
        "transport",
        "payload",
    )


def test_canonical_json_stays_compact_sorted_and_unicode_preserving():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonical_json({"amt": "₹499"}) == '{"amt":"₹499"}'  # not \\u20b9
    assert canonical_json({"a": [1, {"d": 4, "c": 3}]}) == '{"a":[1,{"c":3,"d":4}]}'


def test_a_missing_required_field_is_rejected_by_the_database(ledger):
    # append() projects through _material(), so required fields arrive as NULL
    # rather than raising KeyError. The NOT NULL constraint is what catches it.
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        ledger.append({"ts": "2026-08-29T10:00:00Z", "event_type": "e", "transport": "sim"})


def test_an_unknown_transport_is_rejected_by_the_database(ledger):
    # `real` and `sim` are never pooled in any reported number, so the column is
    # the place that guarantees a third value cannot appear.
    with pytest.raises(sqlite3.IntegrityError):
        ledger.append(_row(transport="mock"))


def test_every_row_shape_rehashes_after_a_round_trip(ledger):
    for row in (
        _row(),
        _row(payload={}),
        _row(payload={"nested": {"b": 2, "a": [1, 2, 3]}}),
        _row(subscription_id=None, customer_id=None, arm=None),
        _row(payload={"note": "₹499 — naïve unicode"}),
        {"run_id": "r", "ts": "2026-08-29T11:00:00Z", "event_type": "e", "transport": "real"},
    ):
        ledger.append(row)
    for stored in ledger.rows():
        assert compute_hash(stored["prev_hash"], stored) == stored["hash"], (
            f"seq {stored['seq']} does not rehash"
        )
