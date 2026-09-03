"""Does the result survive its own assumptions?

The two commitments that matter here were made in `CLAUDE.md` before any number
existed:

* **Report the SIGN, not only the magnitude.** A corner of a declared range where
  the treatment arm loses is a finding, not a range to narrow.
* **Prove each parameter moved the model before calling it insensitive**
  (A-017, INC-005). A parameter nothing reads produces a flat line, and a flat
  line reads as robustness — the sweep would report its most reassuring result
  exactly where the model is emptiest.
"""

import pytest

from recoup.eval.sensitivity import (
    COUNTERFACTUAL_FIRST,
    ReplayAction,
    SweepResult,
    assumption_params,
    render_sweep,
    sweep_assumptions,
)

SEED = 20260902


def _actions(n: int = 120) -> list[ReplayAction]:
    """A cohort shaped like a real run: both arms, several attempts each."""
    out = []
    for i in range(n):
        arm = "control" if i % 2 else "treatment"
        for attempt, day in enumerate((0, 2, 4, 7, 10), start=1):
            out.append(ReplayAction(
                subscription_id=f"sub_sim_{SEED}_{i:06d}",
                arm=arm,
                channel="whatsapp",
                day_offset=day,
                attempt_no=attempt,
                is_hard_decline=(i % 5 == 0),
            ))
    return out


# --- the registry ----------------------------------------------------------------


def test_it_finds_every_declared_assumption():
    names = {p["name"] for p in assumption_params()}
    assert "channel_multiplier_whatsapp" in names
    assert "hard_decline_multiplier" in names
    assert "self_recovery_rate_soft" in names


def test_every_assumption_carries_a_sweep_range():
    for param in assumption_params():
        lo, hi = param["sweep"]
        assert lo < hi, param["name"]


def test_the_counterfactual_parameters_are_swept_FIRST():
    """CLAUDE.md's commitment, and the order is load-bearing.

    These two define `would_self_recover`, so they set the denominator of the
    whole lift claim, and nothing published measures them. Anything swept before
    them is a warm-up.
    """
    names = [p["name"] for p in assumption_params()]
    assert names[: len(COUNTERFACTUAL_FIRST)] == list(COUNTERFACTUAL_FIRST)


def test_the_registry_is_read_not_hand_listed():
    """A hand-maintained list silently stops covering a parameter added later."""
    import inspect

    from recoup.eval import sensitivity

    source = inspect.getsource(sensitivity.assumption_params)
    assert "PARAMS" in source


# --- the sweep -------------------------------------------------------------------


def test_the_sweep_produces_a_result_per_endpoint():
    results = sweep_assumptions(_actions(), seed=SEED)
    assert len(results) == len(assumption_params()) * 2


def test_each_result_reports_whether_the_sign_flipped():
    for r in sweep_assumptions(_actions(), seed=SEED):
        assert isinstance(r.sign_flipped, bool)
        assert r.param in {p["name"] for p in assumption_params()}


def test_sweeping_over_no_actions_is_refused():
    """It would report every parameter as unwired — the most reassuring possible
    result, and meaningless."""
    with pytest.raises(ValueError, match="unwired"):
        sweep_assumptions([], seed=SEED)


# --- UNWIRED is not INSENSITIVE ---------------------------------------------------


def test_a_parameter_that_moves_nothing_is_reported_unwired():
    """A-017/INC-005. The distinction the whole task turns on."""
    r = SweepResult(
        param="ghost", value=0.5, endpoint="low", lift_pp=3.0,
        baseline_lift_pp=3.0, control_rate=0.3, treatment_rate=0.33,
        moved_the_model=False,
    )
    assert r.verdict == "UNWIRED"
    assert "UNWIRED, not insensitive" in "\n".join(render_sweep([r]))


def test_a_parameter_that_moves_the_model_and_holds_is_stable():
    r = SweepResult(
        param="real", value=0.5, endpoint="low", lift_pp=2.7,
        baseline_lift_pp=3.0, control_rate=0.30, treatment_rate=0.327,
        moved_the_model=True,
    )
    assert r.verdict == "stable"


def test_at_least_one_swept_parameter_actually_moves_the_model():
    """Guards the sweep itself. If none moved anything, every line would read
    'UNWIRED' and the sweep would be measuring nothing at all."""
    results = sweep_assumptions(_actions(), seed=SEED)
    moved = [r for r in results if r.moved_the_model]
    assert moved, "no swept parameter changed the outcome; the sweep is inert"


def test_the_channel_multiplier_demonstrably_moves_the_model():
    """A named parameter, checked directly rather than inferred from an
    aggregate — an aggregate can pass on one parameter doing all the work."""
    results = sweep_assumptions(_actions(), seed=SEED)
    channel = [r for r in results if r.param == "channel_multiplier_whatsapp"]
    assert channel, "the parameter was not swept at all"
    assert any(r.moved_the_model for r in channel)


# --- the SIGN ---------------------------------------------------------------------


def test_a_flip_is_detected_and_named():
    flipped = SweepResult(
        param="p", value=0.1, endpoint="low", lift_pp=-2.0,
        baseline_lift_pp=+3.0, control_rate=0.35, treatment_rate=0.33,
        moved_the_model=True,
    )
    assert flipped.sign_flipped
    rendered = "\n".join(render_sweep([flipped]))
    assert "SIGN FLIPPED" in rendered
    assert "falsifying" in rendered
    assert "not narrowed away" in rendered


def test_an_unwired_parameter_cannot_report_a_flip():
    """Its lift equals the baseline by construction, so a 'flip' would be an
    artifact of the parameter doing nothing."""
    r = SweepResult(
        param="ghost", value=0.5, endpoint="low", lift_pp=3.0,
        baseline_lift_pp=3.0, control_rate=0.3, treatment_rate=0.33,
        moved_the_model=False,
    )
    assert not r.sign_flipped


def test_no_flip_is_reported_plainly_rather_than_as_a_pass():
    r = SweepResult(
        param="p", value=0.9, endpoint="high", lift_pp=2.9,
        baseline_lift_pp=3.0, control_rate=0.30, treatment_rate=0.329,
        moved_the_model=True,
    )
    assert "No sign flip" in "\n".join(render_sweep([r]))


# --- the freeze -------------------------------------------------------------------


def test_the_sweep_leaves_the_frozen_simulator_unchanged():
    """Parameters are overridden by runtime attribute assignment, never by
    editing a file, so sha256(simulator/) is untouched."""
    from recoup.simulator.freeze import hash_simulator_dir

    before = hash_simulator_dir()
    sweep_assumptions(_actions(60), seed=SEED)
    assert hash_simulator_dir() == before


def test_the_sweep_restores_every_constant_it_touched():
    """A sweep that leaked a value would silently re-parameterise everything
    that ran after it, including the report."""
    from recoup.simulator import curve, generator

    before = (
        dict(curve.CHANNEL_MULTIPLIER),
        curve.HARD_DECLINE_MULTIPLIER,
        curve.ATTEMPT_DECAY_COMPOUNDING,
        generator.SELF_RECOVERY_RATE_SOFT,
    )
    sweep_assumptions(_actions(60), seed=SEED)
    after = (
        dict(curve.CHANNEL_MULTIPLIER),
        curve.HARD_DECLINE_MULTIPLIER,
        curve.ATTEMPT_DECAY_COMPOUNDING,
        generator.SELF_RECOVERY_RATE_SOFT,
    )
    assert before == after


def test_a_raise_mid_sweep_still_restores():
    """The restore is in a finally, and this proves it rather than reading it."""
    from recoup.simulator import curve

    before = dict(curve.CHANNEL_MULTIPLIER)
    bad = [ReplayAction("sub_x", "control", "carrier-pigeon", 0, 1, False)]
    with pytest.raises(ValueError):
        sweep_assumptions(bad, seed=SEED)
    assert dict(curve.CHANNEL_MULTIPLIER) == before


def test_a_cohort_parameter_is_NOT_SWEPT_rather_than_unwired():
    """The distinction one level up from A-017.

    `self_recovery_rate_soft` cannot be reached by a sweep that replays fixed
    actions — it acts at scenario generation. Reporting it as UNWIRED would say
    "we swept it and it did not matter" about a parameter nobody swept, which is
    the reassuring-result-where-the-model-is-emptiest failure again.
    """
    results = sweep_assumptions(_actions(60), seed=SEED)
    soft = [r for r in results if r.param == "self_recovery_rate_soft"]
    assert soft, "the counterfactual parameter was not even listed"
    assert all(r.verdict == "NOT SWEPT" for r in soft)
    assert all(r.out_of_scope for r in soft)

    rendered = "\n".join(render_sweep(results))
    assert "NOT SWEPT" in rendered
    assert "they are the two that matter most" in rendered
    assert "cohort" in rendered.lower()


def test_a_response_curve_parameter_is_still_judged_normally():
    """The scope carve-out must not swallow the parameters the sweep CAN test."""
    results = sweep_assumptions(_actions(60), seed=SEED)
    hard = [r for r in results if r.param == "hard_decline_multiplier"]
    assert hard
    assert not any(r.out_of_scope for r in hard)
    assert any(r.moved_the_model for r in hard)
