"""The response curve. Every parameter is sourced or marked ASSUMPTION.

This file is FROZEN before `agent/` is written. See SIMULATOR_FREEZE.md.
Read simulator/PARAMS.md for the provenance of every number here.

Every constant below is registered in PARAMS with a `class`:

    MEASURED      published figure, stated population, URL
    DERIVED       computed from a MEASURED figure by an arithmetic stated in PARAMS.md
    DEFINITIONAL  a normalisation anchor -- a choice of units, not a finding
    ASSUMPTION    not sourced; swept in the sensitivity analysis (Task 23b)

A constant that is not registered fails `test_every_numeric_constant_in_the_module_is_
registered_in_params`. That test exists because checking PARAMS alone only proves the
registered numbers have sources -- it says nothing about a number typed straight into
the module, which is precisely how an unsourced beyond-curve decay survived the draft.
"""

import bisect

from recoup.simulator.provenance import CLASSES  # noqa: F401  (re-exported for callers)

# --- MEASURED: Baremetrics, 1M+ dunning emails, US B2B SaaS, Dec 2024 --------
# Not monotonic -- day 30 exceeds day 20. That is in the source. Do not smooth it.
DAY_OFFSET_CURVE: dict[int, float] = {
    0: 0.1325,
    3: 0.1146,
    7: 0.1151,
    15: 0.0422,
    20: 0.0383,
    30: 0.0420,
}

# --- DERIVED: Churnkey incremental recovery per email, each / the first -------
ATTEMPT_DECAY: list[float] = [1.00, 0.68, 0.61, 0.54, 0.54]

# --- channel effectiveness, relative to email --------------------------------
# NONE of these is measured. email is the normalisation anchor (DEFINITIONAL);
# sms and whatsapp are ASSUMPTIONs with declared sweep ranges.
#
# In particular sms is NOT 0.6 from Churnkey. Churnkey reports SMS at 0.6 PERCENT
# *share of recoveries*, which is a different quantity from per-message
# effectiveness and depends on send volumes Churnkey does not publish. See the
# correction block in PARAMS.md.
CHANNEL_MULTIPLIER: dict[str, float] = {
    "email": 1.00,
    "whatsapp": 1.00,
    "sms": 0.60,
}

# --- ASSUMPTION: swept 0.30-1.00 ---------------------------------------------
HARD_DECLINE_MULTIPLIER = 0.60

# --- ASSUMPTION: swept 0.00-1.00 ---------------------------------------------
# How much of ATTEMPT_DECAY is applied ON TOP of DAY_OFFSET_CURVE.
#
# The two sources may measure overlapping effects. Baremetrics reports recovery
# by day offset within a dunning SEQUENCE, so its later days are also its later
# attempts; Churnkey reports incremental recovery by email index. Both encode
# "a later contact recovers less". Multiplying them may discount that decline
# twice.
#
# We cannot resolve it from the published figures -- neither source states how
# its two dimensions relate. So it becomes an explicit, swept parameter rather
# than an unexamined multiplication.
#
# 1.0 = full compounding, the default, because it produces LOWER modelled
# recovery in both arms and therefore a smaller lift. Where the modelling is
# ambiguous the default should be the one that claims less.
# 0.0 = timing only; attempt number adds no further penalty.
ATTEMPT_DECAY_COMPOUNDING = 1.0

# --- ASSUMPTION: swept 0.90-1.00 ---------------------------------------------
# The Baremetrics table stops at day 30 and something has to happen past it.
# Every option is an invention; this one is a slow decay matching the source's
# own shape. Registered so it cannot pass as measured.
DECAY_BEYOND_CURVE = 0.97

PARAMS: dict[str, dict] = {
    "day_offset_curve": {
        "constant": "DAY_OFFSET_CURVE",
        "value": DAY_OFFSET_CURVE,
        "class": "MEASURED",
        "source": "https://baremetrics.com/blog/dunning-email-best-practices",
        "population": "1M+ dunning emails, Baremetrics Recover customers (US B2B SaaS), Dec 2024",
    },
    "attempt_decay": {
        "constant": "ATTEMPT_DECAY",
        "value": ATTEMPT_DECAY,
        "class": "DERIVED",
        "source": "https://churnkey.co/blog/involuntary-churn-benchmarks/",
        "population": "6M failed payments, CY2024",
        "derivation": "[2.8, 1.9, 1.7, 1.5, 1.5] incremental recovery per email, each / 2.8",
    },
    "channel_multiplier_email": {
        "constant": "CHANNEL_MULTIPLIER",
        "constant_key": "email",
        "value": 1.00,
        "class": "DEFINITIONAL",
        "source": "normalisation anchor -- every other channel is relative to email",
        "note": "a choice of units, not a finding, and not evidence for anything",
    },
    "channel_multiplier_sms": {
        "constant": "CHANNEL_MULTIPLIER",
        "constant_key": "sms",
        "value": 0.60,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- no sourced per-message SMS effectiveness figure exists",
        "sweep": [0.07, 1.50],
        "note": (
            "Low endpoint is Churnkey's share ratio 0.6/8.4 read literally as "
            "effectiveness -- a reading we hold invalid, used only as a pessimistic "
            "bound. High endpoint is SMS outperforming email, directionally supported "
            "by Cadena & Schoar, NBER WP 17020 (2011), an RCT finding +7-9pp on "
            "on-time payment from monthly SMS reminders."
        ),
    },
    "channel_multiplier_whatsapp": {
        "constant": "CHANNEL_MULTIPLIER",
        "constant_key": "whatsapp",
        "value": 1.00,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- WhatsApp absent from Churnkey's US-centric data",
        "sweep": [0.50, 1.50],
        "note": (
            "Modelled at email parity. Deliberately NOT modelled higher: the quoted "
            "'WhatsApp 98% open rate' traces to vendor copy with no published "
            "methodology and no Meta-published equivalent. What is sourced about "
            "WhatsApp is cost, not effectiveness."
        ),
    },
    "hard_decline_multiplier": {
        "constant": "HARD_DECLINE_MULTIPLIER",
        "value": HARD_DECLINE_MULTIPLIER,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- direction well founded, magnitude not measured",
        "sweep": [0.30, 1.00],
        "note": (
            "Hard declines need a new payment method, a larger customer action than "
            "topping up a balance. Upper endpoint 1.00 is 'no penalty at all', which "
            "the sweep must be able to reach for it to be a real test."
        ),
    },
    "attempt_decay_compounding": {
        "constant": "ATTEMPT_DECAY_COMPOUNDING",
        "value": ATTEMPT_DECAY_COMPOUNDING,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- the two sources may measure overlapping effects",
        "sweep": [0.00, 1.00],
        "note": (
            "Baremetrics reports recovery by day offset within a dunning sequence, "
            "so its later days are also its later attempts; Churnkey reports "
            "incremental recovery by email index. Multiplying them may discount "
            "the same decline twice, and neither source states how its dimensions "
            "relate. Default 1.0 (full compounding) because it lowers modelled "
            "recovery in both arms and so claims less."
        ),
    },
    "decay_beyond_curve": {
        "constant": "DECAY_BEYOND_CURVE",
        "value": DECAY_BEYOND_CURVE,
        "class": "ASSUMPTION",
        "source": "ASSUMPTION -- the Baremetrics table stops at day 30",
        "sweep": [0.90, 1.00],
        "note": (
            "1.00 is flat, no further decay. Not swept below 0.90: a faster decay "
            "makes late outreach worthless, which flatters the agent's early-contact "
            "policy rather than testing it."
        ),
    },
    "baseline_recovery_rate": {
        "value": 0.51,
        "class": "MEASURED",
        "source": "https://churnkey.co/blog/involuntary-churn-benchmarks/",
        "population": "Stripe Smart Retries alone, 5.4M failures",
        "note": "p1 in the power calculation (A-001). Not read by this module.",
    },
}

_CURVE_DAYS = sorted(DAY_OFFSET_CURVE)

# Module-level names the registration check may skip: derived from a registered
# constant, or structural rather than generative. Anything else must be in PARAMS.
UNREGISTERED_OK = frozenset({"PARAMS", "CLASSES", "UNREGISTERED_OK", "_CURVE_DAYS"})


def _base_rate(day_offset: int) -> float:
    """Linear interpolation between measured points; geometric decay past the end."""
    if day_offset <= _CURVE_DAYS[0]:
        return DAY_OFFSET_CURVE[_CURVE_DAYS[0]]
    if day_offset >= _CURVE_DAYS[-1]:
        last = _CURVE_DAYS[-1]
        return DAY_OFFSET_CURVE[last] * (DECAY_BEYOND_CURVE ** (day_offset - last))

    i = bisect.bisect_left(_CURVE_DAYS, day_offset)
    lo, hi = _CURVE_DAYS[i - 1], _CURVE_DAYS[i]
    if day_offset == hi:
        return DAY_OFFSET_CURVE[hi]
    frac = (day_offset - lo) / (hi - lo)
    return DAY_OFFSET_CURVE[lo] + frac * (DAY_OFFSET_CURVE[hi] - DAY_OFFSET_CURVE[lo])


def recovery_probability(
    day_offset: int,
    channel: str,
    attempt_no: int,
    is_hard_decline: bool,
) -> float:
    """Probability that this single outreach recovers the payment.

    Unknown inputs raise rather than falling back. An unrecognised channel taking
    email parity would silently model a typo as the most effective channel
    available, and a negative day offset would be clamped to day 0 -- the highest
    rate in the whole curve. Both would flatter the result and say nothing.
    """
    if day_offset < 0:
        raise ValueError(
            f"day_offset must be >= 0, got {day_offset}. Outreach dated before the "
            "halt that caused it is an upstream bug, not a day-0 contact."
        )
    if channel not in CHANNEL_MULTIPLIER:
        raise ValueError(
            f"unknown channel {channel!r}; known channels are "
            f"{sorted(CHANNEL_MULTIPLIER)}. Refusing to assume email parity."
        )
    if attempt_no < 1:
        raise ValueError(f"attempt_no must be >= 1, got {attempt_no}")

    p = _base_rate(day_offset)
    p *= CHANNEL_MULTIPLIER[channel]
    raw_decay = ATTEMPT_DECAY[min(attempt_no - 1, len(ATTEMPT_DECAY) - 1)]
    # Interpolate between "no extra attempt penalty" (1.0) and the full measured
    # decay, per ATTEMPT_DECAY_COMPOUNDING. See its definition for why this is a
    # parameter and not a plain multiplication.
    p *= 1.0 + ATTEMPT_DECAY_COMPOUNDING * (raw_decay - 1.0)
    if is_hard_decline:
        p *= HARD_DECLINE_MULTIPLIER
    return max(0.0, min(1.0, p))
