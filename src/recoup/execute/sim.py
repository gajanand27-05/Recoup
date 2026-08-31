"""Simulated transport: the counterfactual customer.

Draws from the FROZEN response curve. This class is what decides whether the
agent wins, which is exactly why `simulator/` is frozen and hash-tagged before
`agent/` is written, and why `PARAMS.md` cites every number.
"""

import hashlib
import random

from recoup.execute.transport import ActionResult
from recoup.models import Action
from recoup.simulator.curve import recovery_probability


class SimTransport:
    """Implements `Transport`. Deterministic given a seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._rng = random.Random(seed)

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
        recovered = self._rng.random() < p

        ref_material = f"{self.seed}|{action.attempt_no}|{action.channel}|{action.send_at}"
        ref = "plink_sim_" + hashlib.sha256(ref_material.encode()).hexdigest()[:14]

        return ActionResult(
            ok=True,
            provider_ref=ref,
            recovered=recovered,
            cost_paise=action.cost_paise,
        )
