from datetime import UTC, datetime, timedelta

import pytest

from recoup.baseline.fixed import (
    CHANNEL_ALTERNATIVES,
    COST_PAISE,
    FIXED_CHANNEL,
    PARAMS,
    SCHEDULE_ALTERNATIVES,
    SCHEDULE_DAYS,
    FixedIntervalOutreach,
)
from recoup.ledger.replay import SubscriptionState
from recoup.simulator.provenance import CLASSES

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _state(**kw):
    st = SubscriptionState(subscription_id="sub_1", customer_id="cust_1", arm="control")
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def _ctx(day_offset=0):
    return {"day_offset": day_offset, "amount_paise": 49900, "halted_at": T0}


# --- the contract PLAN.md specifies ------------------------------------------------


def test_it_proposes_on_the_first_day():
    action = FixedIntervalOutreach().propose(_state(), _ctx(0), now=T0)
    assert action is not None
    assert action.action_type == "send_message"
    assert action.attempt_no == 1


def test_it_never_proposes_a_charge():
    """D-030: post-halt the system issues no debits, ever."""
    for day in SCHEDULE_DAYS:
        action = FixedIntervalOutreach().propose(
            _state(), _ctx(day), now=T0 + timedelta(days=day)
        )
        if action:
            assert action.action_type in ("send_message", "create_link", "wait", "stop")


def test_it_stays_silent_between_scheduled_days():
    off_schedule = next(d for d in range(1, 30) if d not in SCHEDULE_DAYS)
    action = FixedIntervalOutreach().propose(
        _state(), _ctx(off_schedule), now=T0 + timedelta(days=off_schedule)
    )
    assert action is None


def test_it_stops_after_the_schedule_is_exhausted():
    state = _state()
    state.attempts_seen = set(range(1, len(SCHEDULE_DAYS) + 1))
    beyond = max(SCHEDULE_DAYS) + 20
    action = FixedIntervalOutreach().propose(
        state, _ctx(beyond), now=T0 + timedelta(days=beyond)
    )
    assert action is None


def test_the_copy_is_identical_every_time():
    """No decisioning. That is the whole point of the baseline."""
    bodies = {
        FixedIntervalOutreach().propose(_state(), _ctx(d), now=T0 + timedelta(days=d)).body
        for d in SCHEDULE_DAYS
    }
    assert len(bodies) == 1


def test_the_copy_is_service_implicit_clean():
    from recoup.policy.predicates import classify_message, contains_promotional_tokens

    action = FixedIntervalOutreach().propose(_state(), _ctx(0), now=T0)
    assert contains_promotional_tokens(action.body) is None
    assert classify_message(action.body) == "SERVICE_IMPLICIT"


def test_it_respects_opt_out_without_needing_the_policy_engine():
    assert FixedIntervalOutreach().propose(_state(opted_out=True), _ctx(0), now=T0) is None


def test_the_channel_is_fixed():
    channels = {
        FixedIntervalOutreach().propose(_state(), _ctx(d), now=T0 + timedelta(days=d)).channel
        for d in SCHEDULE_DAYS
    }
    assert len(channels) == 1


# --- the control must actually SURVIVE the policy engine ----------------------------
# The catastrophic silent failure: if the baseline's action is vetoed, the control
# arm sends nothing, recovers nothing, and the measured lift is enormous and
# meaningless. PLAN.md has no such test, and its own Action omitted
# `body_matches_registered_template`, which now defaults to False -- so every
# control message would have been vetoed by DLT-008.


def test_every_scheduled_control_action_passes_the_policy_engine():
    import pathlib

    from recoup.policy.engine import PolicyEngine

    rules = pathlib.Path(__file__).resolve().parents[1] / "src/recoup/policy/rules.yaml"
    engine = PolicyEngine(str(rules))

    for day in SCHEDULE_DAYS:
        now = T0 + timedelta(days=day)
        action = FixedIntervalOutreach().propose(_state(), _ctx(day), now=now)
        assert action is not None, f"no action on scheduled day {day}"
        verdict = engine.evaluate(action, _state(), now=now)
        assert verdict.allowed, (
            f"day {day}: the control's own message was vetoed by "
            f"{verdict.rule_ids}. A vetoed control arm sends nothing and the "
            f"measured lift becomes meaningless."
        )


def test_the_policy_check_would_catch_a_control_message_that_could_not_ship():
    """The planted failure for the check above.

    `body_matches_registered_template` defaults to False so DLT-008 can fire.
    PLAN.md's baseline Action omitted it entirely — every control message would
    have been vetoed, the control arm would have sent nothing, and the measured
    lift would have been enormous and meaningless. This constructs that exact
    action and confirms the veto lands.
    """
    import pathlib

    from recoup.policy.engine import PolicyEngine

    rules = pathlib.Path(__file__).resolve().parents[1] / "src/recoup/policy/rules.yaml"
    engine = PolicyEngine(str(rules))

    good = FixedIntervalOutreach().propose(_state(), _ctx(0), now=T0)
    as_plan_had_it = good.model_copy(update={"body_matches_registered_template": False})

    assert engine.evaluate(good, _state(), now=T0).allowed
    verdict = engine.evaluate(as_plan_had_it, _state(), now=T0)
    assert not verdict.allowed
    assert "DLT-008" in verdict.rule_ids


def test_pooling_the_two_arms_across_transports_is_refused():
    """The control and treatment arms must never be averaged across transports.

    The realistic way this happens: the measured batch runs on `sim` while a
    demo subscription runs on `real`, and someone computes one recovery rate
    over the whole ledger. One arm's outcome would then come from the simulator
    and the other from Razorpay — an oracle averaged with reality.
    """
    from recoup.eval.transport_split import require_declared_split, summarise

    control_rows = [{"transport": "sim", "arm": "control"} for _ in range(40)]
    treatment_rows = [{"transport": "sim", "arm": "treatment"} for _ in range(40)]
    demo_rows = [{"transport": "real", "arm": "treatment"} for _ in range(3)]

    # Same transport across both arms: pooling is legitimate.
    ok = require_declared_split(control_rows + treatment_rows, run_id="run-batch")
    assert ok.sole_transport == "sim"

    # One real row anywhere in the run and the refusal fires.
    with pytest.raises(ValueError, match="refusing to pool"):
        require_declared_split(control_rows + treatment_rows + demo_rows, run_id="run-mixed")

    split = summarise(control_rows + treatment_rows + demo_rows)
    assert split.real == 3 and split.sim == 80
    assert "never pooled" in split.caveat()


def test_the_control_stays_inside_its_own_stopping_rules():
    """Five attempts is exactly STOP-001's ceiling, and the spend cap is not near."""
    assert len(SCHEDULE_DAYS) == 5
    total_spend = len(SCHEDULE_DAYS) * COST_PAISE[FIXED_CHANNEL]
    assert total_spend < 5000, f"{total_spend} paise would breach STOP-002"


# --- the strengthenings, pinned so they cannot quietly regress -----------------------


def test_it_stops_when_the_customer_pays():
    """A `payment_link.paid` mid-sequence ends the sequence.

    PLAN.md had no such rule, so the control would have kept messaging a customer
    who had already paid — spending money and inflating its own cost per recovery
    against the agent. That is a way of weakening the control by omission.
    """
    paid = _state(recovered_paise=49900)
    for day in SCHEDULE_DAYS:
        action = FixedIntervalOutreach().propose(
            paid, _ctx(day), now=T0 + timedelta(days=day)
        )
        assert action is None, f"still messaging on day {day} after payment"


def test_the_schedule_beats_the_one_plan_md_specified():
    """The control was strengthened, and by how much is checkable.

    Chosen before any lift number existed. If this ever fails, the control got
    weaker and the lift claim got easier — which is the wrong direction to drift.
    """
    from recoup.simulator.curve import recovery_probability

    def cumulative(days):
        survive = 1.0
        for attempt_no, day in enumerate(days, start=1):
            survive *= 1 - recovery_probability(day, "whatsapp", attempt_no, False)
        return 1 - survive

    assert cumulative(SCHEDULE_DAYS) > cumulative((0, 2, 5, 9, 14))
    assert cumulative(SCHEDULE_DAYS) == pytest.approx(0.3383, abs=0.001)


def test_every_attempt_falls_inside_the_sourced_recovery_window():
    """Recurly: 90% of successful recoveries occur within the first 10 days."""
    assert max(SCHEDULE_DAYS) <= 10


def test_the_stronger_alternatives_are_recorded_not_hidden():
    """Two schedules score higher and were not chosen.

    They are five messages in as many days, which is not a competent merchant's
    process — but the choice is recorded and swept rather than quietly made, so
    if the lift depends on the control not being maximally aggressive, the
    sensitivity analysis says so.
    """
    from recoup.simulator.curve import recovery_probability

    def cumulative(days):
        survive = 1.0
        for n, day in enumerate(days, start=1):
            survive *= 1 - recovery_probability(day, "whatsapp", n, False)
        return 1 - survive

    better = [s for s in SCHEDULE_ALTERNATIVES if cumulative(s) > cumulative(SCHEDULE_DAYS)]
    assert better, "if nothing scores higher, the note about alternatives is stale"
    assert all(s in SCHEDULE_ALTERNATIVES for s in [SCHEDULE_DAYS, (0, 2, 5, 9, 14)])


def test_sms_would_be_a_weaker_control_and_is_not_the_default():
    from recoup.simulator.curve import CHANNEL_MULTIPLIER

    assert CHANNEL_MULTIPLIER[FIXED_CHANNEL] >= max(
        CHANNEL_MULTIPLIER[c] for c in CHANNEL_ALTERNATIVES
    )


# --- provenance -----------------------------------------------------------------------


def test_every_baseline_parameter_carries_a_class_and_a_source():
    for name, meta in PARAMS.items():
        assert meta.get("class") in CLASSES, f"{name}: {meta.get('class')}"
        assert meta.get("source"), f"{name} has no source"


def test_a_measured_parameter_cites_a_url_and_a_population():
    for name, meta in PARAMS.items():
        if meta["class"] == "MEASURED":
            assert meta["source"].startswith("http"), name
            assert meta.get("population"), name


def test_an_assumption_declares_a_sweep_or_a_choice_set_and_cites_no_url():
    for name, meta in PARAMS.items():
        if meta["class"] != "ASSUMPTION":
            continue
        assert "sweep" in meta or "choices" in meta, f"{name} is unswept"
        assert not meta["source"].startswith("http"), f"{name} cites a URL"


def test_a_derived_parameter_states_its_derivation():
    for name, meta in PARAMS.items():
        if meta["class"] == "DERIVED":
            assert meta.get("derivation"), name


def test_every_registered_constant_exists_and_matches():
    import recoup.baseline.fixed as mod

    for name, meta in PARAMS.items():
        const = meta["constant"]
        assert hasattr(mod, const), f"{name} names {const}, which does not exist"
        live = getattr(mod, const)
        recorded = meta["value"]
        assert list(live) == list(recorded) if isinstance(live, tuple) else live == recorded


def test_the_send_hour_is_inside_its_own_sweep():
    lo, hi = PARAMS["send_hour_ist"]["sweep"]
    assert lo <= PARAMS["send_hour_ist"]["value"] <= hi
