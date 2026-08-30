from collections import Counter

import pytest

from recoup.simulator import generator as gen_mod
from recoup.simulator.generator import (
    HARD_DECLINE_CODES,
    PARAMS,
    REASON_MIX,
    RESIDUAL_HARD_FRACTION,
    UNREGISTERED_OK,
    generate_scenarios,
)
from recoup.simulator.provenance import (
    params_problems,
    unread_assumptions,
    unregistered_constants,
    unregistered_literals,
)

# --- determinism --------------------------------------------------------------


def test_generation_is_deterministic_given_a_seed():
    a = generate_scenarios(n=200, seed=42)
    b = generate_scenarios(n=200, seed=42)
    assert a == b


def test_different_seeds_give_different_batches():
    assert generate_scenarios(n=200, seed=1) != generate_scenarios(n=200, seed=2)


def test_it_generates_exactly_n():
    assert len(generate_scenarios(n=2000, seed=7)) == 2000


def test_subscription_ids_are_unique():
    scenarios = generate_scenarios(n=1000, seed=3)
    assert len({s.subscription_id for s in scenarios}) == 1000


def test_two_seeds_produce_disjoint_subscription_ids():
    """The A/A batch is drawn from OUTSIDE the powered N (D-032).

    If ids were positional only -- sub_sim_000001 for every seed -- the A/A batch
    and the main run would collide in the ledger, and replay would merge two
    different subscriptions into one state. The seed is part of the identity.
    """
    a = {s.subscription_id for s in generate_scenarios(n=500, seed=1)}
    b = {s.subscription_id for s in generate_scenarios(n=500, seed=2)}
    assert not (a & b)


def test_ids_are_stable_across_batch_sizes():
    # Drawing 100 then 500 with the same seed must not renumber anyone.
    small = generate_scenarios(n=100, seed=4)
    large = generate_scenarios(n=500, seed=4)
    assert [s.subscription_id for s in small] == [s.subscription_id for s in large[:100]]


# --- the sourced mix ----------------------------------------------------------


def test_reason_mix_weights_sum_to_one():
    assert abs(sum(REASON_MIX.values()) - 1.0) < 1e-9


def test_the_residual_bucket_is_actually_the_residual():
    """PLAN.md had `other: 0.1544`; the true residual is 0.0544.

    The 12 sourced Churnkey codes sum to 0.9456. The plan's value made the
    weights total 1.1000, which silently rescaled every sourced share -- pushing
    insufficient_funds from 40.56% to 36.87% and breaking two of the plan's own
    tests. A residual that is not 1 - sum(sourced) is not a residual.
    """
    sourced = {k: v for k, v in REASON_MIX.items() if k != "other"}
    assert REASON_MIX["other"] == pytest.approx(1.0 - sum(sourced.values()), abs=1e-9)
    assert sum(sourced.values()) == pytest.approx(0.9456, abs=1e-9)


def test_reason_mix_approximates_the_sourced_distribution():
    scenarios = generate_scenarios(n=20000, seed=11)
    counts = Counter(s.reason_code for s in scenarios)
    share = counts["insufficient_funds"] / len(scenarios)
    # sourced at 40.56%; allow sampling slack
    assert 0.38 < share < 0.43


def test_every_sourced_share_is_reproduced_not_just_the_largest():
    # One share landing in range can happen while the rest are rescaled. Check
    # the whole distribution, which is what the 1.1 total would have broken.
    scenarios = generate_scenarios(n=40000, seed=23)
    counts = Counter(s.reason_code for s in scenarios)
    for code, expected in REASON_MIX.items():
        observed = counts[code] / len(scenarios)
        assert abs(observed - expected) < 0.012, f"{code}: {observed:.4f} vs {expected:.4f}"


def test_hard_decline_share_is_about_21_percent():
    scenarios = generate_scenarios(n=20000, seed=13)
    share = sum(s.is_hard_decline for s in scenarios) / len(scenarios)
    assert 0.18 < share < 0.24


def test_hard_decline_flag_matches_the_reason_code():
    for s in generate_scenarios(n=2000, seed=5):
        assert s.is_hard_decline == (s.reason_code in HARD_DECLINE_CODES)


def test_the_residual_bucket_defaults_to_soft_and_that_is_declared():
    # Six hard-decline codes (lost_card, stolen_card, ...) never appear in the
    # Churnkey table and so live inside `other`, which defaults to soft. That is
    # an assumption, registered rather than inherited from the table's shape.
    assert "other" not in HARD_DECLINE_CODES
    assert PARAMS["residual_hard_fraction"]["class"] == "ASSUMPTION"
    assert RESIDUAL_HARD_FRACTION == 0.0


def test_the_residual_hard_fraction_actually_moves_the_model(monkeypatch):
    """A swept parameter nothing reads reports INSENSITIVE and proves nothing.

    This one was declared with a sweep and implemented nowhere. The sensitivity
    analysis would have varied it across 0-30%, seen an identical result every
    time, and recorded robustness that had never been tested.
    """
    base = sum(s.is_hard_decline for s in generate_scenarios(n=20000, seed=31))
    monkeypatch.setattr(gen_mod, "RESIDUAL_HARD_FRACTION", 0.30)
    swept = sum(s.is_hard_decline for s in generate_scenarios(n=20000, seed=31))
    assert swept > base, "sweeping this parameter must change the generated batch"


def test_sweeping_the_residual_does_not_reshuffle_the_rest_of_the_batch(monkeypatch):
    """Common random numbers: one parameter moves, nothing else does.

    The residual roll is drawn unconditionally, so changing the parameter cannot
    change how many numbers each scenario consumes. A conditional draw would
    shift every later draw, and the sweep would then be measuring the parameter
    plus a different Monte Carlo realisation.
    """
    base = generate_scenarios(n=2000, seed=37)
    monkeypatch.setattr(gen_mod, "RESIDUAL_HARD_FRACTION", 0.30)
    swept = generate_scenarios(n=2000, seed=37)

    assert [s.reason_code for s in base] == [s.reason_code for s in swept]
    assert [s.amount_paise for s in base] == [s.amount_paise for s in swept]
    pairs = zip(base, swept, strict=True)
    changed = [i for i, (a, b) in enumerate(pairs) if a.is_hard_decline != b.is_hard_decline]
    assert changed, "the parameter must do something"
    assert all(base[i].reason_code == "other" for i in changed), (
        "only residual-bucket scenarios may change"
    )


# --- scenario fields ----------------------------------------------------------


def test_amounts_are_integer_paise():
    for s in generate_scenarios(n=500, seed=9):
        assert isinstance(s.amount_paise, int)
        assert s.amount_paise > 0


def test_ground_truth_label_is_present_and_boolean():
    for s in generate_scenarios(n=100, seed=17):
        assert isinstance(s.would_self_recover, bool)


def test_hard_declines_self_recover_far_less_often_than_soft():
    scenarios = generate_scenarios(n=20000, seed=29)
    hard = [s for s in scenarios if s.is_hard_decline]
    soft = [s for s in scenarios if not s.is_hard_decline]
    rate_hard = sum(s.would_self_recover for s in hard) / len(hard)
    rate_soft = sum(s.would_self_recover for s in soft) / len(soft)
    assert rate_hard < rate_soft / 2


def test_n_of_zero_is_an_empty_batch_not_an_error():
    assert generate_scenarios(n=0, seed=1) == []


def test_a_negative_n_is_refused():
    with pytest.raises(ValueError, match="n"):
        generate_scenarios(n=-1, seed=1)


# --- provenance ---------------------------------------------------------------


def test_every_generator_parameter_is_well_formed():
    assert params_problems(PARAMS) == []


def test_every_numeric_constant_in_the_module_is_registered():
    # The check that sits where the failure happens: a number typed into the
    # module and never registered. SELF_RECOVERY_RATE_SOFT was exactly this in
    # the draft -- an ASSUMPTION driving the ground-truth label, unmarked.
    assert unregistered_constants(gen_mod, PARAMS, UNREGISTERED_OK) == []


def test_no_magic_numbers_inside_the_generator_functions():
    assert unregistered_literals(gen_mod) == []


def test_every_swept_assumption_is_actually_read_by_the_module():
    assert unread_assumptions(gen_mod, PARAMS) == []


def test_amount_weights_sum_to_one_and_align_with_the_choices():
    # Untested in the plan. random.choices normalises silently, so a weight set
    # that does not sum to 1 distorts the distribution without failing -- exactly
    # how the reason mix reached 1.1000 undetected.
    weights = PARAMS["amount_weights"]["value"]
    choices = PARAMS["amount_distribution"]["value"]
    assert abs(sum(weights) - 1.0) < 1e-9
    assert len(weights) == len(choices)


def test_the_self_recovery_rates_are_assumptions_with_sweeps():
    # These generate `would_self_recover`, which sets the counterfactual the
    # entire lift claim is measured against. If any number in this project needs
    # to be honest about being invented, it is this one.
    for key in ("self_recovery_rate_soft", "self_recovery_rate_hard"):
        assert PARAMS[key]["class"] == "ASSUMPTION"
        assert PARAMS[key]["sweep"]
