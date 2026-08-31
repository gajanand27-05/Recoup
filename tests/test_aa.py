import re
from pathlib import Path

import pytest

from recoup.eval.aa import AA_N_PER_ARM, AA_SEED, AAResult, run_aa
from recoup.eval.power import BASELINE_P1

EXPERIMENT = Path(__file__).resolve().parents[1] / "EXPERIMENT.md"


# --- the pre-registered parameters ------------------------------------------------


def test_the_code_uses_the_seed_pre_registered_in_experiment_md():
    """EXPERIMENT.md is authoritative; the constants must match it.

    The pre-registration is only worth its git timestamp if the code actually
    runs what was registered. A seed quietly changed afterwards would leave a
    file claiming one thing and a result produced by another.
    """
    text = EXPERIMENT.read_text(encoding="utf-8")
    seed = int(re.search(r"\*\*Seed\*\*\s*\|\s*\*\*(\d+)\*\*", text).group(1))
    n = int(re.search(r"\*\*N per arm\*\*\s*\|\s*\*\*([\d,]+)\*\*", text).group(1).replace(",", ""))
    assert AA_SEED == seed
    assert AA_N_PER_ARM == n


def test_the_baseline_rate_comes_from_the_frozen_registry():
    # Same property as the power calculation: not typed, so it cannot drift from
    # the sourced figure that PARAMS.lock.json covers.
    from recoup.eval import aa

    assert aa.DEFAULT_TRUE_RATE == BASELINE_P1 == 0.51


# --- the A/A itself ----------------------------------------------------------------


def test_an_aa_test_finds_no_significant_difference():
    """The whole point: feed the harness no lift, it must report none."""
    result = run_aa(n_per_arm=1000, seed=42)
    assert result.p_value > 0.05
    assert result.passed is True


def test_the_aa_confidence_interval_contains_zero():
    result = run_aa(n_per_arm=1000, seed=42)
    assert result.ci_low < 0 < result.ci_high


def test_aa_is_deterministic_given_a_seed():
    assert run_aa(1000, seed=7) == run_aa(1000, seed=7)


def test_aa_passes_across_many_seeds():
    """At alpha=0.05 we expect ~1 in 20 false positives, so allow a couple."""
    failures = sum(0 if run_aa(500, seed=s).passed else 1 for s in range(20))
    assert failures <= 3


def test_a_deliberately_biased_harness_is_caught():
    """Sanity check on the check: inject real lift, the A/A must fail.

    A check that cannot fail is not a check. This is the planted failure for the
    A/A itself, kept as a permanent test rather than run once and discarded.
    """
    result = run_aa(n_per_arm=1000, seed=42, injected_lift=0.15)
    assert result.passed is False
    assert result.p_value < 0.05


def test_a_small_injected_lift_is_below_the_aa_detection_threshold():
    """The A/A's own power is 6.23pp. It cannot see a 2pp bias, and does not claim to.

    This is the property EXPERIMENT.md states: a passing A/A rules out harness bias
    LARGER than about six percentage points. It does not establish that the harness
    is unbiased. Pinned so nobody later reads a pass as the stronger claim.
    """
    result = run_aa(n_per_arm=AA_N_PER_ARM, seed=AA_SEED, injected_lift=0.02)
    assert result.passed is True, "a 2pp bias is expected to slip through -- that is the point"


def test_injected_lift_does_not_change_the_number_of_random_draws():
    """Common random numbers: the injection must move the rate, not the stream.

    If injecting lift also reshuffled the draws, the biased run and the clean run
    would differ for two reasons at once and the check would be testing a
    different sample rather than a different rate.
    """
    clean = run_aa(500, seed=11, injected_lift=0.0)
    biased = run_aa(500, seed=11, injected_lift=0.15)
    assert clean.successes_a == biased.successes_a, (
        "arm A is untouched by the injection, so it must be identical"
    )
    assert biased.successes_b > clean.successes_b


# --- inputs -------------------------------------------------------------------------


def test_a_non_positive_n_is_refused():
    with pytest.raises(ValueError, match="n_per_arm"):
        run_aa(0, seed=1)


def test_a_rate_outside_zero_to_one_is_refused():
    with pytest.raises(ValueError, match="true_rate"):
        run_aa(100, seed=1, true_rate=1.5)


def test_a_negative_injected_lift_is_refused():
    # Injecting negative lift would make the A/A "fail" in the wrong direction and
    # is never what is wanted; if it is ever needed, say so explicitly.
    with pytest.raises(ValueError, match="injected_lift"):
        run_aa(100, seed=1, injected_lift=-0.1)


# --- the result carries what an incident report would need ----------------------------


# --- the pre-registered run, and its recorded result ---------------------------------


def test_the_preregistered_aa_passes():
    """The actual A/A, run exactly as declared in EXPERIMENT.md.

    If this ever goes red, the harness manufactures lift and every number the
    project produces is void. The response is an INCIDENTS entry and an
    investigation -- NOT a new seed. See EXPERIMENT.md.
    """
    from recoup.eval.aa import run_preregistered

    result = run_preregistered()
    assert result.passed, (
        f"PRE-REGISTERED A/A FAILED: seed={result.seed} p={result.p_value:.4f} "
        f"diff={result.diff * 100:+.2f}pp. Do not re-run with a new seed. Record it "
        "in INCIDENTS.md and investigate the harness."
    )
    assert result.ci_low < 0 < result.ci_high


def test_the_preregistered_aa_result_is_pinned():
    """The result itself, recorded in the repository rather than in prose.

    Anyone can re-run `pytest` and get the same numbers. A result that lives only
    in a summary is a claim; a result pinned here is reproducible by a stranger.

    Run once, on 2026-08-31, with the seed declared in EXPERIMENT.md before the
    run. These numbers were not chosen.
    """
    from recoup.eval.aa import run_preregistered

    r = run_preregistered()
    assert (r.successes_a, r.successes_b) == (513, 510)
    assert r.diff == pytest.approx(-0.003, abs=1e-9)
    assert r.p_value == pytest.approx(0.8932, abs=5e-5)
    assert (r.ci_low, r.ci_high) == pytest.approx((-0.04674, 0.04074), abs=5e-5)


def test_the_result_records_everything_needed_to_reproduce_a_failure():
    """If the A/A fails it becomes an INCIDENTS entry, not a retry.

    That entry needs the seed and the observed p-value, so the result object has
    to carry them rather than leaving someone to reconstruct the run.
    """
    r = run_aa(n_per_arm=200, seed=99)
    assert isinstance(r, AAResult)
    for field in ("seed", "n_per_arm", "successes_a", "successes_b", "p_value", "z", "diff"):
        assert getattr(r, field) is not None, field
    assert r.seed == 99
