"""Scenario generation for the batch run.

FROZEN before `agent/` exists. Reason mix is sourced from Churnkey's 5M-failure
decline distribution; see simulator/PARAMS.md.

`would_self_recover` is a GROUND-TRUTH LABEL. It exists to measure the cost of
acting on a payment that would have recovered anyway. `eval/lift.py` must never
read it (D-011) -- see `eval/__init__.py` for the rule and the enforcement.

Every constant here is registered in PARAMS with a class. See
`simulator/provenance.py` for why registration is checked structurally rather
than by iterating PARAMS.
"""

import random
from dataclasses import dataclass

from recoup.simulator.provenance import CLASSES  # noqa: F401  (re-exported for callers)

# --- MEASURED: Churnkey, 5M failures -----------------------------------------
# The twelve published codes sum to 0.9456. `other` is the RESIDUAL, 1 - 0.9456.
#
# PLAN.md had `other: 0.1544`, which is a digit error: it made the weights total
# 1.1000, and since random.choices normalises, every sourced share was silently
# rescaled -- insufficient_funds would have run at 36.87% rather than the 40.56%
# it cites. A residual that is not 1 - sum(sourced) is not a residual.
_SOURCED_REASON_SHARES: dict[str, float] = {
    "insufficient_funds": 0.4056,
    "transaction_not_allowed": 0.0883,
    "highest_risk_level": 0.0799,
    "do_not_honor": 0.0756,
    "previously_declined_do_not_retry": 0.0644,
    "generic_decline": 0.0578,
    "incorrect_number": 0.0469,
    "try_again_later": 0.0413,
    "partner_insufficient_funds": 0.0368,
    "invalid_account": 0.0271,
    "expired_card": 0.0114,
    "card_velocity_exceeded": 0.0105,
}

REASON_MIX: dict[str, float] = {
    **_SOURCED_REASON_SHARES,
    "other": round(1.0 - sum(_SOURCED_REASON_SHARES.values()), 10),
}

# --- MEASURED: https://docs.stripe.com/declines/codes ------------------------
# Six of these (lost_card, stolen_card, pickup_card, authentication_required,
# revocation_of_authorization, revocation_of_all_authorizations) do not appear in
# Churnkey's published table at all, so they fall inside `other` -- which this
# generator models as entirely soft. That is an ASSUMPTION, registered below.
HARD_DECLINE_CODES: frozenset[str] = frozenset({
    "incorrect_number",
    "lost_card",
    "pickup_card",
    "stolen_card",
    "revocation_of_authorization",
    "revocation_of_all_authorizations",
    "authentication_required",
    "highest_risk_level",
    "transaction_not_allowed",
})

# --- ASSUMPTION: the counterfactual --------------------------------------------
# The fraction that would have recovered with NO intervention at all. This is the
# single most consequential invented number in the project: it defines the
# baseline the entire lift claim is measured against.
SELF_RECOVERY_RATE_SOFT = 0.18
SELF_RECOVERY_RATE_HARD = 0.03

# --- ASSUMPTION: Indian SaaS subscription price points, in paise ---------------
_AMOUNT_CHOICES = [29900, 49900, 79900, 99900, 149900, 249900, 499900]
_AMOUNT_WEIGHTS = [0.22, 0.26, 0.18, 0.14, 0.10, 0.06, 0.04]

PARAMS: dict[str, dict] = {
    "reason_mix": {
        "constant": "REASON_MIX",
        "value": REASON_MIX,
        "class": "DERIVED",
        "source": "https://churnkey.co/blog/involuntary-churn-benchmarks/",
        "population": "5M failed payments, CY2024",
        "derivation": (
            "twelve published code shares verbatim; `other` = 1 - their sum = 0.0544"
        ),
    },
    "sourced_reason_shares": {
        "constant": "_SOURCED_REASON_SHARES",
        "value": _SOURCED_REASON_SHARES,
        "class": "MEASURED",
        "source": "https://churnkey.co/blog/involuntary-churn-benchmarks/",
        "population": "5M failed payments, CY2024",
    },
    "hard_decline_codes": {
        "constant": "HARD_DECLINE_CODES",
        "value": sorted(HARD_DECLINE_CODES),
        "class": "MEASURED",
        "source": "https://docs.stripe.com/declines/codes",
        "population": "Stripe's published non-retryable decline codes",
    },
    "residual_bucket_is_soft": {
        "value": 0.0,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- six hard codes are absent from Churnkey's table",
        "sweep": [0.0, 0.30],
        "note": (
            "lost_card, stolen_card, pickup_card, authentication_required and the "
            "two revocation codes never appear in the sourced mix, so they sit "
            "inside `other` (5.44%) and are modelled as soft. The sweep asks what "
            "happens if up to 30% of the residual is actually hard. Hard-decline "
            "share is 21.51% as modelled, against the ~21% PARAMS.md claims."
        ),
    },
    "self_recovery_rate_soft": {
        "constant": "SELF_RECOVERY_RATE_SOFT",
        "value": SELF_RECOVERY_RATE_SOFT,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- no published post-halt no-intervention recovery rate",
        "sweep": [0.05, 0.35],
        "note": (
            "THE most consequential invented number here: it defines the "
            "counterfactual the whole lift claim is measured against. Post-halt "
            "means Razorpay has stopped retrying, so any recovery is the customer "
            "acting unprompted. Swept wide because we have no measurement of it."
        ),
    },
    "self_recovery_rate_hard": {
        "constant": "SELF_RECOVERY_RATE_HARD",
        "value": SELF_RECOVERY_RATE_HARD,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- as above, for the hard-decline segment",
        "sweep": [0.00, 0.10],
        "note": (
            "A hard decline needs a new payment method, so unprompted recovery "
            "should be rare. 0.00 at the low end is 'never recovers alone'."
        ),
    },
    "amount_distribution": {
        "constant": "_AMOUNT_CHOICES",
        "value": _AMOUNT_CHOICES,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- no sourced Indian SaaS subscription price distribution",
        "sweep": [29900, 499900],
        "note": (
            "Plausible Indian SaaS price points. Affects money-weighted figures "
            "only, not recovery rates. Reported in rupees alongside rate figures "
            "precisely so a reader can see which claims depend on it."
        ),
    },
    "amount_weights": {
        "constant": "_AMOUNT_WEIGHTS",
        "value": _AMOUNT_WEIGHTS,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- weights over the price points above",
        "sweep": [0.0, 1.0],
        "note": "Skewed toward lower price points; sums to 1.0.",
    },
}

UNREGISTERED_OK = frozenset({"PARAMS", "CLASSES", "UNREGISTERED_OK"})


@dataclass(frozen=True)
class Scenario:
    subscription_id: str
    customer_id: str
    amount_paise: int
    reason_code: str
    is_hard_decline: bool
    would_self_recover: bool


def generate_scenarios(n: int, seed: int) -> list[Scenario]:
    """Deterministic batch of failure scenarios.

    Identifiers carry the seed. The A/A batch is drawn from outside the powered N
    (D-032), so a positional-only id would give both batches `sub_sim_000001` and
    replay would merge two different subscriptions into one state.
    """
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")

    rng = random.Random(seed)
    codes = list(REASON_MIX)
    weights = [REASON_MIX[c] for c in codes]

    out: list[Scenario] = []
    for i in range(n):
        code = rng.choices(codes, weights=weights, k=1)[0]
        hard = code in HARD_DECLINE_CODES
        rate = SELF_RECOVERY_RATE_HARD if hard else SELF_RECOVERY_RATE_SOFT
        out.append(
            Scenario(
                subscription_id=f"sub_sim_{seed}_{i:06d}",
                customer_id=f"cust_sim_{seed}_{i:06d}",
                amount_paise=rng.choices(_AMOUNT_CHOICES, weights=_AMOUNT_WEIGHTS, k=1)[0],
                reason_code=code,
                is_hard_decline=hard,
                would_self_recover=rng.random() < rate,
            )
        )
    return out
