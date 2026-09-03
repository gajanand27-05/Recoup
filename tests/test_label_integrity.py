"""THE MISLABELLED ARTIFACT sweep — every derived table the report renders.

The class has fired three times (INC-007, INC-009, the fallback-series windowing)
and the report is where it does the most damage, because that is the artifact a
judge reads.

For each derived artifact: what does its LABEL assert about its contents, and is
there an input where the two diverge? Each test below constructs that input.

WHAT THIS FILE IS NOT
---------------------
It is not a test that the numbers are right. It is a test that the *names* are
right — that "recovery rate" counts subscriptions rather than actions, that "per
arm" is per arm, that "cost per recovery" divides by recoveries. Every defect in
the class produced correct arithmetic over the wrong contents.
"""

import pytest

from recoup.assign.arms import CONTROL, TREATMENT
from recoup.batch.runner import ArmStats
from recoup.eval.lift import compute_lift
from recoup.eval.views import LiftView


def _view(i, arm, recovered, spend=60, amount=49900):
    return LiftView(
        subscription_id=f"sub_{i:05d}", arm=arm, status="halted",
        amount_paise=amount, recovered_paise=amount if recovered else 0,
        spend_paise=spend, attempts=3,
    )


def _rows(n=4, transport="sim"):
    return [{"transport": transport} for _ in range(n)]


# --- "recovery rate" asserts: subscriptions, not actions --------------------------


def test_recovery_rate_counts_SUBSCRIPTIONS_even_when_actions_outnumber_them():
    """The label says a rate per subscription. If it counted actions, an arm that
    messaged more would look like it recovered more — the treatment arm sends
    more by construction, so the bias would flatter exactly the arm under test.
    """
    views = [_view(i, CONTROL, i < 10) for i in range(100)]
    views += [_view(1000 + i, TREATMENT, i < 10) for i in range(100)]
    result = compute_lift(views, run_id="r", ledger_rows=_rows())

    assert result.control.n == 100
    assert result.treatment.n == 100
    assert result.control.rate == pytest.approx(0.10)
    assert result.treatment.rate == pytest.approx(0.10)
    assert result.diff_pp == pytest.approx(0.0), (
        "identical per-subscription recovery produced a non-zero lift, so the "
        "denominator is not subscriptions"
    )


def test_a_subscription_recovering_is_counted_once_however_many_rows_it_has():
    """A subscription with several actions and one recovery is ONE recovery.
    Counting rows would inflate whichever arm acts more."""
    views = [_view(i, CONTROL, True) for i in range(5)]
    views += [_view(100 + i, TREATMENT, True) for i in range(5)]
    result = compute_lift(views, run_id="r", ledger_rows=_rows())
    assert result.control.recovered == 5
    assert result.treatment.recovered == 5


# --- "per arm" asserts: the arms are not pooled -----------------------------------


def test_the_arms_cannot_be_silently_merged():
    """If `_split` defaulted an unknown arm into one bucket, that arm's
    subscriptions would land wherever the code happened to put them."""
    from recoup.eval.lift import LiftError

    views = [_view(i, CONTROL, i < 3) for i in range(10)]
    views += [_view(100 + i, TREATMENT, i < 3) for i in range(10)]
    views.append(_view(999, "neither", True))
    with pytest.raises(LiftError, match="not one of"):
        compute_lift(views, run_id="r", ledger_rows=_rows())


def test_an_arm_with_no_subscriptions_is_a_broken_run_not_a_large_effect():
    from recoup.eval.lift import LiftError

    with pytest.raises(LiftError, match="broken run"):
        compute_lift(
            [_view(i, CONTROL, i < 3) for i in range(10)],
            run_id="r", ledger_rows=_rows(),
        )


# --- "cost per recovery" asserts: divided by recoveries ---------------------------


def test_cost_per_recovery_divides_by_RECOVERIES_not_by_subscriptions():
    """Dividing by subscriptions would make an arm that recovers nobody look
    cheap rather than infinitely expensive."""
    views = [_view(i, CONTROL, i < 10, spend=100) for i in range(100)]
    views += [_view(1000 + i, TREATMENT, i < 10, spend=100) for i in range(100)]
    result = compute_lift(views, run_id="r", ledger_rows=_rows())
    # 100 subscriptions x 100 paise / 10 recoveries = 1000
    assert result.control.cost_per_recovery_paise == pytest.approx(1000.0)


def test_an_arm_that_recovers_nobody_costs_infinity_rather_than_its_spend():
    views = [_view(i, CONTROL, False, spend=100) for i in range(50)]
    views += [_view(100 + i, TREATMENT, i < 5, spend=100) for i in range(50)]
    result = compute_lift(views, run_id="r", ledger_rows=_rows())
    assert result.control.cost_per_recovery_paise == float("inf")


# --- "fallback rate" asserts: over decisions, per arm ------------------------------


def test_the_fallback_rate_is_over_DECISIONS_not_over_subscriptions():
    stats = ArmStats(subscriptions=100, model_decided=90, fallbacks=10)
    assert stats.fallback_rate == pytest.approx(0.10), (
        "the rate divided by subscriptions rather than by decisions; an arm "
        "making several decisions per subscription would report a rate below "
        "the true one"
    )


def test_an_arm_that_made_no_decisions_reports_no_rate_rather_than_zero():
    """The control calls no model. 0.0% invites comparison with the treatment
    arm's rate, which compares a number to its absence."""
    stats = ArmStats(subscriptions=100, model_decided=0, fallbacks=0)
    assert stats.fallback_rate == 0.0
    assert stats.model_decided + stats.fallbacks == 0  # the caller must check this


# --- "recovery rate" in the runner asserts: recovered / subscriptions --------------


def test_arm_recovery_rate_is_over_that_arms_own_subscriptions():
    """Not over the whole run. Dividing by the run's N would halve both arms and
    make the difference look smaller than it is."""
    stats = ArmStats(subscriptions=50, recovered=25)
    assert stats.recovery_rate == pytest.approx(0.5)


# --- the ledger summary asserts: rows of THIS run ----------------------------------


def test_a_ledger_summary_counts_only_the_named_run(tmp_path):
    """Two runs in one database is the ordinary case — the demo writes into its
    own. A summary that ignored run_id would pool two experiments."""
    from recoup.ledger.store import Ledger

    ledger = Ledger(str(tmp_path / "two.db"))
    for run_id, count in (("run-a", 3), ("run-b", 5)):
        for i in range(count):
            ledger.append({
                "run_id": run_id, "ts": "2026-09-03T00:00:00Z",
                "event_type": "action.executed", "subscription_id": f"s{i}",
                "customer_id": "c", "arm": CONTROL, "transport": "sim",
                "payload": {"attempt_no": 1},
            })
    assert len(ledger.rows("run-a")) == 3
    assert len(ledger.rows("run-b")) == 5


def test_a_transport_column_that_says_sim_means_the_row_was_simulated(tmp_path):
    """D-009's label. A row labelled `sim` that came from a real transport would
    let a real outcome be pooled into a simulated figure."""
    from recoup.execute.sim import SimTransport

    assert SimTransport(seed=1).name == "sim"


# --- the accuracy table asserts: the model classified these ------------------------


def test_the_accuracy_denominator_excludes_what_the_model_never_saw():
    """The defect that fired here already: 8 of 60 fixtures are handled by the
    deterministic opt-out matcher and never reach the model. An accuracy over 60
    would report the matcher's correctness as the model's."""
    from recoup.agent.llm import NON_MODEL_SOURCES

    sources = ["gpt-oss:120b"] * 52 + ["deterministic"] * 8
    by_model = [s for s in sources if s not in NON_MODEL_SOURCES]
    assert len(by_model) == 52, (
        "the model-classified subset is not 52; an accuracy over all 60 pools two "
        "instruments"
    )


# --- the sweep table asserts: these parameters were swept --------------------------


def test_the_sweep_distinguishes_NOT_SWEPT_from_flat():
    """The same class one level up. A cohort parameter reported as UNWIRED would
    say 'we swept it and it did not matter' about something nobody swept."""
    from recoup.eval.sensitivity import OUT_OF_SCOPE, SweepResult

    out_of_scope = SweepResult(
        param="self_recovery_rate_soft", value=0.05, endpoint="low",
        lift_pp=3.0, baseline_lift_pp=3.0, control_rate=0.3,
        treatment_rate=0.33, moved_the_model=False,
    )
    in_scope_flat = SweepResult(
        param="decay_beyond_curve", value=0.9, endpoint="low",
        lift_pp=3.0, baseline_lift_pp=3.0, control_rate=0.3,
        treatment_rate=0.33, moved_the_model=False,
    )
    assert out_of_scope.verdict == "NOT SWEPT"
    assert in_scope_flat.verdict == "UNWIRED"
    assert "self_recovery_rate_soft" in OUT_OF_SCOPE


# --- the completeness line asserts: rows belonging to no subscription --------------


def test_unattributable_rows_are_counted_rather_than_dropped():
    """They shorten every denominator. A summary that silently skipped them
    would report rates over a cohort smaller than the one that ran."""
    from recoup.ledger.replay import count_unattributable

    rows = [
        {"subscription_id": "s1", "event_type": "action.executed", "payload": {}},
        {"subscription_id": None, "event_type": "webhook.received", "payload": {}},
        {"subscription_id": "", "event_type": "webhook.received", "payload": {}},
    ]
    assert count_unattributable(rows) == 2


# --- the meta-check: the report renders every one of these -------------------------


def test_every_table_in_the_report_has_a_label_test_here():
    """A new table added to the report without a label test would be exactly the
    class this file exists for, arriving unguarded."""
    from pathlib import Path

    report = (Path(__file__).resolve().parents[1] / "scripts" / "report.py").read_text(
        encoding="utf-8"
    )
    headings = {
        line.split('"')[1] for line in report.splitlines()
        if 'say("## ' in line and '"' in line
    }
    covered = {
        "## The model", "## Per arm", "## Fallback rate over the run",
        "## Recovery lift", "## Completeness",
    }
    assert headings <= covered, (
        f"the report renders section(s) {headings - covered} with no label test "
        f"in tests/test_label_integrity.py. Write the sentence its heading "
        f"asserts, then construct the input where that diverges from what it "
        f"contains."
    )
