"""Recompute the ledger hash chain, and check it against an external anchor.

These are two different questions and the distinction matters:

  verify_chain()  -- is this chain internally consistent?
                     Catches mutation of any field and deletion from the middle.
  check_anchor()  -- is this the chain we committed to?
                     Catches tail truncation, which the chain provably cannot.

A hash chain has no way to know that rows were removed from its end. Delete the
last two rows and what remains is a perfectly valid chain with a shorter length
and a different head; nothing inside the file records that those rows ever
existed. The only thing that closes that gap is a head hash recorded somewhere
the ledger cannot reach, *before* the rows it covers were written -- committed to
git, so the ordering is witnessed rather than asserted.

Verification proves consistency. The anchor proves completeness.
"""

import json
from dataclasses import dataclass

from recoup.ledger.store import GENESIS, Ledger, compute_hash


@dataclass
class VerifyResult:
    ok: bool
    rows_checked: int
    head_hash: str
    first_bad_seq: int | None = None
    reason: str | None = None


@dataclass
class AnchorResult:
    ok: bool
    expected_head: str
    actual_head: str
    actual_rows: int
    expected_rows: int | None = None
    reason: str | None = None


def verify_chain(ledger: Ledger) -> VerifyResult:
    """Recompute every hash from genesis.

    On failure `head_hash` holds the last hash that *did* verify, not the stored
    head. Callers must not present it as the ledger's head: a chain that failed
    verification has no head it can vouch for.
    """
    prev = GENESIS
    checked = 0

    for row in ledger.rows():
        seq = row["seq"]

        if row["prev_hash"] != prev:
            return VerifyResult(
                ok=False,
                rows_checked=checked,
                head_hash=prev,
                first_bad_seq=seq,
                reason=f"broken link at seq {seq}: prev_hash does not match previous row's hash",
            )

        expected = compute_hash(prev, row)
        if expected != row["hash"]:
            return VerifyResult(
                ok=False,
                rows_checked=checked,
                head_hash=prev,
                first_bad_seq=seq,
                reason=f"hash mismatch at seq {seq}: row contents do not match stored hash",
            )

        prev = row["hash"]
        checked += 1

    return VerifyResult(ok=True, rows_checked=checked, head_hash=prev)


def check_anchor(
    result: VerifyResult,
    expected_head: str,
    expected_rows: int | None = None,
) -> AnchorResult:
    """Compare a verified chain against the head recorded when the run finished.

    `expected_rows` is cryptographically redundant -- if the head matches, the
    length does too. It is carried because it is the field a human can eyeball
    against the report, and because a mismatch names how many rows went missing
    instead of only that something did.
    """
    head_ok = result.head_hash == expected_head
    rows_ok = expected_rows is None or result.rows_checked == expected_rows

    reason = None
    if not head_ok:
        reason = (
            f"head does not match the anchor: expected {expected_head}, "
            f"found {result.head_hash}"
        )
        if expected_rows is not None and expected_rows != result.rows_checked:
            missing = expected_rows - result.rows_checked
            reason += (
                f" ({missing} rows missing from the end)"
                if missing > 0
                else f" ({-missing} rows appended since the anchor)"
            )
    elif not rows_ok:
        reason = (
            f"head matches but the anchor records {expected_rows} rows and the "
            f"ledger holds {result.rows_checked}; the anchor file disagrees with itself"
        )

    return AnchorResult(
        ok=head_ok and rows_ok,
        expected_head=expected_head,
        actual_head=result.head_hash,
        actual_rows=result.rows_checked,
        expected_rows=expected_rows,
        reason=reason,
    )


def read_anchor(path: str) -> dict:
    """Read a `runs/<run_id>.head` anchor file.

    Written by the batch runner (Task 22) at the end of a run and committed, so
    that git witnesses the head existing before anything could truncate it.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not data.get("head_hash"):
        raise ValueError(f"anchor file {path} has no head_hash")
    return data
