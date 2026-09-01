"""Post signed webhooks at the local demo server, then show the ledger.

    python scripts/send_demo_event.py

Sends three things, in this order, because each one shows a different guard:

  1. a valid `subscription.halted`            -> 202, and a ledger row appears
  2. the SAME event id again                  -> 202, and NO second row
  3. the same body with a broken signature    -> 400, nothing written

2 is the dedupe rule: Razorpay delivers at-least-once and unordered, so a
redelivery must be a no-op rather than a second recovery attempt. 3 is why an
attacker cannot post their own `halted` event and drive outreach.
"""

import hashlib
import hmac
import json
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))  # so `scripts.` resolves when run as a file

from recoup.ledger import Ledger  # noqa: E402
from scripts.run_local_demo import DEMO_DB, DEMO_SECRET  # noqa: E402

URL = "http://localhost:8000/webhook"

HALTED = {
    "entity": "event",
    "event": "subscription.halted",
    "contains": ["subscription"],
    "payload": {"subscription": {"entity": {"id": "sub_demo_001", "status": "halted"}}},
    "created_at": 1756400000,
}


def post(body: dict, event_id: str, *, secret: str = DEMO_SECRET) -> httpx.Response:
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return httpx.post(
        URL,
        content=raw,
        headers={
            "X-Razorpay-Signature": sig,
            "x-razorpay-event-id": event_id,
            "Content-Type": "application/json",
        },
        timeout=10.0,
    )


def rows() -> int:
    ledger = Ledger(str(DEMO_DB), check_same_thread=False)
    try:
        return ledger.conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    finally:
        ledger.conn.close()


def step(n: int, title: str, note: str) -> None:
    print(f"\n{'-' * 70}\n  {n}. {title}\n     {note}\n{'-' * 70}")


def main() -> int:
    try:
        httpx.get("http://localhost:8000/health", timeout=3.0).raise_for_status()
    except Exception:
        print("The server is not up. Run this first, in another terminal:")
        print("    python scripts/run_local_demo.py")
        return 1

    step(1, "A valid subscription.halted", "ACK must be 2xx and fast; work happens after.")
    r = post(HALTED, "evt_demo_001")
    print(f"     HTTP {r.status_code}  {r.json()}")

    step(2, "The SAME event id, redelivered", "At-least-once delivery. This must NOT write twice.")
    r = post(HALTED, "evt_demo_001")
    print(f"     HTTP {r.status_code}  {r.json()}")

    step(3, "A forged signature", "Anyone can reach this port. Not everyone can sign.")
    r = post(HALTED, "evt_demo_002", secret="attacker-guessing")
    print(f"     HTTP {r.status_code}  {r.text.strip()[:120]}")

    print(f"\n{'=' * 70}")
    print(f"  ledger rows written: {rows()}   (2 accepted posts, 1 deduped, 1 rejected)")
    print(f"{'=' * 70}")
    print("\n  Verify the chain, and note transport=sim on every row:")
    print(f'    python -m recoup.cli --db "{DEMO_DB}" verify-ledger')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
