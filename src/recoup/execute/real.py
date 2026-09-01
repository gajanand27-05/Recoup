"""Real transport: genuine Razorpay test-mode API calls. **Branch (b) of D-033.**

What this is, and what it is not
---------------------------------
Gate 1 — whether the Dashboard's "Charge this now" offers a *failed* outcome —
was never answered, so per the weaker-claim rule branch (b) ships. Branch (b) is
**not branch (a) with steps removed.** It is a different construction with a
different claim:

    "Payment Links were really issued against Razorpay — real auth, real
     reference_id collision behaviour, real error envelopes. The subscription
     they represent, and the failure sequence that triggers outreach, were both
     REPLAYED."

That is weaker than "the loop ran end-to-end against Razorpay", and it is said in
that form. See A-020, D-033 and the README limitations section.

**A-020 narrowed this further on 2026-09-01.** An earlier wording said "real
Payment Links against real subscriptions". A read-only probe found `plans` and
`subscriptions` returning 401 while seven other endpoints returned 200 on the
same credentials — the Subscriptions product is not enabled on the account. A
Payment Link is standalone and needs no Subscription, so the links are genuinely
real while the subscription context around them is synthetic. The narrowed
wording is not rounded back up if the product is enabled later; that would be a
new run with a new claim.

Consequence: the demo run is transport-MIXED
---------------------------------------------
The replayed `subscription.halted` produces `sim` rows; everything this module
does produces `real` rows. One subscription's history therefore spans both, and
`eval.transport_split.require_declared_split()` will **refuse to pool that run**.
That is correct behaviour, not a bug — see the note in `VIDEO.md`, written before
it happens on camera.

Idempotency, all sourced (LOGS 8c)
-----------------------------------
  - Payment Links create has **no idempotency header**. This is why `reference_id`
    exists at all.
  - `reference_id` is unique-enforced but it **REJECTS** duplicates; it does not
    replay them. So "already exists" is treated as success-and-fetch.
  - On a timeout we `GET` by `reference_id` **before** ever retrying. Never
    blind-retry a create — that is how you charge someone twice. (A-009)

Do **not** use `upi_link: true`: live mode only. Use
`options.checkout.method.upi` (A-010).

This module never initiates a debit. Post-halt there is no mandate to debit, and
there is no code path here that could (D-030).
"""

import hashlib

import httpx

from recoup.execute.transport import ActionResult
from recoup.models import Action

BASE_URL = "https://api.razorpay.com/v1"

# Substrings Razorpay uses when a reference_id is already taken. Matched
# case-insensitively against the error description. class: INDUSTRY_PRACTICE --
# the rejection is documented, the exact wording is not contractual, so a miss
# here degrades to "create failed" rather than to a duplicate link.
_DUPLICATE_MARKERS = ("reference_id", "already exists", "duplicate")


def reference_id(subscription_id: str, action_type: str, attempt_no: int) -> str:
    """Deterministic, so retries collapse instead of duplicating. Max 40 chars.

    sha256(subscription_id|action_type|attempt_no)[:40] — A-009.
    """
    material = f"{subscription_id}|{action_type}|{attempt_no}"
    return hashlib.sha256(material.encode()).hexdigest()[:40]


class RealTransport:
    """Implements `Transport`. Issues genuine Razorpay test-mode Payment Links."""

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not key_id or not key_secret:
            raise ValueError(
                "RealTransport needs both key_id and key_secret. Constructing it "
                "without credentials would fail on the first call, after the run "
                "had already started."
            )
        self._client = client or httpx.Client(auth=(key_id, key_secret), timeout=timeout)

    @property
    def name(self) -> str:
        return "real"

    # --- provider calls ------------------------------------------------------

    def _find_by_reference(self, ref: str) -> dict | None:
        try:
            resp = self._client.get(
                f"{BASE_URL}/payment_links", params={"reference_id": ref}
            )
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        items = resp.json().get("payment_links", [])
        return items[0] if items else None

    @staticmethod
    def _is_duplicate_rejection(resp: httpx.Response) -> bool:
        if resp.status_code != 400:
            return False
        try:
            description = str(resp.json().get("error", {}).get("description", ""))
        except ValueError:
            return False
        low = description.lower()
        return any(marker in low for marker in _DUPLICATE_MARKERS)

    def _payload(self, action: Action, context: dict, ref: str) -> dict:
        return {
            "amount": context["amount_paise"],
            "currency": "INR",
            "accept_partial": False,
            "reference_id": ref,
            "description": "Subscription payment recovery",
            "customer": {
                "name": context.get("customer_name", "Customer"),
                "email": context.get("customer_email", ""),
                "contact": context.get("customer_contact", ""),
            },
            # We send our own messages. Razorpay's notifications would
            # double-message and would not pass through our policy engine.
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            # NOT `upi_link: true` -- that is live mode only (A-010).
            "options": {"checkout": {"method": {"upi": "1"}}},
        }

    # --- the boundary --------------------------------------------------------

    def execute(self, action: Action, context: dict) -> ActionResult:
        """Create a payment link, exactly once, for this (subscription, action, attempt).

        `recovered` is ALWAYS False. A link being created says nothing about
        whether anyone paid it; that arrives later as a `payment_link.paid`
        webhook. Returning anything else here would be the transport claiming to
        know an outcome it cannot see.
        """
        if action.action_type in ("wait", "stop"):
            return ActionResult(ok=True, provider_ref="", recovered=False, cost_paise=0)

        ref = reference_id(
            context["subscription_id"], action.action_type, action.attempt_no
        )
        payload = self._payload(action, context, ref)

        try:
            resp = self._client.post(f"{BASE_URL}/payment_links", json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # NEVER blind-retry a create. Ask the provider what happened first.
            existing = self._find_by_reference(ref)
            if existing:
                return ActionResult(
                    ok=True,
                    provider_ref=existing.get("id", ""),
                    recovered=False,
                    cost_paise=action.cost_paise,
                    deduplicated=True,
                )
            return ActionResult(
                ok=False,
                provider_ref="",
                recovered=False,
                cost_paise=0,
                error=f"{type(exc).__name__}: link not created and none found for {ref}",
            )

        if resp.status_code in (200, 201):
            return ActionResult(
                ok=True,
                provider_ref=resp.json().get("id", ""),
                recovered=False,
                cost_paise=action.cost_paise,
            )

        if self._is_duplicate_rejection(resp):
            # reference_id collisions REJECT, they do not replay. Treat as
            # success-and-fetch: the work was already done.
            existing = self._find_by_reference(ref)
            if existing:
                return ActionResult(
                    ok=True,
                    provider_ref=existing.get("id", ""),
                    recovered=False,
                    cost_paise=0,  # nothing new was sent, so nothing new was spent
                    deduplicated=True,
                )
            return ActionResult(
                ok=False,
                provider_ref="",
                recovered=False,
                cost_paise=0,
                error=f"reference_id {ref} rejected as duplicate but no link found",
            )

        try:
            detail = resp.json().get("error", {}).get("description", resp.text)
        except ValueError:
            detail = resp.text
        return ActionResult(
            ok=False,
            provider_ref="",
            recovered=False,
            cost_paise=0,
            error=f"HTTP {resp.status_code}: {detail}",
        )
