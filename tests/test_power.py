import pytest

from recoup.eval.power import (
    BASELINE_P1,
    DEFAULT_ALPHA,
    DEFAULT_POWER,
    design_table,
    mde_at_n,
    n_per_arm,
)

# --- the chosen design ----------------------------------------------------------


def test_the_chosen_design_gives_the_expected_mde():
    """N=1000/arm at the sourced baseline of 51%."""
    assert mde_at_n(p1=0.51, n_per_arm=1000) == pytest.approx(0.062, abs=0.004)


def test_the_mde_at_the_pre_registered_design_is_6_2_pp():
    # The figure quoted in the spec and in DECISION.md A-001. If this moves, the
    # documents are wrong, not the code.
    assert mde_at_n(p1=BASELINE_P1, n_per_arm=1000) == pytest.approx(0.0623, abs=0.0005)


def test_the_quarter_size_figure_matches_the_corrected_value():
    # A-012 corrected an earlier 13.9pp to 12.3pp. Pinned so it cannot drift back.
    assert mde_at_n(p1=BASELINE_P1, n_per_arm=250) == pytest.approx(0.1230, abs=0.0005)


def test_the_baseline_comes_from_the_frozen_registry_not_a_literal():
    """p1 is sourced, and the report must use the frozen value.

    Typing 0.51 into this module would let it drift from `PARAMS.md` silently.
    Reading it from the registry means the freeze covers the number that goes
    into the power calculation.
    """
    from recoup.simulator.curve import PARAMS

    assert BASELINE_P1 == PARAMS["baseline_recovery_rate"]["value"] == 0.51
    assert PARAMS["baseline_recovery_rate"]["class"] == "MEASURED"


# --- shape ------------------------------------------------------------------------


def test_mde_shrinks_as_n_grows():
    assert mde_at_n(0.51, 2000) < mde_at_n(0.51, 1000) < mde_at_n(0.51, 500)


def test_n_and_mde_are_inverses_of_each_other():
    mde = mde_at_n(p1=0.51, n_per_arm=1000)
    assert n_per_arm(p1=0.51, mde=mde) == pytest.approx(1000, rel=0.05)


def test_the_round_trip_is_exact_at_the_design_point():
    mde = mde_at_n(p1=BASELINE_P1, n_per_arm=1000)
    assert n_per_arm(p1=BASELINE_P1, mde=mde) == 1000


def test_smaller_mde_demands_more_subjects():
    assert n_per_arm(0.51, 0.03) > n_per_arm(0.51, 0.06)


def test_more_power_demands_more_subjects():
    assert n_per_arm(0.51, 0.06, power=0.90) > n_per_arm(0.51, 0.06, power=0.80)


def test_a_stricter_alpha_demands_more_subjects():
    assert n_per_arm(0.51, 0.06, alpha=0.01) > n_per_arm(0.51, 0.06, alpha=0.05)


def test_a_baseline_near_one_half_is_the_most_expensive():
    """Variance peaks at p=0.5, so that baseline needs the largest sample."""
    assert n_per_arm(0.50, 0.05) > n_per_arm(0.90, 0.05)


def test_n_per_arm_returns_a_whole_number_rounded_up():
    n = n_per_arm(0.51, 0.0623)
    assert isinstance(n, int)
    # Rounding down would report a design that is underpowered for its own claim.
    assert n_per_arm(0.51, 0.0623) >= 1000 - 1


# --- inputs that must not be guessed -----------------------------------------------


def test_a_baseline_outside_zero_to_one_is_refused():
    for bad in (-0.1, 0.0, 1.0, 1.5):
        with pytest.raises(ValueError, match="p1"):
            n_per_arm(bad, 0.05)


def test_a_non_positive_mde_is_refused():
    # mde = 0 divides by zero; a negative one silently computes a positive n for
    # an effect in the wrong direction.
    for bad in (0.0, -0.05):
        with pytest.raises(ValueError, match="mde"):
            n_per_arm(0.51, bad)


def test_an_mde_that_pushes_p2_past_one_is_refused():
    # p1 = 0.9 with mde = 0.2 would clamp p2 to 1.0 and quietly answer a
    # different question than the one asked.
    with pytest.raises(ValueError, match="p2"):
        n_per_arm(0.9, 0.2)


def test_an_invalid_alpha_or_power_is_refused():
    with pytest.raises(ValueError, match="alpha"):
        n_per_arm(0.51, 0.05, alpha=0.0)
    with pytest.raises(ValueError, match="power"):
        n_per_arm(0.51, 0.05, power=1.0)


def test_a_non_positive_n_is_refused():
    with pytest.raises(ValueError, match="n_per_arm"):
        mde_at_n(0.51, 0)


# --- the numbers that go into EXPERIMENT.md -----------------------------------------


def test_design_table_covers_the_pre_registered_sizes():
    table = design_table()
    assert [row["n_per_arm"] for row in table] == [250, 500, 1000, 2000]
    for row in table:
        assert row["p1"] == BASELINE_P1
        assert row["alpha"] == DEFAULT_ALPHA
        assert row["power"] == DEFAULT_POWER
        assert 0.0 < row["mde"] < 1.0


def test_design_table_is_computed_not_transcribed():
    # Every row must agree with a direct call. A table typed by hand is how the
    # spec's illustrative figures became a wrong number in a document (A-001).
    for row in design_table():
        assert row["mde"] == mde_at_n(BASELINE_P1, row["n_per_arm"])
