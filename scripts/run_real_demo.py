"""Branch (b) of D-033, end to end against Razorpay test mode.

    RZP_KEY_ID=rzp_test_... RZP_KEY_SECRET=... python scripts/run_real_demo.py sub_XXXX

What this does and does not claim
----------------------------------
It issues a **real** Payment Link, with real auth, the real deterministic
`reference_id`, and real error envelopes. Run it twice and the second call
demonstrates the collision path: Razorpay rejects the repeated `reference_id`,
and this fetches rather than creating a second link.

Two things it does **not** do, both stated rather than glossed:

1. **It does not produce a real `subscription.halted`.** Test mode will not
   simulate a *failed* subscription charge, so the trigger is replayed.
2. **The subscription context is synthetic** (A-020). A read-only probe on
   2026-09-01 found `plans` and `subscriptions` returning 401 while seven other
   endpoints returned 200 on the same credentials — the Subscriptions product is
   not enabled on this account. A Payment Link is standalone and needs no
   Subscription, so the link is genuinely real; the subscription it represents is
   not.

The claim is therefore:

    "Payment Links were really issued against Razorpay -- real auth, real
     reference_id collision behaviour, real error envelopes. The subscription
     they represent, and the failure sequence that triggers outreach, were both
     replayed."

and not "the loop ran end-to-end against Razorpay". See A-020, D-033 and README.

Rows produced here are `transport="real"`. The replayed halt is `transport="sim"`.
The run is therefore MIXED, and `require_declared_split()` will refuse to pool it
— which is correct, and is scripted in `VIDEO.md` before it happens on camera.

**No debit is initiated.** Post-halt there is no mandate to debit, and there is no
code path here that could (D-030).
"""

import os
import sys
from datetime import UTC, datetime

from recoup.execute.capture import manifest
from recoup.execute.real import RealTransport, reference_id
from recoup.models import Action


def main() -> int:
    key_id = os.getenv("RZP_KEY_ID", "")
    key_secret = os.getenv("RZP_KEY_SECRET", "")
    if not key_id or not key_secret:
        print(
            "RZP_KEY_ID and RZP_KEY_SECRET must be set. Without them this would "
            "fail on the first call, after the demo had already started.",
            file=sys.stderr,
        )
        return 2
    if not key_id.startswith("rzp_test_"):
        print(
            f"refusing to run: {key_id[:12]}... is not a test-mode key. This demo "
            "issues real payment links and must never run against live keys.",
            file=sys.stderr,
        )
        return 2

    subscription_id = sys.argv[1] if len(sys.argv) > 1 else "sub_demo"
    attempt_no = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    action = Action(
        action_type="create_link",
        channel="whatsapp",
        body="Your payment could not be processed. Pay here: {link}",
        send_at=datetime.now(UTC),
        attempt_no=attempt_no,
        cost_paise=0,
        dlt_template_id="TPL_DEMO",
        dlt_template_approved=True,
        body_matches_registered_template=True,
    )
    context = {
        "subscription_id": subscription_id,
        "amount_paise": 49900,
        "customer_name": "Demo Customer",
        "customer_email": "",
        "customer_contact": "",
    }

    ref = reference_id(subscription_id, action.action_type, attempt_no)
    print(f"subscription : {subscription_id}")
    print(f"attempt      : {attempt_no}")
    print(f"reference_id : {ref}")
    print("  deterministic, so a retry collapses onto the same link rather than")
    print("  creating a second one. Payment Links have no idempotency header.\n")

    result = RealTransport(key_id, key_secret).execute(action, context)

    print(f"ok           : {result.ok}")
    print(f"provider_ref : {result.provider_ref or '-'}")
    print(f"deduplicated : {result.deduplicated}")
    if result.deduplicated:
        print("  ^ the link already existed. Razorpay REJECTS a repeated")
        print("    reference_id rather than replaying it, so this fetched the")
        print("    existing link instead of creating a duplicate (A-009).")
    if result.error:
        print(f"error        : {result.error}")
    print(f"recovered    : {result.recovered}")
    print("  ^ always False. A link being created says nothing about whether")
    print("    anyone paid it; that arrives later as payment_link.paid.\n")

    print("captured payload shapes:")
    for event, status in manifest().items():
        print(f"  {event:26} {status}")
    print(
        "\nRun the ingest with transport='real' and a tunnel to capture the shapes\n"
        "marked capturable. `subscription.halted` cannot be captured in test mode."
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
