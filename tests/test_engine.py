import pathlib
import re
from datetime import UTC, datetime

import pytest
import yaml

from recoup.ledger.replay import SubscriptionState
from recoup.models import Action
from recoup.policy.engine import (
    CONTEXT_CALLABLES,
    CONTEXT_SCHEMA,
    CONTEXT_VALUES,
    PolicyEngine,
    PolicyRuleError,
    validate_predicate,
)

_REPO = pathlib.Path(__file__).resolve().parents[1]
RULES = str(_REPO / "src" / "recoup" / "policy" / "rules.yaml")


@pytest.fixture
def engine():
    return PolicyEngine(RULES)


def _action(**kw) -> Action:
    base = dict(
        action_type="send_message",
        channel="whatsapp",
        body="Your payment of Rs 499 could not be processed. Tap to retry: {link}",
        send_at=datetime(2026, 9, 1, 14, 0, tzinfo=UTC),
        attempt_no=1,
        cost_paise=12,
        wa_template_category="UTILITY",
        dlt_template_id="TPL_001",
        dlt_template_approved=True,
        body_matches_registered_template=True,
        uses_rzp_reminder=False,
    )
    base.update(kw)
    return Action(**base)


def _state(**kw) -> SubscriptionState:
    st = SubscriptionState(subscription_id="sub_1", customer_id="cust_1", arm="treatment")
    for k, v in kw.items():
        setattr(st, k, v)
    return st


NOW = datetime(2026, 9, 1, tzinfo=UTC)


# --- the happy path and the cases the demo turns on --------------------------------


def test_a_compliant_action_is_allowed(engine):
    verdict = engine.evaluate(_action(), _state(), now=NOW)
    assert verdict.allowed is True, verdict.denials
    assert verdict.denials == []


def test_service_implicit_at_2340_is_allowed(engine):
    """SI messages are 24x7 and DND-exempt. A quiet-hours veto here would be
    a self-inflicted, non-legal constraint -- and factually wrong."""
    action = _action(send_at=datetime(2026, 9, 1, 18, 10, tzinfo=UTC))  # 23:40 IST
    verdict = engine.evaluate(action, _state(), now=NOW)
    assert verdict.allowed is True, verdict.denials


def test_promotional_drift_is_vetoed(engine):
    """THE staged failure demo (A-005)."""
    action = _action(body="Payment failed. Don't lose your 40% loyalty discount, upgrade now!")
    verdict = engine.evaluate(action, _state(), now=NOW)

    assert verdict.allowed is False
    assert "DLT-007" in verdict.rule_ids

    denial = next(d for d in verdict.denials if d.rule_id == "DLT-007")
    assert denial.rule_class == "HARD_LAW"
    assert denial.source_url.startswith("http")
    assert "discount" in denial.detail.lower()


def test_promotional_drift_also_loses_service_implicit_status(engine):
    """The drift costs the SI classification, which is the point of the demo.

    Vetoing only on the token would understate it: the message stops being
    24x7-eligible at the same moment, so a late-evening send picks up a second
    veto it would not otherwise have had.
    """
    late = datetime(2026, 9, 1, 18, 10, tzinfo=UTC)  # 23:40 IST
    clean = engine.evaluate(_action(send_at=late), _state(), now=NOW)
    drifted = engine.evaluate(
        _action(send_at=late, body="Payment failed. Claim your discount now"),
        _state(), now=NOW,
    )
    assert clean.allowed is True
    assert {"DLT-003", "DLT-007", "DLT-004"} & set(drifted.rule_ids)


def test_an_unregistered_template_is_vetoed(engine):
    verdict = engine.evaluate(_action(dlt_template_approved=False), _state(), now=NOW)
    assert verdict.allowed is False
    assert "DLT-001" in verdict.rule_ids


def test_a_marketing_category_whatsapp_template_is_vetoed(engine):
    verdict = engine.evaluate(_action(wa_template_category="MARKETING"), _state(), now=NOW)
    assert "WA-002" in verdict.rule_ids


def test_opt_out_is_absolute(engine):
    verdict = engine.evaluate(_action(), _state(opted_out=True), now=NOW)
    assert verdict.allowed is False
    assert "STOP-003" in verdict.rule_ids


def test_the_attempt_cap_stops_the_agent(engine):
    state = _state()
    state.attempts_seen = {1, 2, 3, 4, 5}
    verdict = engine.evaluate(_action(attempt_no=6), state, now=NOW)
    assert "STOP-001" in verdict.rule_ids


def test_the_spend_cap_stops_the_agent(engine):
    state = _state()
    state.spend_by_attempt = {1: 5000}
    verdict = engine.evaluate(_action(), state, now=NOW)
    assert "STOP-002" in verdict.rule_ids


def test_a_promise_to_pay_suppresses_contact_until_the_day_after(engine):
    state = _state(ptp_date="2026-09-03")
    before = engine.evaluate(_action(), state, now=NOW)
    after = engine.evaluate(_action(), state, now=datetime(2026, 9, 4, tzinfo=UTC))

    assert "STOP-004" in before.rule_ids
    assert "STOP-004" not in after.rule_ids


def test_voice_outside_the_adopted_window_is_vetoed(engine):
    # 18:10 UTC = 23:40 IST. RBI-005, adopted voluntarily.
    action = _action(channel="voice", send_at=datetime(2026, 9, 1, 18, 10, tzinfo=UTC))
    verdict = engine.evaluate(action, _state(), now=NOW)
    denial = next(d for d in verdict.denials if d.rule_id == "RBI-005")
    assert denial.rule_class == "BEST_PRACTICE_BY_ANALOGY"


def test_coercive_copy_is_vetoed_by_the_rbi_rule(engine):
    verdict = engine.evaluate(
        _action(body="Pay immediately or we will take legal action"), _state(), now=NOW
    )
    assert "RBI-005" in verdict.rule_ids


def test_every_denial_carries_its_class_and_source(engine):
    action = _action(body="40% discount, upgrade now!", dlt_template_approved=False)
    verdict = engine.evaluate(action, _state(), now=NOW)

    assert verdict.denials
    for denial in verdict.denials:
        assert denial.rule_class in {
            "HARD_LAW", "INDUSTRY_PRACTICE", "BEST_PRACTICE_BY_ANALOGY", "SELF_IMPOSED",
        }
        assert denial.detail, f"{denial.rule_id} has no detail"
        if denial.rule_class != "SELF_IMPOSED":
            assert denial.source_url.startswith("http")


def test_the_baseline_arm_passes_through_the_same_engine(engine):
    """D-015: identical path, only the decision module differs. Otherwise the
    measured lift reflects infrastructure quality, not agent quality."""
    action = _action(body="Payment failed. Pay here: {link}")
    verdict = engine.evaluate(action, _state(arm="control"), now=NOW)
    assert verdict.allowed is True, verdict.denials


def test_a_wait_action_is_not_judged_as_a_message(engine):
    # `wait` sends nothing, so template and channel rules must not veto it.
    verdict = engine.evaluate(
        _action(action_type="wait", channel="none", body="", dlt_template_id=None,
                dlt_template_approved=False, body_matches_registered_template=False),
        _state(), now=NOW,
    )
    assert verdict.allowed is True, verdict.denials


# --- the rules must actually be DATA ------------------------------------------------
# The plan's engine re-implemented every rule in Python while rules.yaml carried
# `predicate` strings that nothing evaluated. That is the INC-005 shape inside the
# one file whose claim is "auditable without reading Python": an auditor would be
# reading a document that does not drive the system.


def test_every_rule_in_the_file_is_evaluated(engine):
    """No rule may be silently unused.

    A rule present in the file and absent from the engine is a compliance claim
    with no enforcement behind it.
    """
    on_disk = {r["id"] for r in yaml.safe_load(open(RULES, encoding="utf-8"))["rules"]}
    assert engine.evaluated_rule_ids() == on_disk


def test_editing_a_predicate_in_the_file_changes_the_verdict(tmp_path):
    """The proof that rules are data.

    If this passes with the predicate rewritten and the Python untouched, the
    YAML is genuinely the source of truth. If it fails, the file is documentation
    pretending to be configuration.
    """
    doc = yaml.safe_load(open(RULES, encoding="utf-8"))
    for rule in doc["rules"]:
        if rule["id"] == "STOP-001":
            rule["predicate"] = "state.attempts < 1"  # was < 5
    edited = tmp_path / "rules.yaml"
    edited.write_text(yaml.safe_dump(doc), encoding="utf-8")

    state = _state()
    state.attempts_seen = {1, 2}  # 2 attempts: under 5, over 1

    assert "STOP-001" not in PolicyEngine(RULES).evaluate(_action(), state, now=NOW).rule_ids
    assert "STOP-001" in PolicyEngine(str(edited)).evaluate(_action(), state, now=NOW).rule_ids


# --- the context contract, validated at LOAD time -----------------------------------


def test_the_schema_and_the_runtime_context_agree_in_both_directions(engine):
    """A schema that has drifted from the context is a declared thing with no consumer.

    A field in the context but not the schema is unreachable by any rule. A field
    in the schema but not the context passes load-time validation and then fails
    at evaluation — which is exactly the arrival-time problem load validation
    exists to remove.
    """
    ctx = engine._context(_action(), _state(), now=NOW)

    assert set(CONTEXT_SCHEMA) | CONTEXT_VALUES | CONTEXT_CALLABLES == set(ctx)

    for root, allowed in CONTEXT_SCHEMA.items():
        actual = set(vars(ctx[root]))
        assert actual == set(allowed), (
            f"{root}: schema {sorted(allowed)} vs context {sorted(actual)}"
        )


def test_every_shipped_predicate_passes_validation():
    doc = yaml.safe_load(open(RULES, encoding="utf-8"))
    for rule in doc["rules"]:
        validate_predicate(rule["id"], rule["predicate"])


@pytest.mark.parametrize(
    "predicate,fragment",
    [
        ("state.no_such_field < 5", "state.no_such_field"),
        ("msg.is_coersive", "msg.is_coersive"),          # the RBI-005 typo, one letter out
        ("nonexistent.attempts < 5", "'nonexistent'"),
        ("banana", "'banana'"),
        ("__import__", "'__import__'"),
        ("__import__('os')", "other than"),
        ("ist_hour(msg.send_at) < 5", "other than"),      # a helper not in the contract
        ("state.ptp_date.year > 2020", "chained attribute"),
        ("[x for x in (1, 2)]", "not one of the permitted"),
        ("state.attempts <", "does not parse"),
    ],
    ids=[
        "unknown-field", "typo'd-field", "unknown-root", "bare-name", "dunder-name",
        "dunder-call", "uncontracted-call", "chained-attribute", "comprehension",
        "syntax-error",
    ],
)
def test_a_predicate_outside_the_contract_is_refused_at_load(predicate, fragment):
    with pytest.raises(PolicyRuleError, match=re.escape(fragment)):
        validate_predicate("TEST-001", predicate)


def test_the_rbi_005_class_is_now_a_load_time_error(tmp_path):
    """The exact defect A-019 recorded, made impossible rather than unlikely.

    RBI-005 read `not msg.is_coercive` while nothing defined `is_coercive`. That
    clause could never be false, and no test noticed because the rule still
    denied on its other clause. With load-time name checking, the same mistake
    stops the engine from being constructed at all.
    """
    doc = yaml.safe_load(open(RULES, encoding="utf-8"))
    for rule in doc["rules"]:
        if rule["id"] == "RBI-005":
            rule["predicate"] = rule["predicate"].replace("is_coercive", "is_coersive")
    broken = tmp_path / "rules.yaml"
    broken.write_text(yaml.safe_dump(doc), encoding="utf-8")

    with pytest.raises(PolicyRuleError, match="RBI-005"):
        PolicyEngine(str(broken))


def test_load_validation_covers_rules_that_no_action_would_reach(tmp_path):
    """The point of validating at load rather than on first use.

    SELF-001 only fires when a message has already been sent today. An action
    that never triggers it would, under lazy validation, sail past a broken
    predicate — for the whole batch.
    """
    doc = yaml.safe_load(open(RULES, encoding="utf-8"))
    for rule in doc["rules"]:
        if rule["id"] == "SELF-001":
            rule["predicate"] = "state.messages_yesterday < 1"
    broken = tmp_path / "rules.yaml"
    broken.write_text(yaml.safe_dump(doc), encoding="utf-8")

    with pytest.raises(PolicyRuleError, match="SELF-001"):
        PolicyEngine(str(broken))


def test_a_predicate_that_cannot_be_evaluated_fails_loudly(tmp_path):
    """A rule referencing a field the context lacks must not silently pass.

    Swallowing the error would turn a broken compliance rule into a green light,
    which is the worst available direction for this failure.
    """
    doc = yaml.safe_load(open(RULES, encoding="utf-8"))
    for rule in doc["rules"]:
        if rule["id"] == "STOP-001":
            rule["predicate"] = "state.nonexistent_field < 5"
    broken = tmp_path / "rules.yaml"
    broken.write_text(yaml.safe_dump(doc), encoding="utf-8")

    with pytest.raises(Exception, match="STOP-001"):
        PolicyEngine(str(broken)).evaluate(_action(), _state(), now=NOW)


def test_every_rule_has_a_detail_formatter(engine):
    """A denial without a specific detail is unactionable in a report."""
    missing = engine.rules_without_detail()
    assert not missing, f"rules with no detail formatter: {missing}"


def test_the_engine_refuses_a_rules_file_with_an_unknown_class(tmp_path):
    doc = yaml.safe_load(open(RULES, encoding="utf-8"))
    doc["rules"][0]["class"] = "PROBABLY_FINE"
    bad = tmp_path / "rules.yaml"
    bad.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="class"):
        PolicyEngine(str(bad))


def test_the_verdict_serialises_for_the_ledger(engine):
    verdict = engine.evaluate(_action(body="get your discount"), _state(), now=NOW)
    payload = verdict.as_ledger_payload()
    assert payload["allowed"] is False
    assert payload["denials"][0]["class"] in {"HARD_LAW", "INDUSTRY_PRACTICE"}

    from recoup.ledger.store import canonical_json

    canonical_json(payload)  # must not raise: it goes into a hashed ledger row
