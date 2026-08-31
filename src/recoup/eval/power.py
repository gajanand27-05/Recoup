"""Power analysis for the two-proportion design.

    n_arm = (z_{alpha/2} + z_beta)^2 * [p1(1-p1) + p2(1-p2)] / (p2 - p1)^2

**This is code and not a table in a document.** The spec's MDE figures are
illustrative; what goes in the report is computed, so that if `p1` moves the
number moves with it (A-001). A hand-typed design table is exactly how an
illustrative figure becomes a wrong claim in a submitted document.

The baseline is read from the **frozen** simulator registry rather than typed
here, so the number in the power calculation is provably the sourced one and is
covered by `PARAMS.lock.json`.

`statistics.NormalDist` rather than scipy, for the same reason as `stats.py`: the
quantiles agree to machine precision, and a reproducibility claim should not
depend on a matching scipy build.
"""

import math
from statistics import NormalDist

from recoup.simulator.curve import PARAMS as _SIM_PARAMS

_NORMAL = NormalDist()

# MEASURED. Stripe Smart Retries alone, Churnkey 5.4M failures. Read from the
# frozen registry -- see simulator/PARAMS.md -- so it cannot drift from its source.
BASELINE_P1: float = _SIM_PARAMS["baseline_recovery_rate"]["value"]

# SELF_IMPOSED, and conventional rather than derived. alpha = 0.05 and
# power = 0.80 are the standard defaults in applied trial design; neither is
# implied by anything about this problem. They are pre-registered in
# EXPERIMENT.md before the batch runs, which is what stops them being chosen
# afterwards to suit the result.
DEFAULT_ALPHA: float = 0.05
DEFAULT_POWER: float = 0.80

# The sizes reported in EXPERIMENT.md. 1000/arm is the pre-registered design
# (N = 2,000 across two arms, D-010).
DESIGN_SIZES: tuple[int, ...] = (250, 500, 1000, 2000)


def _validate(p1: float, alpha: float, power: float) -> None:
    if not 0.0 < p1 < 1.0:
        raise ValueError(f"p1 must be strictly between 0 and 1, got {p1}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")
    if not 0.0 < power < 1.0:
        raise ValueError(f"power must be strictly between 0 and 1, got {power}")


def _n_for(p1: float, mde: float, alpha: float, power: float) -> int:
    """The sample-size formula. Private, so `mde_at_n` can call it without the
    `n_per_arm` parameter shadowing the public function of the same name."""
    z_a = _NORMAL.inv_cdf(1 - alpha / 2)
    z_b = _NORMAL.inv_cdf(power)
    p2 = p1 + mde

    numerator = (z_a + z_b) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2))
    return math.ceil(numerator / (mde**2))


def n_per_arm(
    p1: float, mde: float, alpha: float = DEFAULT_ALPHA, power: float = DEFAULT_POWER
) -> int:
    """Subjects per arm needed to detect `mde` at this baseline."""
    _validate(p1, alpha, power)
    if mde <= 0.0:
        raise ValueError(
            f"mde must be > 0, got {mde}; a zero mde divides by zero and a negative "
            "one silently computes a sample size for an effect in the other direction"
        )
    if p1 + mde >= 1.0:
        raise ValueError(
            f"p2 = p1 + mde = {p1 + mde} is not a probability. Clamping it to 1.0 "
            "would answer a different question than the one asked."
        )
    return _n_for(p1, mde, alpha, power)


def mde_at_n(
    p1: float,
    n_per_arm: int,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
) -> float:
    """Smallest detectable difference at this n.

    Solved by bisection because p2 appears on both sides through the variance
    term. The signature keeps `n_per_arm` as the parameter name because Task 22
    calls it by keyword.
    """
    _validate(p1, alpha, power)
    if n_per_arm < 1:
        raise ValueError(f"n_per_arm must be >= 1, got {n_per_arm}")

    lo, hi = 1e-9, 1.0 - p1 - 1e-9
    if hi <= lo:
        raise ValueError(f"no detectable difference exists below p1 = {p1}")

    for _ in range(200):
        mid = (lo + hi) / 2
        if _n_for(p1, mid, alpha, power) > n_per_arm:
            lo = mid
        else:
            hi = mid
    return hi


def design_table(
    sizes: tuple[int, ...] = DESIGN_SIZES,
    p1: float = BASELINE_P1,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
) -> list[dict]:
    """The rows that go into EXPERIMENT.md, computed rather than transcribed."""
    return [
        {
            "n_per_arm": n,
            "total_n": 2 * n,
            "p1": p1,
            "alpha": alpha,
            "power": power,
            "mde": mde_at_n(p1, n, alpha, power),
        }
        for n in sizes
    ]


DESIGN_TABLE_BEGIN = "<!-- BEGIN generated: design-table -->"
DESIGN_TABLE_END = "<!-- END generated: design-table -->"


def design_table_markdown(chosen: int = 1000) -> str:
    """The EXPERIMENT.md table, rendered from the computation.

    Delimited by markers so a test can extract the committed block and compare it
    against a fresh render. Without that, the table silently goes stale the moment
    `p1` moves in the frozen registry -- and `p1` is read from the registry
    precisely so the baseline is provably the sourced one. A hand-typed table
    would quietly break the property the registry lookup exists to provide.
    """
    lines = [
        DESIGN_TABLE_BEGIN,
        f"| N/arm | Total N | MDE at p1 = {BASELINE_P1}, alpha = {DEFAULT_ALPHA}, "
        f"power = {DEFAULT_POWER} |",
        "|---|---|---|",
    ]
    for row in design_table():
        n = row["n_per_arm"]
        mark = "**" if n == chosen else ""
        chose = "  <- chosen" if n == chosen else ""
        lines.append(
            f"| {mark}{n:,}{mark} | {mark}{row['total_n']:,}{mark} | "
            f"{mark}{row['mde'] * 100:.2f} pp{mark}{chose} |"
        )
    lines.append(DESIGN_TABLE_END)
    return "\n".join(lines)


def main() -> int:  # pragma: no cover - convenience entry point
    print(f"p1 = {BASELINE_P1}  alpha = {DEFAULT_ALPHA}  power = {DEFAULT_POWER}")
    for row in design_table():
        print(
            f"  {row['n_per_arm']:5d}/arm (N={row['total_n']:5d})"
            f" -> MDE {row['mde'] * 100:5.2f}pp"
        )
    print()
    print(design_table_markdown())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
