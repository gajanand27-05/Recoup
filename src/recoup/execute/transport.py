"""The transport boundary.

In Razorpay test mode nothing gets paid unless something pays it. At batch scale
our simulator is acting as the counterfactual customer — it is the outcome
oracle. Hiding that inside the executor would be the single most dangerous thing
this design could do, so it is a named boundary in the type system (D-009).

Every ledger row records which transport produced it. `real` and `sim` are NEVER
pooled in any reported number.

The two transports are not interchangeable, and that is the point
------------------------------------------------------------------
`SimTransport.execute()` returns whether the payment was recovered. It can,
because it *is* the customer.

`RealTransport.execute()` **always returns `recovered=False`**, and not because
nothing was recovered. A real payment link being created says nothing about
whether anyone paid it; that answer arrives later, asynchronously, as a
`payment_link.paid` webhook. A real transport that claimed to know the outcome
synchronously would be lying about the one thing this boundary exists to make
honest.

So the two differ in *what they can know*, not merely in how they are implemented
— which is a further reason the numbers they produce are never pooled.
"""

from dataclasses import dataclass
from typing import Protocol

from recoup.models import Action


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    provider_ref: str
    recovered: bool
    cost_paise: int
    error: str | None = None

    # True when the provider already had this reference and we fetched it rather
    # than creating a second one. Recorded because "we did not double-charge"
    # should be visible in the ledger, not inferred from an absence.
    deduplicated: bool = False


class Transport(Protocol):
    @property
    def name(self) -> str:
        """'real' or 'sim'. Written to every ledger row."""
        ...

    def execute(self, action: Action, context: dict) -> ActionResult: ...
