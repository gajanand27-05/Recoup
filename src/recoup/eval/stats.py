"""Interval estimation.

Rates -> Newcombe-Wilson. It behaves near 0 and 1, where the normal
approximation produces intervals that fall outside [0, 1].

Money -> percentile bootstrap. Recovered-amount distributions are right-skewed
(most subscriptions recover nothing, a few recover a lot), so a
normal-approximation interval on the mean would be wrong in a way that flatters
whichever arm has the fatter tail (D-010).

Newcombe, R.G. (1998), Statistics in Medicine 17:873-890, method 10.

Why `statistics.NormalDist` and not scipy
-----------------------------------------
The normal quantiles here agree with scipy to 8.9e-16 -- machine precision -- so
scipy buys nothing but a version-dependent number in a reproducibility claim.
Someone recomputing the reported figures should need Python and this repository,
not a matching scipy build.

Why these functions raise on empty input
----------------------------------------
An arm with no subscriptions is a broken run, not a zero effect. Returning
`(0.0, 0.0)` from an empty sample would assert "the difference is exactly zero,
with certainty" -- the strongest possible claim, made from no data -- and it
would render into a report as a confident null result. `wilson_interval(0, 0)` is
the deliberate exception: `(0.0, 1.0)` says "no information", which is true.
"""

import math
import random
from statistics import NormalDist

_NORMAL = NormalDist()


def _check_counts(successes: int, n: int, label: str = "") -> None:
    suffix = f" ({label})" if label else ""
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}{suffix}")
    if successes < 0:
        raise ValueError(f"successes must be >= 0, got {successes}{suffix}")
    if successes > n:
        raise ValueError(
            f"successes ({successes}) exceeds trials ({n}){suffix}; that is not a "
            "proportion. Counts come from replay, where this would mean a "
            "subscription recovered more often than it was attempted."
        )


def wilson_interval(successes: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval for a single proportion."""
    _check_counts(successes, n)
    if n == 0:
        return (0.0, 1.0)  # no data, no information -- and the interval says so

    z = _NORMAL.inv_cdf(1 - alpha / 2)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom

    lower = max(0.0, centre - margin)
    upper = min(1.0, centre + margin)

    # At p = 0 the Wilson lower bound is exactly 0, and at p = 1 the upper bound
    # is exactly 1. Floating-point leaves ~1e-17 of residue instead, which is
    # enough to make the interval fail to contain its own point estimate --
    # `lo <= 0.0` is False when lo is 1.4e-17. Pinned to the exact values rather
    # than papered over with a tolerance at every call site.
    if successes == 0:
        lower = 0.0
    if successes == n:
        upper = 1.0
    return (lower, upper)


def newcombe_diff_interval(
    s1: int, n1: int, s2: int, n2: int, alpha: float = 0.05
) -> tuple[float, float]:
    """CI for (p2 - p1) by Newcombe's method 10, composed from Wilson intervals."""
    _check_counts(s1, n1, "arm 1")
    _check_counts(s2, n2, "arm 2")
    if n1 == 0:
        raise ValueError("n1 is 0: an arm with no subscriptions is a broken run")
    if n2 == 0:
        raise ValueError("n2 is 0: an arm with no subscriptions is a broken run")

    l1, u1 = wilson_interval(s1, n1, alpha)
    l2, u2 = wilson_interval(s2, n2, alpha)
    p1 = s1 / n1
    p2 = s2 / n2
    diff = p2 - p1

    lower = diff - math.sqrt((p2 - l2) ** 2 + (u1 - p1) ** 2)
    upper = diff + math.sqrt((u2 - p2) ** 2 + (p1 - l1) ** 2)
    return (max(-1.0, lower), min(1.0, upper))


def bootstrap_mean_diff_interval(
    a: list[int],
    b: list[int],
    iterations: int = 10000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI for mean(b) - mean(a).

    `a` and `b` are one value per subscription -- the shape `replay()` produces
    for `recovered_paise`: mostly zeros with a heavy right tail.

    Uses `random.Random`, whose stream is stable across Python versions, so a
    seeded run is reproducible by anyone with the repository.
    """
    if not a or not b:
        raise ValueError(
            "cannot bootstrap an empty sample; an empty arm is a broken run, not a "
            "zero difference"
        )
    if iterations < 1:
        raise ValueError(f"iterations must be >= 1, got {iterations}")

    rng = random.Random(seed)
    na, nb = len(a), len(b)
    diffs = []
    for _ in range(iterations):
        sa = sum(a[rng.randrange(na)] for _ in range(na)) / na
        sb = sum(b[rng.randrange(nb)] for _ in range(nb)) / nb
        diffs.append(sb - sa)

    diffs.sort()
    lo_idx = int((alpha / 2) * iterations)
    hi_idx = min(int((1 - alpha / 2) * iterations), iterations - 1)
    return (diffs[lo_idx], diffs[hi_idx])


def two_proportion_z_test(s1: int, n1: int, s2: int, n2: int) -> tuple[float, float]:
    """Pooled two-proportion z-test. Returns (z, two-sided p)."""
    _check_counts(s1, n1, "arm 1")
    _check_counts(s2, n2, "arm 2")
    if n1 == 0 or n2 == 0:
        raise ValueError("an arm with no subscriptions is a broken run, not a null result")

    p1, p2 = s1 / n1, s2 / n2
    pooled = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        # Both arms all-success or all-failure: no variance, so no evidence of a
        # difference. p = 1.0 is the weak answer, which is the correct one here.
        return (0.0, 1.0)

    z = (p2 - p1) / se
    p_value = 2 * (1 - _NORMAL.cdf(abs(z)))
    return (z, p_value)
