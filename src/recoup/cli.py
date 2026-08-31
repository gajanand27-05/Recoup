"""recoup command line.

Exit codes are part of the interface. `verify-ledger` answers two separate
questions and they get separate codes, because they call for different responses:

    0  chain verifies, and matches the anchor if one was supplied
    1  chain is INVALID -- mutation or a deletion from the middle
    3  chain is valid but its head is NOT the one committed to -- truncation,
       a fork, or an anchor that was never updated

2 is deliberately skipped: argparse spends it on usage errors, and a mistyped
flag must never be mistaken for a head mismatch.
"""

import argparse
import sys

from recoup.ledger.store import Ledger
from recoup.ledger.verify import check_anchor, read_anchor, verify_chain

DEFAULT_DB = "runs/recoup.db"

EXIT_OK = 0
EXIT_CHAIN_INVALID = 1
EXIT_HEAD_MISMATCH = 3


def cmd_verify_ledger(args: argparse.Namespace) -> int:
    result = verify_chain(Ledger(args.db))

    if not result.ok:
        # Deliberately does not print HEAD. `result.head_hash` here is the last
        # hash that verified, not the ledger's head, and labelling it HEAD would
        # imply this ledger has a head worth quoting. It does not.
        print(f"FAIL {result.reason}", file=sys.stderr)
        print(f"     first bad seq:  {result.first_bad_seq}", file=sys.stderr)
        print(f"     rows verified before the break: {result.rows_checked}", file=sys.stderr)
        return EXIT_CHAIN_INVALID

    expected_head = args.expect_head
    expected_rows = None
    if args.expect_head_file:
        anchor = read_anchor(args.expect_head_file)
        expected_head = anchor["head_hash"]
        expected_rows = anchor.get("rows_checked")

    if expected_head is None:
        print(f"OK  rows checked: {result.rows_checked}")
        print(f"HEAD {result.head_hash}")
        print("     (no anchor supplied -- consistency checked, completeness not)")
        return EXIT_OK

    anchored = check_anchor(result, expected_head, expected_rows)
    if not anchored.ok:
        print(f"MISMATCH {anchored.reason}", file=sys.stderr)
        print("         the chain is internally valid; it is not the one anchored", file=sys.stderr)
        return EXIT_HEAD_MISMATCH

    print(f"OK  rows checked: {result.rows_checked}")
    print(f"HEAD {result.head_hash}")
    print("     matches anchor")
    return EXIT_OK


def cmd_captures(args: argparse.Namespace) -> int:
    """Show observed vs committed payload shapes, and promote by name.

    Promotion is deliberately a command someone runs, never something that
    happens automatically. Moving a payload into the evidence directory asserts
    *this is what Razorpay actually sent*, and that assertion should require a
    person — the test suite once made it by accident (INC-006).
    """
    from recoup.execute.capture import (
        CAPTURE_INBOX,
        manifest,
        pending_captures,
        promote_capture,
    )

    if args.promote:
        for event in args.promote:
            try:
                target = promote_capture(event)
            except (FileNotFoundError, ValueError) as exc:
                # A refusal is an answer, not a crash. Print it and exit 1.
                print(f"REFUSED  {exc}", file=sys.stderr)
                return 1
            print(f"promoted {event} -> {target}")
        return 0

    print(f"inbox (observed, not evidence): {CAPTURE_INBOX}")
    pending = pending_captures()
    print(f"awaiting promotion: {', '.join(pending) if pending else 'none'}\n")

    for event, status in manifest().items():
        print(f"  {event:26} {status}")

    if pending:
        print(
            "\nPromote with:\n"
            f"  python -m recoup.cli captures --promote {' '.join(pending)}\n"
            "Check each payload first -- promoting it makes it a claim about "
            "what Razorpay sends."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recoup")
    parser.add_argument("--db", default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    p_verify = sub.add_parser(
        "verify-ledger", help="recompute the hash chain and print the head hash"
    )
    p_verify.add_argument(
        "--expect-head",
        metavar="HASH",
        help="fail with exit 3 unless the head equals HASH (explicit override)",
    )
    p_verify.add_argument(
        "--expect-head-file",
        metavar="PATH",
        help="read the expected head from a committed runs/<run_id>.head anchor file",
    )

    p_cap = sub.add_parser(
        "captures", help="show observed vs committed webhook payload shapes"
    )
    p_cap.add_argument(
        "--promote",
        nargs="+",
        metavar="EVENT",
        help="move an observed payload into committed evidence (a deliberate act)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "verify-ledger":
        return cmd_verify_ledger(args)
    if args.command == "captures":
        return cmd_captures(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
