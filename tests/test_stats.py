import random

import pytest

from recoup.eval.stats import (
    bootstrap_mean_diff_interval,
    newcombe_diff_interval,
    two_proportion_z_test,
    wilson_interval,
)

# --- Wilson --------------------------------------------------------------------


def test_wilson_matches_a_known_published_value():
    # 5 successes in 10 trials, 95% CI -> approximately (0.2366, 0.7634)
    lo, hi = wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=0.001)
    assert hi == pytest.approx(0.7634, abs=0.001)


def test_wilson_stays_in_bounds_at_the_extremes():
    """Where the normal approximation produces impossible intervals."""
    lo, hi = wilson_interval(0, 20)
    assert lo == 0.0
    assert 0.0 < hi < 1.0

    lo, hi = wilson_interval(20, 20)
    assert 0.0 < lo < 1.0
    assert hi == 1.0


def test_wilson_of_an_empty_sample_is_the_whole_interval():
    # No data means no information, and (0, 1) says exactly that.
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_narrows_as_n_grows():
    narrow = wilson_interval(500, 1000)
    wide = wilson_interval(5, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_wilson_contains_the_point_estimate():
    for s, n in [(0, 10), (1, 10), (5, 10), (9, 10), (10, 10), (137, 1000)]:
        lo, hi = wilson_interval(s, n)
        assert lo <= s / n <= hi


def test_a_higher_confidence_level_gives_a_wider_interval():
    ci95 = wilson_interval(500, 1000, alpha=0.05)
    ci99 = wilson_interval(500, 1000, alpha=0.01)
    assert (ci99[1] - ci99[0]) > (ci95[1] - ci95[0])


def test_wilson_actually_covers_at_the_stated_rate():
    """The only real test of an interval method is coverage.

    Matching one published pair proves the arithmetic was copied correctly. It
    says nothing about whether the interval does what it claims. This repeatedly
    draws from a known p and counts how often the interval contains it.

    Wilson is slightly conservative by design, so >= 0.93 at nominal 0.95 with
    n=50 is the expected behaviour, not a loose threshold.
    """
    rng = random.Random(12345)
    p_true, n, trials = 0.30, 50, 3000
    covered = 0
    for _ in range(trials):
        successes = sum(rng.random() < p_true for _ in range(n))
        lo, hi = wilson_interval(successes, n)
        covered += lo <= p_true <= hi
    assert 0.93 <= covered / trials <= 0.99, covered / trials


# --- inputs that must not be guessed --------------------------------------------


def test_more_successes_than_trials_is_refused():
    # p = 1.5 is not a probability. Real counts come from replay, where this
    # would mean a subscription recovered more times than it was attempted.
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(15, 10)


def test_negative_counts_are_refused():
    with pytest.raises(ValueError):
        wilson_interval(-1, 10)
    with pytest.raises(ValueError):
        wilson_interval(5, -10)


# --- Newcombe --------------------------------------------------------------------


def test_newcombe_interval_contains_the_observed_difference():
    lo, hi = newcombe_diff_interval(510, 1000, 570, 1000)
    observed = 0.570 - 0.510
    assert lo < observed < hi


def test_newcombe_interval_includes_zero_when_arms_are_identical():
    lo, hi = newcombe_diff_interval(500, 1000, 500, 1000)
    assert lo < 0 < hi


def test_newcombe_excludes_zero_for_a_large_clear_difference():
    lo, hi = newcombe_diff_interval(300, 1000, 700, 1000)
    assert lo > 0


def test_newcombe_flips_sign_when_the_arms_swap():
    lo, hi = newcombe_diff_interval(300, 1000, 700, 1000)
    rlo, rhi = newcombe_diff_interval(700, 1000, 300, 1000)
    assert rlo == pytest.approx(-hi)
    assert rhi == pytest.approx(-lo)


def test_newcombe_stays_within_minus_one_and_one():
    for s1, n1, s2, n2 in [(0, 10, 10, 10), (10, 10, 0, 10), (0, 1, 1, 1)]:
        lo, hi = newcombe_diff_interval(s1, n1, s2, n2)
        assert -1.0 <= lo <= hi <= 1.0


def test_newcombe_refuses_an_empty_arm():
    # An arm with no subscriptions is a broken run, not a zero effect.
    with pytest.raises(ValueError, match="n1"):
        newcombe_diff_interval(0, 0, 5, 10)


def test_newcombe_actually_covers_at_the_stated_rate():
    rng = random.Random(999)
    p1, p2, n, trials = 0.20, 0.26, 200, 1500
    true_diff = p2 - p1
    covered = 0
    for _ in range(trials):
        s1 = sum(rng.random() < p1 for _ in range(n))
        s2 = sum(rng.random() < p2 for _ in range(n))
        lo, hi = newcombe_diff_interval(s1, n, s2, n)
        covered += lo <= true_diff <= hi
    assert 0.93 <= covered / trials <= 0.995, covered / trials


# --- bootstrap ---------------------------------------------------------------------


def test_bootstrap_interval_brackets_a_known_mean_difference():
    a = [100] * 500
    b = [200] * 500
    lo, hi = bootstrap_mean_diff_interval(a, b, iterations=2000, seed=1)
    assert lo <= 100 <= hi


def test_bootstrap_is_deterministic_given_a_seed():
    a = list(range(100))
    b = list(range(50, 150))
    first = bootstrap_mean_diff_interval(a, b, iterations=500, seed=7)
    second = bootstrap_mean_diff_interval(a, b, iterations=500, seed=7)
    assert first == second


def test_bootstrap_handles_skew_without_going_negative_on_a_positive_quantity():
    """Recovered amounts are right-skewed; this is why we bootstrap.

    This is the real input shape: one row per subscription, mostly zero, a few
    large. It is what `replay()` produces for `recovered_paise`.
    """
    a = [0] * 900 + [500000] * 100
    b = [0] * 850 + [500000] * 150
    lo, hi = bootstrap_mean_diff_interval(a, b, iterations=2000, seed=3)
    assert hi > lo
    assert lo <= (sum(b) / len(b) - sum(a) / len(a)) <= hi


def test_bootstrap_widens_with_less_data():
    rng = random.Random(4)
    big_a = [rng.choice([0, 499900]) for _ in range(800)]
    big_b = [rng.choice([0, 499900]) for _ in range(800)]
    lo_b, hi_b = bootstrap_mean_diff_interval(big_a, big_b, iterations=1500, seed=5)
    lo_s, hi_s = bootstrap_mean_diff_interval(big_a[:40], big_b[:40], iterations=1500, seed=5)
    assert (hi_s - lo_s) > (hi_b - lo_b)


def test_bootstrap_refuses_an_empty_sample():
    """Returning (0.0, 0.0) here would be the strongest possible claim from no data.

    A zero-width interval centred on zero asserts "the difference is exactly
    zero, with certainty". From an empty arm. That is precisely backwards, and it
    would be rendered into a report as a confident null result.
    """
    with pytest.raises(ValueError, match="empty"):
        bootstrap_mean_diff_interval([], [1, 2, 3])
    with pytest.raises(ValueError, match="empty"):
        bootstrap_mean_diff_interval([1, 2, 3], [])


def test_a_higher_confidence_level_widens_the_bootstrap_interval():
    rng = random.Random(6)
    a = [rng.choice([0, 0, 0, 499900]) for _ in range(300)]
    b = [rng.choice([0, 0, 499900]) for _ in range(300)]
    ci95 = bootstrap_mean_diff_interval(a, b, iterations=2000, seed=8, alpha=0.05)
    ci99 = bootstrap_mean_diff_interval(a, b, iterations=2000, seed=8, alpha=0.01)
    assert (ci99[1] - ci99[0]) > (ci95[1] - ci95[0])


# --- z test -------------------------------------------------------------------------


def test_z_test_finds_no_significance_for_identical_arms():
    z, p = two_proportion_z_test(500, 1000, 500, 1000)
    assert abs(z) < 1e-9
    assert p > 0.99


def test_z_test_finds_significance_for_a_large_difference():
    z, p = two_proportion_z_test(300, 1000, 700, 1000)
    assert p < 0.001


def test_z_test_agrees_with_newcombe_about_whether_zero_is_excluded():
    # Two independent routes to the same qualitative answer. If they disagree,
    # one of them is wrong and the report would quote whichever was asked first.
    for s1, n1, s2, n2 in [
        (500, 1000, 500, 1000),
        (300, 1000, 700, 1000),
        (510, 1000, 570, 1000),
        (200, 500, 210, 500),
    ]:
        lo, hi = newcombe_diff_interval(s1, n1, s2, n2)
        _, p = two_proportion_z_test(s1, n1, s2, n2)
        excludes_zero = lo > 0 or hi < 0
        assert excludes_zero == (p < 0.05), (s1, n1, s2, n2, lo, hi, p)


def test_z_test_refuses_an_empty_arm():
    with pytest.raises(ValueError):
        two_proportion_z_test(0, 0, 5, 10)


def test_z_of_a_known_two_proportion_case():
    # p1 = 0.10, p2 = 0.20, n = 100 each. Pooled p = 0.15,
    # se = sqrt(0.15 * 0.85 * (1/100 + 1/100)) = 0.050497...
    # z = 0.10 / 0.050497 = 1.98031...
    z, p = two_proportion_z_test(10, 100, 20, 100)
    assert z == pytest.approx(1.98031, abs=1e-4)
    assert p == pytest.approx(0.04767, abs=1e-4)
