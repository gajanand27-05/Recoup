"""The reported effect. This module may NEVER see who would have recovered anyway.

THE FIREWALL
------------
`would_self_recover` is the simulator's ground-truth counterfactual. If the code
that computes lift can read it, it can condition on it — deliberately or by
accident — and the number becomes self-fulfilling. So this module is forbidden by
IMPORT STRUCTURE from reaching it: `tests/test_firewall.py` walks the transitive
import closure of `recoup.eval.lift` and fails if `recoup.simulator.generator` or
`recoup.eval.diagnostics` appears anywhere in it.

That is why this file imports `LiftView` and nothing that could carry a label,
and why it takes views rather than states. A `SubscriptionState` has the label
attached; a `LiftView` is the projection that does not.

WHAT IT COMPUTES, AND WITH WHAT UNCERTAINTY
--------------------------------------------
* recovery rate per arm, Wilson intervals
* the difference, Newcombe interval — not two Wilson intervals eyeballed for
  overlap, which is a different and wrong test
* a two-proportion z test
* recovered amount per arm, bootstrap interval — money is skewed and a normal
  interval on a mean of it is not defensible

Every figure comes back as a `Figure` from `provenance_gate`, so a number
computed over stub output cannot be rendered (A-023). Arithmetic launders
provenance; `combined_with` is what stops it.
"""

from dataclasses import dataclass

from recoup.eval.provenance_gate import SIMULATED, Figure
from recoup.eval.stats import (
    bootstrap_mean_diff_interval,
    newcombe_diff_interval,
    two_proportion_z_test,
    wilson_interval,
)
from recoup.eval.transport_split import require_declared_split
from recoup.eval.views import LiftView

CONTROL = "control"
TREATMENT = "treatment"


class LiftError(RuntimeError):
    """The comparison cannot be made as asked."""


@dataclass(frozen=True)
class ArmOutcome:
    arm: str
    n: int
    recovered: int
    recovered_paise: int
    spend_paise: int

    @property
    def rate(self) -> float:
        return self.recovered / self.n if self.n else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.recovered, self.n)

    @property
    def cost_per_recovery_paise(self) -> float:
        return self.spend_paise / self.recovered if self.recovered else float("inf")


@dataclass(frozen=True)
class LiftResult:
    control: ArmOutcome
    treatment: ArmOutcome
    diff_pp: float
    diff_ci_pp: tuple[float, float]
    p_value: float
    money_diff_paise: float
    money_ci_paise: tuple[float, float]
    figures: tuple

    @property
    def is_significant(self) -> bool:
        low, high = self.diff_ci_pp
        return low > 0 or high < 0

    def describe(self) -> str:
        c, t = self.control, self.treatment
        lines = [
            f"control   n={c.n:>5}  recovered={c.recovered:>5}  "
            f"rate={c.rate:6.2%}  CI [{c.interval[0]:.2%}, {c.interval[1]:.2%}]",
            f"treatment n={t.n:>5}  recovered={t.recovered:>5}  "
            f"rate={t.rate:6.2%}  CI [{t.interval[0]:.2%}, {t.interval[1]:.2%}]",
            "",
            f"difference {self.diff_pp:+.2f} pp   "
            f"95% CI [{self.diff_ci_pp[0]:+.2f}, {self.diff_ci_pp[1]:+.2f}] pp   "
            f"p = {self.p_value:.4f}",
            f"significant at 5%: {self.is_significant}",
        ]
        if not self.is_significant:
            lines.append(
                "  The interval spans zero. This run does not distinguish the "
                "agent from the control."
            )
        return "\n".join(lines)


def _split(views) -> dict[str, list[LiftView]]:
    arms: dict[str, list[LiftView]] = {CONTROL: [], TREATMENT: []}
    for view in views:
        if view.arm not in arms:
            raise LiftError(
                f"subscription {view.subscription_id!r} has arm {view.arm!r}, which "
                f"is not one of {sorted(arms)}. An unassigned subscription cannot "
                f"enter a comparison — including it would put it in whichever arm "
                f"the code happened to default to."
            )
        arms[view.arm].append(view)
    return arms


def _outcome(arm: str, views: list[LiftView]) -> ArmOutcome:
    return ArmOutcome(
        arm=arm,
        n=len(views),
        recovered=sum(1 for v in views if v.recovered_paise > 0),
        recovered_paise=sum(v.recovered_paise for v in views),
        spend_paise=sum(v.spend_paise for v in views),
    )


def compute_lift(
    views,
    *,
    run_id: str,
    ledger_rows: list[dict],
    provenance: frozenset = frozenset({SIMULATED}),
    bootstrap_iterations: int = 10_000,
    seed: int = 20260902,
) -> LiftResult:
    """The reported effect, with its uncertainty and its provenance attached.

    `ledger_rows` is REQUIRED and its transport split is checked before anything
    is computed.
    Filtering rows by transport is not enough: with `sim` as the default the
    split is usually trivially empty, and a correct filter then yields one silent
    pooled number that looks identical to a properly-split one. Raising is the
    point (D-009).
    """
    require_declared_split(ledger_rows, run_id=run_id)

    arms = _split(views)
    control = _outcome(CONTROL, arms[CONTROL])
    treatment = _outcome(TREATMENT, arms[TREATMENT])

    for outcome in (control, treatment):
        if outcome.n == 0:
            raise LiftError(
                f"arm {outcome.arm!r} has no subscriptions. A lift figure needs "
                f"both arms; one empty arm is not a large effect, it is a broken run."
            )

    # ARGUMENT ORDER IS THE SIGN OF THE HEADLINE NUMBER.
    # `newcombe_diff_interval(s1, n1, s2, n2)` returns the CI for (p2 - p1), so
    # CONTROL goes first to get (treatment - control). Passing treatment first
    # computes control - treatment: a correct interval around the wrong quantity,
    # which reads as the agent losing by exactly the amount it won by. Caught by
    # reading the signature rather than by the result looking odd — at these
    # magnitudes a sign flip does not look odd.
    low, high = newcombe_diff_interval(
        control.recovered, control.n, treatment.recovered, treatment.n
    )
    _, p_value = two_proportion_z_test(
        control.recovered, control.n, treatment.recovered, treatment.n
    )
    money_low, money_high, money_diff = _money(arms, bootstrap_iterations, seed)

    control_fig = Figure(
        name="control_recovery_rate", value=control.rate, unit="",
        sources=provenance,
    )
    treatment_fig = Figure(
        name="treatment_recovery_rate", value=treatment.rate, unit="",
        sources=provenance,
    )
    lift_fig = control_fig.combined_with(
        treatment_fig,
        name="recovery_lift",
        value=(treatment.rate - control.rate) * 100,
        unit="pp",
        caveat=(
            "sim transport only; schema violations pull this toward null "
            "(EXPERIMENT.md Addendum 2)"
        ),
    )

    return LiftResult(
        control=control,
        treatment=treatment,
        diff_pp=(treatment.rate - control.rate) * 100,
        diff_ci_pp=(low * 100, high * 100),
        p_value=p_value,
        money_diff_paise=money_diff,
        money_ci_paise=(money_low, money_high),
        figures=(control_fig, treatment_fig, lift_fig),
    )


def _money(arms, iterations: int, seed: int) -> tuple[float, float, float]:
    """Bootstrap on recovered amount. Money is skewed; a normal interval on its
    mean is not defensible, which is why this is a percentile bootstrap."""
    control_amounts = [float(v.recovered_paise) for v in arms[CONTROL]]
    treatment_amounts = [float(v.recovered_paise) for v in arms[TREATMENT]]
    # Same trap as above: `bootstrap_mean_diff_interval(a, b)` returns
    # mean(b) - mean(a), so control is `a`.
    low, high = bootstrap_mean_diff_interval(
        control_amounts, treatment_amounts, iterations=iterations, seed=seed
    )
    diff = (
        sum(treatment_amounts) / len(treatment_amounts)
        - sum(control_amounts) / len(control_amounts)
    )
    return low, high, diff
