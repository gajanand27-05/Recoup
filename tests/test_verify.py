import json

import pytest

from recoup.cli import EXIT_CHAIN_INVALID, EXIT_HEAD_MISMATCH, EXIT_OK, main
from recoup.ledger.store import GENESIS, Ledger
from recoup.ledger.verify import check_anchor, read_anchor, verify_chain


@pytest.fixture
def ledger(tmp_path):
    lg = Ledger(str(tmp_path / "v.db"))
    for i in range(5):
        lg.append({
            "run_id": "run-1",
            "ts": f"2026-08-29T10:0{i}:00Z",
            "event_type": "action.executed",
            "subscription_id": f"sub_{i}",
            "customer_id": f"cust_{i}",
            "arm": "control",
            "transport": "sim",
            "payload": {"n": i},
        })
    return lg


# --- internal consistency ----------------------------------------------------


def test_an_untouched_chain_verifies(ledger):
    result = verify_chain(ledger)
    assert result.ok is True
    assert result.rows_checked == 5
    assert result.head_hash == ledger.head_hash()
    assert result.first_bad_seq is None


def test_an_empty_ledger_verifies_at_genesis(tmp_path):
    result = verify_chain(Ledger(str(tmp_path / "empty.db")))
    assert result.ok is True
    assert result.rows_checked == 0
    assert result.head_hash == GENESIS


def test_a_tampered_payload_is_caught(ledger):
    # Bypass the triggers the way an attacker with file access would.
    ledger.conn.execute("DROP TRIGGER ledger_no_update")
    ledger.conn.execute("UPDATE ledger SET payload = '{\"n\":999}' WHERE seq = 3")
    ledger.conn.commit()

    result = verify_chain(ledger)
    assert result.ok is False
    assert result.first_bad_seq == 3
    assert "hash mismatch" in result.reason


def test_a_broken_link_is_caught(ledger):
    ledger.conn.execute("DROP TRIGGER ledger_no_update")
    ledger.conn.execute("UPDATE ledger SET prev_hash = ? WHERE seq = 4", ("f" * 64,))
    ledger.conn.commit()

    result = verify_chain(ledger)
    assert result.ok is False
    assert result.first_bad_seq == 4


def test_a_deleted_row_is_caught(ledger):
    ledger.conn.execute("DROP TRIGGER ledger_no_delete")
    ledger.conn.execute("DELETE FROM ledger WHERE seq = 2")
    ledger.conn.commit()

    result = verify_chain(ledger)
    assert result.ok is False


# --- the gap the chain cannot close ------------------------------------------
# A hash chain detects mutation and mid-chain deletion. It cannot detect deletion
# of the TAIL: the remaining prefix is still perfectly self-consistent and nothing
# inside the file records that the removed rows ever existed. Only an external
# anchor -- a head hash committed before those rows were written -- proves
# completeness. This test asserts the limitation so it stays honest.


def test_tail_truncation_is_invisible_to_the_chain(ledger):
    """PINS A KNOWN LIMITATION. This is not asserting desired behaviour.

    `ok is True` on a truncated ledger is the gap, not the goal. The assertion
    exists so the limitation cannot quietly stop being true.

    If this test goes RED, do not adjust the assertion. It means the chain's
    detection properties changed, and three things need revisiting together:
      1. the module docstring in ledger/verify.py
      2. the limitations section of README.md
      3. whether `--expect-head` is still the thing that closes the gap

    What closes it today is the external anchor: see
    test_the_anchor_catches_tail_truncation directly below, which is the same
    scenario with a committed head to compare against.
    """
    full_head = ledger.head_hash()
    ledger.conn.execute("DROP TRIGGER ledger_no_delete")
    ledger.conn.execute("DELETE FROM ledger WHERE seq > 3")
    ledger.conn.commit()

    result = verify_chain(ledger)
    assert result.ok is True, "a truncated prefix is still internally consistent"
    assert result.rows_checked == 3
    assert result.head_hash != full_head


# --- external anchor: completeness -------------------------------------------


def test_the_anchor_accepts_a_matching_head(ledger):
    result = verify_chain(ledger)
    anchor = check_anchor(result, expected_head=ledger.head_hash(), expected_rows=5)
    assert anchor.ok is True
    assert anchor.reason is None


def test_the_anchor_catches_tail_truncation(ledger):
    committed_head = ledger.head_hash()
    ledger.conn.execute("DROP TRIGGER ledger_no_delete")
    ledger.conn.execute("DELETE FROM ledger WHERE seq > 3")
    ledger.conn.commit()

    result = verify_chain(ledger)
    anchor = check_anchor(result, expected_head=committed_head, expected_rows=5)
    assert result.ok is True
    assert anchor.ok is False
    assert "head" in anchor.reason.lower()
    assert anchor.actual_head == result.head_hash
    assert anchor.expected_head == committed_head


def test_the_anchor_reports_the_row_count_gap(ledger):
    committed_head = ledger.head_hash()
    ledger.conn.execute("DROP TRIGGER ledger_no_delete")
    ledger.conn.execute("DELETE FROM ledger WHERE seq > 3")
    ledger.conn.commit()

    anchor = check_anchor(verify_chain(ledger), expected_head=committed_head, expected_rows=5)
    assert anchor.expected_rows == 5
    assert anchor.actual_rows == 3
    assert "2" in anchor.reason  # names how many rows went missing


def test_the_anchor_ignores_row_count_when_not_supplied(ledger):
    anchor = check_anchor(verify_chain(ledger), expected_head=ledger.head_hash())
    assert anchor.ok is True


def test_a_row_count_mismatch_alone_still_fails(ledger):
    # Head matches but the recorded count does not. The anchor file disagrees with
    # itself, which is a finding regardless of which side is wrong.
    anchor = check_anchor(verify_chain(ledger), expected_head=ledger.head_hash(), expected_rows=9)
    assert anchor.ok is False


def test_read_anchor_parses_a_run_file(tmp_path):
    p = tmp_path / "run-1.head"
    p.write_text(json.dumps({"run_id": "run-1", "head_hash": "a" * 64, "rows_checked": 5}))
    anchor = read_anchor(str(p))
    assert anchor["head_hash"] == "a" * 64
    assert anchor["rows_checked"] == 5


def test_read_anchor_rejects_a_file_without_a_head_hash(tmp_path):
    p = tmp_path / "bad.head"
    p.write_text(json.dumps({"run_id": "run-1"}))
    with pytest.raises(ValueError, match="head_hash"):
        read_anchor(str(p))


# --- CLI ---------------------------------------------------------------------
# Exit codes are load-bearing: 1 and 3 are different findings with different
# responses. 2 is skipped because argparse spends it on usage errors, and a typo
# must not look like a head mismatch.


def test_cli_exits_0_and_prints_head_on_a_good_chain(ledger, capsys):
    code = main(["--db", ledger.db_path, "verify-ledger"])
    out = capsys.readouterr().out
    assert code == EXIT_OK == 0
    assert "OK" in out
    assert ledger.head_hash() in out


def test_cli_exits_1_when_the_chain_is_invalid(ledger, capsys):
    ledger.conn.execute("DROP TRIGGER ledger_no_update")
    ledger.conn.execute("UPDATE ledger SET payload = '{\"n\":999}' WHERE seq = 3")
    ledger.conn.commit()

    code = main(["--db", ledger.db_path, "verify-ledger"])
    assert code == EXIT_CHAIN_INVALID == 1


def test_cli_does_not_print_a_head_it_cannot_vouch_for(ledger, capsys):
    ledger.conn.execute("DROP TRIGGER ledger_no_update")
    ledger.conn.execute("UPDATE ledger SET payload = '{\"n\":999}' WHERE seq = 3")
    ledger.conn.commit()

    main(["--db", ledger.db_path, "verify-ledger"])
    captured = capsys.readouterr()
    assert "HEAD" not in captured.out + captured.err, (
        "a failed verify has no head it can vouch for"
    )


def test_cli_exits_3_when_the_head_does_not_match_the_anchor(ledger, capsys):
    committed_head = ledger.head_hash()
    ledger.conn.execute("DROP TRIGGER ledger_no_delete")
    ledger.conn.execute("DELETE FROM ledger WHERE seq > 3")
    ledger.conn.commit()

    code = main(["--db", ledger.db_path, "verify-ledger", "--expect-head", committed_head])
    err = capsys.readouterr().err
    assert code == EXIT_HEAD_MISMATCH == 3
    assert committed_head in err


def test_cli_exits_0_when_the_head_matches_the_anchor(ledger):
    code = main(["--db", ledger.db_path, "verify-ledger", "--expect-head", ledger.head_hash()])
    assert code == EXIT_OK


def test_cli_reads_an_anchor_from_a_file(ledger, tmp_path):
    p = tmp_path / "run-1.head"
    p.write_text(json.dumps({
        "run_id": "run-1",
        "head_hash": ledger.head_hash(),
        "rows_checked": 5,
    }))
    assert main(["--db", ledger.db_path, "verify-ledger", "--expect-head-file", str(p)]) == EXIT_OK


def test_a_broken_chain_outranks_a_head_mismatch(ledger):
    # Both wrong at once must report the more severe finding, not the later check.
    ledger.conn.execute("DROP TRIGGER ledger_no_update")
    ledger.conn.execute("UPDATE ledger SET payload = '{\"n\":999}' WHERE seq = 3")
    ledger.conn.commit()

    code = main(["--db", ledger.db_path, "verify-ledger", "--expect-head", "b" * 64])
    assert code == EXIT_CHAIN_INVALID


def test_the_ledger_creates_its_parent_directory(tmp_path):
    # `--db runs/recoup.db` must work without a preceding mkdir.
    lg = Ledger(str(tmp_path / "nested" / "deeper" / "recoup.db"))
    assert lg.head_hash() == GENESIS
