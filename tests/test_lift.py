"""The reported effect — and above all, its SIGN.

A sign error here is the worst available defect: the interval is correct, the
p-value is correct, and the number says the agent lost by exactly the margin it
won by. Nothing looks wrong. Two of the three stats helpers take their arguments
in (baseline, comparison) order and return `second - first`, so passing treatment
first silently inverts the headline.

Caught by reading the signatures rather than by the output looking odd — at these
magnitudes an inverted lift does not look odd.
"""

import pytest

from recoup.agent.llm import DETERMINISTIC
from recoup.eval.lift import CONTROL, TREATMENT, LiftError, compute_lift
from recoup.eval.provenance_gate import SIMULATED, ProvenanceError
from recoup.eval.views import LiftView


def _view(i: int, arm: str, recovered: bool, amount: int = 49900, spend: int = 60):
    return LiftView(
        subscription_id=f"sub_{i:04d}",
        arm=arm,
        status="halted",
        amount_paise=amount,
        recovered_paise=amount if recovered else 0,
        spend_paise=spend,
        attempts=3,
    )


def _rows(n: int = 4, transport: str = "sim"):
    return [{"transport": transport} for _ in range(n)]


def _cohort(control_recovered: int, treatment_recovered: int, per_arm: int = 100):
    views = []
    for i in range(per_arm):
        views.append(_view(i, CONTROL, i < control_recovered))
    for i in range(per_arm):
        views.append(_view(1000 + i, TREATMENT, i < treatment_recovered))
    return views


# --- THE SIGN ------------------------------------------------------------------


def test_a_treatment_arm_that_wins_reports_a_POSITIVE_lift():
    """If this ever flips, every downstream number is wrong in the same way."""
    result = compute_lift(
        _cohort(control_recovered=30, treatment_recovered=45),
        run_id="r", ledger_rows=_rows(),
    )
    assert result.diff_pp > 0, (
        f"treatment recovered 45/100 vs control 30/100 and lift came out "
        f"{result.diff_pp:+.2f} pp — the sign is inverted"
    )
    assert result.diff_pp == pytest.approx(15.0, abs=1e-9)


def test_a_treatment_arm_that_loses_reports_a_NEGATIVE_lift():
    """The direction that must be reportable. A build that can only express
    'the agent won' is not measuring anything."""
    result = compute_lift(
        _cohort(control_recovered=45, treatment_recovered=30),
        run_id="r", ledger_rows=_rows(),
    )
    assert result.diff_pp == pytest.approx(-15.0, abs=1e-9)


def test_the_interval_is_on_the_same_side_as_the_point_estimate():
    """An inverted interval around a correct point estimate is the subtle
    version of the same bug."""
    result = compute_lift(
        _cohort(control_recovered=20, treatment_recovered=60),
        run_id="r", ledger_rows=_rows(),
    )
    low, high = result.diff_ci_pp
    assert low > 0 and high > 0, f"lift {result.diff_pp:+.2f} but CI [{low}, {high}]"
    assert low < result.diff_pp < high


def test_the_money_difference_has_the_same_sign_as_the_rate_difference():
    """Third helper, third chance to invert. `bootstrap_mean_diff_interval(a, b)`
    returns mean(b) - mean(a)."""
    result = compute_lift(
        _cohort(control_recovered=20, treatment_recovered=60),
        run_id="r", ledger_rows=_rows(), bootstrap_iterations=500,
    )
    assert result.money_diff_paise > 0
    assert result.diff_pp > 0
    # The INTERVAL too, not just the point estimate. `money_diff` is computed
    # directly from the two means and so survives an inverted bootstrap call —
    # when the sign plant was run, this test passed while the rate test failed,
    # because it only checked the half that could not be wrong.
    low, high = result.money_ci_paise
    assert low > 0 and high > 0, (
        f"money diff {result.money_diff_paise:+.0f} paise but CI [{low}, {high}] — "
        f"the bootstrap arguments are reversed"
    )
    assert low < result.money_diff_paise < high


def test_no_difference_reports_zero_and_a_straddling_interval():
    result = compute_lift(
        _cohort(control_recovered=40, treatment_recovered=40),
        run_id="r", ledger_rows=_rows(),
    )
    assert result.diff_pp == pytest.approx(0.0, abs=1e-9)
    low, high = result.diff_ci_pp
    assert low < 0 < high
    assert not result.is_significant
    assert "does not distinguish" in result.describe()


# --- the gates ------------------------------------------------------------------


def test_a_mixed_transport_run_is_refused_before_anything_is_computed():
    """D-009. Not filtered — refused."""
    mixed = _rows(3, "sim") + _rows(2, "real")
    with pytest.raises(ValueError) as exc:
        compute_lift(_cohort(30, 45), run_id="r", ledger_rows=mixed)
    assert "pool" in str(exc.value).lower() or "transport" in str(exc.value).lower()


def test_an_empty_ledger_is_refused():
    """Zero rows is not a clean split — it is nothing measured, and the two must
    not produce the same outcome."""
    with pytest.raises(ValueError):
        compute_lift(_cohort(30, 45), run_id="r", ledger_rows=[])


def test_a_subscription_with_an_unknown_arm_is_refused():
    views = _cohort(10, 10, per_arm=10)
    views.append(_view(9999, "somehow_neither", True))
    with pytest.raises(LiftError, match="not one of"):
        compute_lift(views, run_id="r", ledger_rows=_rows())


def test_an_empty_arm_is_a_broken_run_not_a_large_effect():
    views = [_view(i, CONTROL, i < 5) for i in range(20)]
    with pytest.raises(LiftError, match="broken run"):
        compute_lift(views, run_id="r", ledger_rows=_rows())


def test_a_figure_over_fallback_output_cannot_be_produced():
    """A stubbed run completes and yields a plausible lift. The refusal is here."""
    with pytest.raises(ProvenanceError, match="deterministic"):
        compute_lift(
            _cohort(30, 45), run_id="r", ledger_rows=_rows(),
            provenance=frozenset({SIMULATED, DETERMINISTIC}),
        )


def test_the_lift_figure_carries_both_arms_provenance():
    result = compute_lift(_cohort(30, 45), run_id="r", ledger_rows=_rows())
    lift = [f for f in result.figures if f.name == "recovery_lift"][0]
    assert lift.sources == frozenset({SIMULATED})
    assert "toward null" in lift.caveat, (
        "the conservative-bias sentence must travel with the figure "
        "(EXPERIMENT.md Addendum 2)"
    )


# --- arithmetic -----------------------------------------------------------------


def test_cost_per_recovery_is_infinite_rather_than_a_division_error():
    result = compute_lift(
        _cohort(control_recovered=0, treatment_recovered=10),
        run_id="r", ledger_rows=_rows(),
    )
    assert result.control.cost_per_recovery_paise == float("inf")
    assert result.treatment.cost_per_recovery_paise > 0


def test_recovery_rate_counts_subscriptions_not_actions():
    result = compute_lift(
        _cohort(control_recovered=25, treatment_recovered=50),
        run_id="r", ledger_rows=_rows(),
    )
    assert result.control.rate == pytest.approx(0.25)
    assert result.treatment.rate == pytest.approx(0.50)
    assert result.control.n == 100 and result.treatment.n == 100


def test_significance_reads_the_interval_not_the_p_value():
    """Two ways to be wrong that agree most of the time. The interval is what
    the pre-registration commits to."""
    result = compute_lift(
        _cohort(control_recovered=30, treatment_recovered=60),
        run_id="r", ledger_rows=_rows(),
    )
    low, high = result.diff_ci_pp
    assert result.is_significant == (low > 0 or high < 0)
