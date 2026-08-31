"""A/A test — validating the instrument before trusting the measurement.

Both arms run the identical policy. If the harness reports lift here, it
manufactures lift, and every number the project produces is void.

**This is the one measurement in the project where a NULL result is the success
condition**, which inverts every incentive elsewhere in the build. The seed, the
N and the response to a failure are therefore fixed in `EXPERIMENT.md` — the file
whose commit timestamp is the evidence — and not decided here.

What this validates, and what it does not
-----------------------------------------
It exercises the **statistical machinery**: two Bernoulli samples at the same rate
pushed through the same interval and test code the report uses. It never touches
arm assignment, the ledger, or replay, so it **cannot** detect a broken assignment
hash, a seed collision, or the identifier-collision class already caught once in
Task 9 — which are precisely the failures an A/A is supposed to catch.

A **full-pipeline A/A** is therefore pre-registered in `EXPERIMENT.md` for after
Task 22 and before the main batch. Reporting this one as though it validated the
harness would be a claim the test does not support.

Its power is the same as the main design, 6.23pp at 1,000 per arm. A pass rules
out harness bias **larger than about six percentage points**; it does not
establish that the harness is unbiased.

If it fails
-----------
It is **not re-run with a new seed.** That is optional stopping wearing a
different hat. It becomes an `INCIDENTS.md` entry carrying the failing seed and
the observed p-value, the harness is investigated, and it is re-run only after a
fix — with the same seed, and both runs reported.

`injected_lift` exists only to test this test: inject real lift and the A/A must
fail. A check that cannot fail is not a check.
"""

import random
from dataclasses import dataclass

from recoup.eval.power import BASELINE_P1
from recoup.eval.stats import newcombe_diff_interval, two_proportion_z_test

# Declared in EXPERIMENT.md, which is authoritative. These must match it; a test
# parses the file and compares. A seed quietly changed after the pre-registration
# was pushed would leave a committed file claiming one thing and a reported result
# produced by another.
AA_SEED = 20260831
AA_N_PER_ARM = 1000

# Sourced, read from the frozen registry rather than typed -- the same property
# the power calculation relies on, so the rate cannot drift from PARAMS.lock.json.
DEFAULT_TRUE_RATE = BASELINE_P1


@dataclass(frozen=True)
class AAResult:
    n_per_arm: int
    seed: int
    successes_a: int
    successes_b: int
    diff: float
    ci_low: float
    ci_high: float
    z: float
    p_value: float
    passed: bool


def run_aa(
    n_per_arm: int,
    seed: int,
    true_rate: float = DEFAULT_TRUE_RATE,
    injected_lift: float = 0.0,
    alpha: float = 0.05,
) -> AAResult:
    """Draw two arms at the same rate and ask the report's own machinery for a verdict."""
    if n_per_arm < 1:
        raise ValueError(f"n_per_arm must be >= 1, got {n_per_arm}")
    if not 0.0 < true_rate < 1.0:
        raise ValueError(f"true_rate must be strictly between 0 and 1, got {true_rate}")
    if injected_lift < 0.0:
        raise ValueError(
            f"injected_lift must be >= 0, got {injected_lift}. Negative injection would "
            "make the A/A fail in the wrong direction; if that is ever wanted, say so "
            "explicitly rather than passing a negative here."
        )

    rng = random.Random(seed)

    # Arm A is drawn first and is untouched by the injection, and each arm consumes
    # exactly n_per_arm draws regardless of rate -- so injecting lift moves the
    # rate and nothing else. A different number of draws would reshuffle arm B and
    # the check would be comparing a different sample as well as a different rate.
    successes_a = sum(rng.random() < true_rate for _ in range(n_per_arm))
    rate_b = min(1.0, true_rate + injected_lift)
    successes_b = sum(rng.random() < rate_b for _ in range(n_per_arm))

    z, p = two_proportion_z_test(successes_a, n_per_arm, successes_b, n_per_arm)
    lo, hi = newcombe_diff_interval(successes_a, n_per_arm, successes_b, n_per_arm, alpha)

    return AAResult(
        n_per_arm=n_per_arm,
        seed=seed,
        successes_a=successes_a,
        successes_b=successes_b,
        diff=successes_b / n_per_arm - successes_a / n_per_arm,
        ci_low=lo,
        ci_high=hi,
        z=z,
        p_value=p,
        passed=p > alpha,
    )


def run_preregistered() -> AAResult:
    """The A/A exactly as pre-registered. No parameters, deliberately.

    Taking no arguments is the point: there is no seed to pass, so there is no
    seed to try again.
    """
    return run_aa(n_per_arm=AA_N_PER_ARM, seed=AA_SEED)
