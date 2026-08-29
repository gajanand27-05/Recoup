import pytest

from recoup.ledger.store import GENESIS, Ledger, canonical_json


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
