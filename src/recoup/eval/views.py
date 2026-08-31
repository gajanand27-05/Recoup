"""The firewall.

Ground-truth labels and a holdout arm are two different measurement systems.
Mixing them makes the result circular: the simulator decides who recovers, so
using its labels to compute lift would be measuring the simulator against
itself.

`LiftView` is the ONLY shape `lift.py` is allowed to see. The ground-truth label
is deliberately absent, and `tests/test_firewall.py` fails the build if it
returns — including by a transitive import route, which a direct-import check
would miss.

The label IS legitimately used elsewhere — false-positive cost, randomisation
balance — in modules that never compute lift. See `eval/diagnostics.py`.

⚠️ **If you are about to write `lift.py`: the firewall has been exercised.**
Because `lift.py` does not exist, the guards protecting it have no subject to
fail on and would pass vacuously. So `tests/test_firewall.py` writes a genuinely
violating `lift.py` into this package on every run, confirms both the import
closure and the label scan catch it, and deletes it — once for a direct import of
the generator, once for an indirect route through a helper, which a direct-import
check would miss. You are not the first thing to test them.

Why `amount_paise` is passed in rather than looked up
-----------------------------------------------------
`SubscriptionState` deliberately carries no subscription-level amount: amount is
per invoice, and a plan change or proration legitimately produces two different
values for one subscription (see `ledger/replay.py`). The amount therefore comes
from the scenario — and the scenario object also carries the ground-truth label.

So this module does **not** import the generator. If it did, `lift.py` would
reach the labels transitively through the very module built to prevent that.
The caller — the batch runner, which legitimately sees both — passes the single
permitted field as a plain integer. `tests/test_firewall.py` pins that this
module's import closure stays clean.
"""

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from recoup.ledger.replay import SubscriptionState


@dataclass(frozen=True)
class LiftView:
    """A ledger row as the lift calculation is permitted to see it."""

    subscription_id: str
    arm: str
    status: str
    amount_paise: int
    recovered_paise: int
    spend_paise: int
    attempts: int

    __columns__ = frozenset({
        "subscription_id", "arm", "status", "amount_paise",
        "recovered_paise", "spend_paise", "attempts",
    })

    @classmethod
    def from_state(cls, state: "SubscriptionState", *, amount_paise: int) -> "LiftView":
        """Project replayed state onto the permitted columns.

        This exists so the view has a producer. A declared shape with no way to
        build it from real data is the INC-005 shape: something registered,
        described, and never wired up — which reads as working.

        `amount_paise` is keyword-only so it cannot be passed positionally into
        the wrong slot, and it is the caller's job to supply it from the scenario.
        """
        if state.arm is None:
            raise ValueError(
                f"subscription {state.subscription_id!r} has no arm assigned; it "
                "cannot appear in a lift calculation"
            )
        return cls(
            subscription_id=state.subscription_id,
            arm=state.arm,
            status=state.status,
            amount_paise=amount_paise,
            recovered_paise=state.recovered_paise,
            spend_paise=state.spend_paise,
            attempts=state.attempts,
        )

    def as_dict(self) -> dict:
        """Only the permitted columns, by construction rather than by promise."""
        return {f.name: getattr(self, f.name) for f in fields(self)}
