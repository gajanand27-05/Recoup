"""Simulated transport: the counterfactual customer.

Draws from the FROZEN response curve. This class is what decides whether the
agent wins, which is exactly why `simulator/` is frozen and hash-tagged before
`agent/` is written, and why `PARAMS.md` cites every number.
"""

import hashlib

from recoup.execute.transport import ActionResult
from recoup.models import Action
from recoup.simulator.curve import recovery_probability


def _uniform(*parts) -> float:
    """A uniform draw in [0, 1) derived from identity, not from call order.

    `random.Random(seed).random()` advances shared state, so which draw a
    subscription receives depends on how many draws happened before it — that is,
    on the ORDER subscriptions were processed, and under a thread pool on the
    interleaving. Two runs of the same batch at different concurrency then
    produce different outcomes, and the whole reproducibility claim goes with it.

    Found by `test_concurrency_produces_the_same_rows_as_sequential`, which is
    also why that test exists: a sequential run and a 4-way concurrent run of the
    same seed disagreed on which subscriptions recovered.

    Hashing stable identifiers instead makes the draw a pure function of *which
    subscription, which attempt* — order-independent, thread-safe, and identical
    whether the batch runs on one thread or six.
    """
    material = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(material.encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


class SimTransport:
    """Implements `Transport`.

    Deterministic given a seed **and independent of processing order**. The
    second half is not free — see `_uniform`.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed

    @property
    def name(self) -> str:
        return "sim"

    def execute(self, action: Action, context: dict) -> ActionResult:
        if action.action_type in ("wait", "stop"):
            return ActionResult(ok=True, provider_ref="", recovered=False, cost_paise=0)

        p = recovery_probability(
            day_offset=context.get("day_offset", 0),
            channel=action.channel,
            attempt_no=action.attempt_no,
            is_hard_decline=context.get("is_hard_decline", False),
        )
        # Keyed on the subscription, so the draw belongs to that subscription
        # rather than to its position in the queue. `subscription_id` falls back
        # to the provider ref material only if a caller omitted it — a missing id
        # would otherwise collapse every subscription onto the same draw.
        subscription_id = context.get("subscription_id") or getattr(
            context.get("scenario"), "subscription_id", "unknown"
        )
        recovered = _uniform(
            self.seed, subscription_id, action.attempt_no, context.get("day_offset", 0)
        ) < p

        ref_material = f"{self.seed}|{action.attempt_no}|{action.channel}|{action.send_at}"
        ref = "plink_sim_" + hashlib.sha256(ref_material.encode()).hexdigest()[:14]

        return ActionResult(
            ok=True,
            provider_ref=ref,
            recovered=recovered,
            cost_paise=action.cost_paise,
        )
