"""The treatment arm's decision module.

WHAT THE MODEL IS AND IS NOT ALLOWED TO DO
-------------------------------------------
It does NOT write message bodies. Under DLT a body that does not match its
registered template is not sendable however well it reads, so a planner that
emits free text emits unsendable actions -- and if the compliance flag were
asserted rather than computed, it would emit *illegal* ones that pass the check.

So the model picks a registered template, a channel and a delay, and supplies
variables. `render()` computes whether the result matches. That is a narrower
job than PLAN.md's `body: {"type": "string"}`, and deliberately so.

THE MOCK-LLM TRAP
-----------------
A test whose mock returns a compliant body and then asserts the body is
compliant has tested the mock. Every assertion here is about something the
PLANNER decides -- attempt numbering, template legality, what reaches the replan
prompt, what happens when the model returns nothing -- never about the content
the mock was configured to hand back.
"""

from datetime import UTC, datetime, timedelta

import pytest

from recoup.agent.llm import DETERMINISTIC, ModelProvenanceError, require_real_model
from recoup.agent.planner import RecoveryAgent
from recoup.policy.engine import Denial, Verdict
from recoup.render.templates import TEMPLATES, body_matches

T0 = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


class _State:
    def __init__(self, **kw):
        self.subscription_id = "sub_1"
        self.customer_id = "cust_1"
        self.arm = "treatment"
        self.attempts_seen: set[int] = set()
        self.spend_paise = 0
        self.opted_out = False
        self.recovered_paise = 0
        self.ptp_date = None
        self.messages_today = 0
        self.__dict__.update(kw)


def _ctx(**kw):
    base = {
        "day_offset": 0,
        "amount_paise": 49900,
        "is_hard_decline": False,
        "reason_code": "insufficient_funds",
        "customer_name": "Priya",
    }
    base.update(kw)
    return base


class _FakeLLM:
    """Stands in for a model. Records what it was asked, returns what it was told."""

    def __init__(self, payload=None, *, name="fake-model-1", payloads=None):
        self.name = name
        self._payloads = list(payloads) if payloads else None
        self._payload = payload if payload is not None else {
            "template_id": "TPL_RECOUP_WA_001",
            "hours_from_now": 2,
            "variables": {"name": "Priya", "amount": "499"},
            "rationale": "day 0, highest recovery window",
        }
        self.prompts: list[str] = []

    def classify_reply(self, text, today):  # pragma: no cover - not this role
        raise AssertionError("the planner must not use the reply-classification path")

    def propose_action(self, system: str, prompt: str) -> dict | None:
        self.prompts.append(prompt)
        if self._payloads:
            return self._payloads.pop(0)
        return self._payload


# --- the job ---------------------------------------------------------------------


def test_it_proposes_a_sendable_action():
    action = RecoveryAgent(client=_FakeLLM()).propose(_State(), _ctx(), now=T0)
    assert action is not None
    assert action.action_type == "send_message"
    assert action.attempt_no == 1
    assert action.body_matches_registered_template is True


def test_the_proposed_body_actually_matches_its_template():
    """Computed, not taken from the model. This is the DLT-008 claim."""
    action = RecoveryAgent(client=_FakeLLM()).propose(_State(), _ctx(), now=T0)
    assert body_matches(action.dlt_template_id, action.body) is True


def test_attempt_number_increments_with_prior_attempts():
    action = RecoveryAgent(client=_FakeLLM()).propose(
        _State(attempts_seen={1, 2}), _ctx(), now=T0
    )
    assert action.attempt_no == 3


def test_an_opted_out_customer_gets_nothing():
    assert RecoveryAgent(client=_FakeLLM()).propose(
        _State(opted_out=True), _ctx(), now=T0
    ) is None


def test_a_customer_who_paid_gets_nothing():
    assert RecoveryAgent(client=_FakeLLM()).propose(
        _State(recovered_paise=49900), _ctx(), now=T0
    ) is None


def test_a_stop_proposal_is_honoured():
    action = RecoveryAgent(
        client=_FakeLLM({"action_type": "stop", "rationale": "hard decline, 4 attempts"})
    ).propose(_State(), _ctx(), now=T0)
    assert action.action_type == "stop"
    assert action.cost_paise == 0


# --- D-030: no debit, ever -------------------------------------------------------


def test_the_model_cannot_ask_for_a_charge():
    """Not 'the prompt discourages it' — there is no such action type to emit."""
    agent = RecoveryAgent(client=_FakeLLM({"action_type": "charge", "rationale": "x"}))
    with pytest.raises(ValueError, match="charge"):
        agent.propose(_State(), _ctx(), now=T0)


# --- the model may not invent a template ----------------------------------------


def test_an_unregistered_template_is_refused_not_rendered():
    agent = RecoveryAgent(
        client=_FakeLLM({
            "template_id": "TPL_I_MADE_THIS_UP",
            "hours_from_now": 1,
            "variables": {"amount": "499"},
            "rationale": "x",
        })
    )
    action = agent.propose(_State(), _ctx(), now=T0)
    # Falls back rather than crashing the batch, but the fallback is LABELLED.
    assert action.model_source == DETERMINISTIC
    assert "fallback" in action.rationale


def test_a_variable_carrying_promotional_copy_is_refused():
    """The escape hatch: legal template, illegal variable content."""
    agent = RecoveryAgent(
        client=_FakeLLM({
            "template_id": "TPL_RECOUP_WA_001",
            "hours_from_now": 1,
            "variables": {
                "name": "Priya",
                "amount": "499. Don't lose your 40% loyalty discount",
            },
            "rationale": "x",
        })
    )
    action = agent.propose(_State(), _ctx(), now=T0)
    assert action.model_source == DETERMINISTIC


# --- provenance: a fallback is not a model decision ------------------------------


def test_a_model_action_records_the_model_id():
    action = RecoveryAgent(client=_FakeLLM(name="gemini-2.5-flash")).propose(
        _State(), _ctx(), now=T0
    )
    assert action.model_source == "gemini-2.5-flash"


def test_a_fallback_action_is_not_reportable_as_a_model_result():
    """The INC-006 shape: an action that looks like an agent decision with no
    model behind it. It may execute; it may not be counted as model output."""
    agent = RecoveryAgent(client=_FakeLLM(payload=None if False else {}))
    action = agent.propose(_State(), _ctx(), now=T0)
    assert action.model_source == DETERMINISTIC
    with pytest.raises(ModelProvenanceError):
        require_real_model([action], run_id="run-planner")


def test_a_run_mixing_model_and_fallback_actions_is_refused():
    real = RecoveryAgent(client=_FakeLLM(name="gemini-2.5-flash")).propose(
        _State(), _ctx(), now=T0
    )
    fell_back = RecoveryAgent(client=_FakeLLM({})).propose(_State(), _ctx(), now=T0)
    with pytest.raises(ModelProvenanceError):
        require_real_model([real, fell_back], run_id="run-planner")


def test_no_client_raises_rather_than_falling_back():
    """A missing key must not silently produce a deterministic 'agent' arm."""
    with pytest.raises(ValueError, match="no model"):
        RecoveryAgent(client=None).propose(_State(), _ctx(), now=T0)


# --- replan ----------------------------------------------------------------------


def _denial():
    return Verdict(
        allowed=False,
        denials=[
            Denial(
                rule_id="DLT-007",
                rule_class="HARD_LAW",
                reason="promotional content reclassifies the message",
                detail="body contains promotional token 'discount'",
                source_url="https://msg91.com/help/dlt-content-template-faqs",
            )
        ],
    )


def test_replan_puts_the_actual_denial_in_the_prompt():
    client = _FakeLLM()
    agent = RecoveryAgent(client=client)
    original = agent.propose(_State(), _ctx(), now=T0)
    agent.replan(original, _denial(), _State(), _ctx(), now=T0)

    prompt = client.prompts[-1]
    assert "DLT-007" in prompt
    assert "discount" in prompt
    assert "HARD_LAW" in prompt
    assert "msg91.com" in prompt, "the rule's source must travel with the veto"


def test_replan_keeps_the_same_attempt_number():
    """A veto is not a new attempt. Counting it as one would let a replan loop
    burn through STOP-001's five-attempt ceiling without sending anything."""
    client = _FakeLLM()
    agent = RecoveryAgent(client=client)
    original = agent.propose(_State(attempts_seen={1}), _ctx(), now=T0)
    replanned = agent.replan(original, _denial(), _State(attempts_seen={1}), _ctx(), now=T0)
    assert replanned.attempt_no == original.attempt_no == 2


def test_replan_is_bounded():
    """Without a bound, a model that keeps proposing the same vetoed thing loops
    forever inside one subscription's turn."""
    from recoup.agent.planner import MAX_REPLANS

    assert MAX_REPLANS >= 1
    client = _FakeLLM()
    agent = RecoveryAgent(client=client)
    action = agent.propose(_State(), _ctx(), now=T0)
    for _ in range(MAX_REPLANS + 3):
        action = agent.replan(action, _denial(), _State(), _ctx(), now=T0)
        if action is None:
            break
    assert action is None, "replanning must give up rather than loop"


# --- timing ----------------------------------------------------------------------


def test_send_time_is_offset_from_now_not_from_a_call_site_clock():
    action = RecoveryAgent(client=_FakeLLM()).propose(_State(), _ctx(), now=T0)
    assert action.send_at == T0 + timedelta(hours=2)
    assert action.send_at.tzinfo is not None


def test_an_absurd_delay_is_clamped_rather_than_trusted():
    agent = RecoveryAgent(
        client=_FakeLLM({
            "template_id": "TPL_RECOUP_WA_001",
            "hours_from_now": 100000,
            "variables": {"name": "Priya", "amount": "499"},
            "rationale": "x",
        })
    )
    action = agent.propose(_State(), _ctx(), now=T0)
    assert action.model_source == DETERMINISTIC


# --- the templates the planner may choose ---------------------------------------


def test_every_template_the_planner_offers_is_registered():
    from recoup.agent.planner import OFFERED_TEMPLATES

    assert OFFERED_TEMPLATES, "a planner offering no templates can propose nothing"
    for template_id in OFFERED_TEMPLATES:
        assert template_id in TEMPLATES
