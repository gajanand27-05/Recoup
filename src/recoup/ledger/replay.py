"""Ledger -> state, as a pure function.

The eval harness reads only from the ledger (D-016), so this is the single path
from recorded events to anything reportable. Two properties, both forced by
reality rather than by taste:

1. ORDER INDEPENDENCE. Razorpay webhooks are at-least-once and UNORDERED (A-008),
   so replay must produce the same state for any permutation of the same rows.
   Accumulations are therefore sets, sums and maxima -- operations that commute.

2. IDEMPOTENCE. The same row applied twice must count once, so actions are keyed
   on `attempt_no` rather than counted.

Why conflicts raise instead of resolving
----------------------------------------
Commutative accumulation covers the fields that accumulate. It says nothing about
the fields that are simply ASSIGNED -- `arm`, `customer_id`, and the cost of a
given attempt. Those are last-write-wins, and last-write-wins over an unordered
stream means "whichever happened to arrive last".

Shuffling a fixture whose rows all agree will never reveal this: with no
conflicting values there is no last write to observe. So the assignment path
refuses disagreement outright. A subscription that appears in two arms is a
randomisation failure, and picking a winner by arrival position would bury it in
a number rather than raising it as a fault.

Identical repeats are not conflicts. At-least-once delivery makes the same row
arriving five times entirely ordinary.

What is NOT conflictable, and why
---------------------------------
There is no subscription-level amount here, deliberately. Two different amounts
for one subscription is a perfectly ordinary history -- a plan change, a
proration, a different invoice -- and a Razorpay subscription entity does not
carry an amount at all: it carries `plan_id`, while the money lives on the plan's
`item.amount` and on invoice and payment entities. Amount is per-INVOICE.

Treating it as a conflictable subscription scalar would have halted a whole batch
run on the first legitimate upgrade, and the pressure then would be to weaken the
conflict check itself -- taking the `arm` protection down with it. The conflict
disappears by construction rather than by loosening a predicate.

Money that matters to the measurement arrives as `outcome.recovered`, which is
accumulated with `max` so a redelivery cannot invent payment. An at-risk
denominator, when Task 22 needs one, must be built per invoice and not as a
scalar on this state.
"""

from dataclasses import dataclass, field


class ReplayConflict(Exception):
    """Two rows assert different values for the same field of one subscription.

    Never resolved by position. If this fires, the ledger contains a genuine
    contradiction and every figure derived from it is suspect until explained.
    """


@dataclass
class SubscriptionState:
    subscription_id: str
    customer_id: str | None = None
    arm: str | None = None
    attempts_seen: set[int] = field(default_factory=set)
    spend_by_attempt: dict[int, int] = field(default_factory=dict)
    recovered_paise: int = 0
    opted_out: bool = False
    ptp_date: str | None = None

    @property
    def attempts(self) -> int:
        return len(self.attempts_seen)

    @property
    def spend_paise(self) -> int:
        return sum(self.spend_by_attempt.values())

    @property
    def status(self) -> str:
        """The OUTCOME, which is not the same question as `opted_out`.

        NOTE: `PLAN.md` Task 7 says opt-out is terminal. This deliberately does
        the opposite, and the plan is not the authority here. Its own test only
        covers the case where nothing was recovered, so both readings pass it.
        Do not "restore" the plan's behaviour without reading the next paragraph.

        Recovery outranks opt-out deliberately. Opting out of further messaging
        does not un-pay an invoice, and treating it as terminal would drop a real
        recovery out of the numerator because the customer later asked to be left
        alone. `opted_out` remains the operational flag meaning "send nothing
        more"; it is read by the policy engine, not by the outcome measure.
        """
        if self.recovered_paise > 0:
            return "recovered"
        if self.opted_out:
            return "opted_out"
        if self.attempts:
            return "in_progress"
        return "new"

    def to_canonical(self) -> dict:
        """The ONLY way this state gets serialised. One projection, all callers.

        `attempts_seen` is a set and `spend_by_attempt` is a dict whose insertion
        order follows webhook ARRIVAL order. Two identical runs therefore hold
        equal states -- set and dict equality do not care about order -- while
        producing different bytes through any serialiser that walks them as they
        sit. A `.head`-style artifact, a report digest, or anything hashed would
        then mismatch with no attacker and no bug.

        That is the same failure as the append/verify payload divergence in Task
        3 (INC-001), and it gets the same fix: not "remember to sort", but a
        single projection that every caller goes through. Sets become sorted
        lists; integer keys become strings, because JSON has no others.
        """
        return {
            "subscription_id": self.subscription_id,
            "customer_id": self.customer_id,
            "arm": self.arm,
            "attempts_seen": sorted(self.attempts_seen),
            "spend_by_attempt": {
                str(k): self.spend_by_attempt[k] for k in sorted(self.spend_by_attempt)
            },
            "recovered_paise": self.recovered_paise,
            "opted_out": self.opted_out,
            "ptp_date": self.ptp_date,
            "status": self.status,
        }


def _assign(state: SubscriptionState, field_name: str, value: object) -> None:
    """Set a scalar once. Agreeing repeats are fine; disagreement is a fault."""
    if value is None or value == 0:
        return  # absent, not asserted -- an arm of None never overwrites a real one
    current = getattr(state, field_name)
    if current not in (None, 0) and current != value:
        raise ReplayConflict(
            f"subscription {state.subscription_id!r} has conflicting {field_name}: "
            f"{current!r} and {value!r}. Refusing to pick one by arrival order -- "
            f"webhook delivery is unordered, so that would be arbitrary."
        )
    setattr(state, field_name, value)


def replay(rows: list[dict]) -> dict[str, SubscriptionState]:
    """Build per-subscription state from ledger rows, in any order.

    Rows with no `subscription_id` are not attributable to a subscription and are
    skipped. Use `count_unattributable()` to find out how many -- they are events
    that happened and are missing from every per-subscription figure.
    """
    states: dict[str, SubscriptionState] = {}

    for row in rows:
        sub_id = row.get("subscription_id")
        if not sub_id:
            continue

        st = states.setdefault(sub_id, SubscriptionState(subscription_id=sub_id))
        payload = row.get("payload") or {}

        _assign(st, "customer_id", row.get("customer_id"))
        _assign(st, "arm", row.get("arm"))

        event = row["event_type"]

        if event == "action.executed":
            attempt = payload.get("attempt_no")
            if attempt is not None:
                cost = payload.get("cost_paise", 0)
                prior = st.spend_by_attempt.get(attempt)
                if prior is not None and prior != cost:
                    raise ReplayConflict(
                        f"subscription {sub_id!r} attempt {attempt} has conflicting "
                        f"cost_paise: {prior} and {cost}. One attempt has one cost."
                    )
                st.attempts_seen.add(attempt)
                st.spend_by_attempt[attempt] = cost

        elif event == "outcome.recovered":
            # max, not +=: at-least-once delivery means the same recovery can be
            # recorded twice, and adding would invent money that was never paid.
            st.recovered_paise = max(st.recovered_paise, payload.get("amount_paise", 0))

        elif event == "opt_out":
            st.opted_out = True

        elif event == "ptp_hold":
            promised = payload.get("promised_date")
            if promised and (st.ptp_date is None or promised > st.ptp_date):
                st.ptp_date = promised

    return states


def count_unattributable(rows: list[dict]) -> int:
    """Rows that belong to no subscription, and so appear in no per-subscription figure.

    An unparseable webhook, or one whose entity shape was not recognised, has no
    `subscription_id`. Those events happened. Letting them vanish silently
    shortens the denominator exactly the way a given-up event does.
    """
    return sum(1 for row in rows if not row.get("subscription_id"))


def canonical_states(states: dict[str, SubscriptionState]) -> dict:
    """Serialise a whole replay result deterministically.

    Use this rather than walking `states` directly anywhere the output is hashed,
    diffed, written to a file, or compared between runs.
    """
    return {sub_id: states[sub_id].to_canonical() for sub_id in sorted(states)}
