"""Every arm must be able to act. INC-007's guard.

THE FAILURE THIS EXISTS FOR
---------------------------
The control arm's `Action` omitted `body_matches_registered_template`. It
defaults to False, DLT-008 vetoed every control message, and the control arm
sent nothing and recovered nothing. Measured lift would have been enormous and
meaningless — a number-fabricating defect, not a silent failure.

Nothing caught it. The unit tests passed: the control produced an Action with
the right schedule and the right copy, and the policy engine correctly vetoed
it. Each half was right. Nobody ran them together.

So this test walks the ARM REGISTRY and puts each arm's real action through the
real engine. Parametrised over `DECIDERS`, so an arm added later without policy
coverage fails here rather than passing by omission — a test naming its arms in
a literal list would go green on an arm it had never heard of.

WHAT IT ASSERTS, AND WHAT IT DOES NOT
--------------------------------------
It asserts each arm can take the actions it is SUPPOSED to be able to take. It
does not assert every action is allowed — an arm proposing something illegal
should be vetoed, and this test would be wrong to say otherwise.
"""

from datetime import UTC, datetime, timedelta

import pytest

from recoup.agent.llm import DETERMINISTIC
from recoup.assign.registry import ALL_ARMS, DECIDERS, decider_for
from recoup.policy.engine import PolicyEngine
from recoup.render.templates import body_matches

RULES = "src/recoup/policy/rules.yaml"

# 11:00 IST on a weekday — inside every send-window rule, so a veto here is
# about the message rather than about the clock.
NOW = datetime(2026, 9, 2, 5, 0, tzinfo=UTC)


class _State:
    def __init__(self, **kw):
        self.subscription_id = "sub_cov"
        self.customer_id = "cust_cov"
        self.arm = "control"
        self.attempts_seen: set[int] = set()
        self.attempts = 0
        self.spend_paise = 0
        self.opted_out = False
        self.recovered_paise = 0
        self.ptp_date = None
        self.messages_today = 0
        self.whatsapp_optin = True
        self.__dict__.update(kw)


CONTEXT = {
    "day_offset": 0,
    "amount_paise": 49900,
    "is_hard_decline": False,
    "reason_code": "insufficient_funds",
    "customer_name": "Priya",
}


class _PlanningLLM:
    """A model that proposes a legal action. Its CONTENT is not what is asserted.

    The assertions below are about what the policy engine says, so this stands in
    for "the model returned something well-formed" and nothing more.
    """

    name = "fake-planner-1"

    def classify_reply(self, text, today):  # pragma: no cover - wrong role
        raise AssertionError("not this path")

    def propose_action(self, system, prompt):
        return {
            "action_type": "send_message",
            "template_id": "TPL_RECOUP_WA_001",
            "hours_from_now": 0,
            "variables": {"name": "Priya", "amount": "499"},
            "rationale": "day 0",
        }


def _client_for(arm: str):
    return _PlanningLLM() if arm == "treatment" else None


def test_the_registry_covers_every_assignable_arm():
    """An arm the experiment assigns to but nothing decides for sends nothing."""
    assert set(DECIDERS) == set(ALL_ARMS)


@pytest.mark.parametrize("arm", sorted(DECIDERS))
def test_each_arm_actually_proposes_an_action(arm):
    """Before asking whether it is allowed: does the arm act at all?"""
    action = decider_for(arm, client=_client_for(arm)).propose(
        _State(arm=arm), CONTEXT, now=NOW
    )
    assert action is not None, f"arm {arm!r} proposed nothing on day 0"
    assert action.action_type == "send_message"


@pytest.mark.parametrize("arm", sorted(DECIDERS))
def test_each_arms_own_action_is_not_vetoed(arm):
    """THE INC-007 ASSERTION. An arm whose every message is vetoed is an arm
    that recovers nothing, and its counterpart's lift is then an artifact."""
    action = decider_for(arm, client=_client_for(arm)).propose(
        _State(arm=arm), CONTEXT, now=NOW
    )
    verdict = PolicyEngine(RULES).evaluate(action, _State(arm=arm), now=NOW)
    assert verdict.allowed, (
        f"arm {arm!r} cannot send its own first message: "
        f"{[(d.rule_id, d.detail) for d in verdict.denials]}"
    )


@pytest.mark.parametrize("arm", sorted(DECIDERS))
def test_each_arms_body_matches_a_registered_template(arm):
    """Computed here rather than read off the action, so an arm that asserts the
    flag without earning it fails — which is exactly what INC-007 was."""
    action = decider_for(arm, client=_client_for(arm)).propose(
        _State(arm=arm), CONTEXT, now=NOW
    )
    assert body_matches(action.dlt_template_id, action.body), (
        f"arm {arm!r} produced a body that matches no registered template, "
        f"regardless of what its action claims"
    )
    assert action.body_matches_registered_template is True


#: The two vetoes mean opposite things. A STOP-class rule firing is the system
#: working -- the arm has spent its permitted attempts or budget. A content or
#: compliance rule firing on an arm's own first message means the arm can never
#: send anything, which is INC-007. Only the second kind is a defect here.
_STOPPING_RULES = ("STOP-",)


@pytest.mark.parametrize("arm", sorted(DECIDERS))
def test_each_arm_can_send_its_whole_permitted_quota(arm):
    """One allowed message is not enough. INC-007 would have shown up on the
    first send; an arm vetoed only from attempt 3 onward would not.

    Being vetoed by STOP-001 at attempt 6 is CORRECT -- the cap is 5. So the
    assertion is that every veto encountered is a stopping rule, and that the
    arm got its full quota out before hitting one. An arm vetoed on content
    fails both halves.
    """
    engine = PolicyEngine(RULES)
    state = _State(arm=arm)
    sent = 0
    for day in range(0, 15):
        decider = decider_for(arm, client=_client_for(arm))
        action = decider.propose(state, {**CONTEXT, "day_offset": day}, now=NOW)
        if action is None:
            continue
        verdict = engine.evaluate(action, state, now=NOW)
        if not verdict.allowed:
            offending = [d.rule_id for d in verdict.denials]
            assert all(
                any(r.startswith(p) for p in _STOPPING_RULES) for r in offending
            ), (
                f"arm {arm!r} vetoed on day {day} attempt {action.attempt_no} by a "
                f"NON-stopping rule {offending} — this arm cannot send at all "
                f"(INC-007): {[(d.rule_id, d.detail) for d in verdict.denials]}"
            )
            continue
        state.attempts_seen.add(action.attempt_no)
        state.attempts = len(state.attempts_seen)
        state.spend_paise += action.cost_paise
        sent += 1
    assert sent >= 5, (
        f"arm {arm!r} got only {sent} message(s) out across 15 days; the "
        f"attempt cap permits 5, so this arm is being stopped by something else"
    )


def test_the_treatment_arm_refuses_to_run_without_a_model():
    """The other way an arm silently does nothing: no key, no model, and a
    deterministic stand-in quietly becomes 'the agent'."""
    with pytest.raises(ValueError, match="no model"):
        decider_for("treatment", client=None).propose(_State(), CONTEXT, now=NOW)


def test_a_fallback_action_is_still_sendable_but_labelled():
    """When the model returns nothing the batch must continue — but the action
    carries DETERMINISTIC so the CLAIM cannot be made over it."""

    class _Useless:
        name = "fake-planner-1"

        def classify_reply(self, text, today):  # pragma: no cover
            raise AssertionError("not this path")

        def propose_action(self, system, prompt):
            return None

    action = decider_for("treatment", client=_Useless()).propose(
        _State(), CONTEXT, now=NOW
    )
    assert action.model_source == DETERMINISTIC
    verdict = PolicyEngine(RULES).evaluate(action, _State(), now=NOW)
    assert verdict.allowed, "a fallback that cannot be sent is not a fallback"


def test_both_arms_are_evaluated_by_the_same_engine_instance():
    """D-015: only the decision module differs. If the arms were gated by
    different rule sets, the comparison would be between two policies rather
    than between two deciders."""
    engine = PolicyEngine(RULES)
    seen = {}
    for arm in sorted(DECIDERS):
        action = decider_for(arm, client=_client_for(arm)).propose(
            _State(arm=arm), CONTEXT, now=NOW
        )
        engine.evaluate(action, _State(arm=arm), now=NOW)
        seen[arm] = engine.evaluated_rule_ids()
    assert len(set(map(frozenset, seen.values()))) == 1, (
        f"arms were evaluated against different rules: {seen}"
    )


@pytest.mark.parametrize("arm", sorted(DECIDERS))
def test_no_arm_can_propose_a_charge(arm):
    """D-030, asserted per arm rather than once globally, so an arm added later
    is covered without anyone remembering to extend a list."""
    action = decider_for(arm, client=_client_for(arm)).propose(
        _State(arm=arm), CONTEXT, now=NOW
    )
    assert action.action_type != "charge"
    assert action.cost_paise >= 0


@pytest.mark.parametrize("arm", sorted(DECIDERS))
def test_each_arm_stops_once_the_customer_has_paid(arm):
    paid = _State(arm=arm, recovered_paise=49900)
    action = decider_for(arm, client=_client_for(arm)).propose(paid, CONTEXT, now=NOW)
    assert action is None, f"arm {arm!r} kept messaging a customer who had paid"


@pytest.mark.parametrize("arm", sorted(DECIDERS))
def test_each_arm_honours_an_opt_out(arm):
    out = _State(arm=arm, opted_out=True)
    assert decider_for(arm, client=_client_for(arm)).propose(out, CONTEXT, now=NOW) is None


def test_the_schedule_window_used_here_is_inside_every_send_hour_rule():
    """Guards the test itself: if NOW drifted outside the permitted window every
    assertion above would fail for a reason that has nothing to do with arms."""
    later = NOW + timedelta(hours=1)
    engine = PolicyEngine(RULES)
    action = decider_for("control").propose(_State(), CONTEXT, now=later)
    assert engine.evaluate(action, _State(), now=later).allowed
