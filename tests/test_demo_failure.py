"""The staged veto: promotional drift, caught and replanned.

A-005 amended D-023. The original trigger was a quiet-hours violation, which is
**factually wrong**: a payment-failure notice is Service-Implicit under TCCCPR
2018, so it is 24x7 and DND-exempt. There is no quiet-hours violation to catch,
and staging one would be wrong on camera in front of people who know the rules.

Promotional drift is the better trigger anyway, because it is a failure mode only
a language model produces. Nobody writes "don't lose your 40% loyalty discount"
into a dunning template by hand; a model reaching for persuasion writes it every
time.
"""

import pytest

from recoup.demo import run_failure_demo
from recoup.ledger.store import Ledger


def test_the_demo_produces_a_veto_then_a_compliant_replan(tmp_path):
    result = run_failure_demo(Ledger(str(tmp_path / "demo.db")), run_id="demo")
    assert result["vetoed"] is True
    assert result["rule_id"] == "DLT-007"
    assert result["rule_class"] == "HARD_LAW"
    assert result["replanned_allowed"] is True


def test_the_denial_names_the_offending_token(tmp_path):
    """A veto that says 'not allowed' teaches nothing. It has to point."""
    result = run_failure_demo(Ledger(str(tmp_path / "d.db")), run_id="demo")
    assert result["offending_token"] in result["original_body"].lower()


def test_the_denial_carries_its_source(tmp_path):
    """A-006: a rule without a source does not ship, and the demo shows the
    source rather than asserting the rule exists."""
    result = run_failure_demo(Ledger(str(tmp_path / "d.db")), run_id="demo")
    assert result["source_url"].startswith("http")


def test_both_the_veto_and_the_replan_are_in_the_ledger(tmp_path):
    ledger = Ledger(str(tmp_path / "d2.db"))
    run_failure_demo(ledger, run_id="demo")
    types = [r["event_type"] for r in ledger.rows("demo")]
    assert "policy.denied" in types
    assert "agent.replanned" in types
    assert types.index("policy.denied") < types.index("agent.replanned")


def test_the_replanned_message_is_actually_sendable(tmp_path):
    """Not 'the second attempt was allowed' — the second attempt is checked by
    the same engine, and its body is checked against the registry."""
    from recoup.render.templates import body_matches

    result = run_failure_demo(Ledger(str(tmp_path / "d3.db")), run_id="demo")
    assert body_matches(result["replanned_template_id"], result["replanned_body"])


def test_the_replan_carries_no_promotional_token(tmp_path):
    from recoup.policy.predicates import contains_promotional_tokens

    result = run_failure_demo(Ledger(str(tmp_path / "d4.db")), run_id="demo")
    assert contains_promotional_tokens(result["replanned_body"]) is None


def test_the_demo_is_deterministic(tmp_path):
    """It runs on camera. A demo that varies is a demo that can surprise you."""
    a = run_failure_demo(Ledger(str(tmp_path / "a.db")), run_id="d")
    b = run_failure_demo(Ledger(str(tmp_path / "b.db")), run_id="d")
    assert a["rule_id"] == b["rule_id"]
    assert a["original_body"] == b["original_body"]
    assert a["replanned_body"] == b["replanned_body"]


def test_the_demo_needs_no_model(tmp_path):
    """The staged body is a fixture of what a model produces, not a live call.

    Deliberate: the demo must not depend on a key, a quota, or a model happening
    to reach for persuasion on the take. What it demonstrates is the ENGINE's
    response, and that is fully deterministic.
    """
    import inspect

    from recoup import demo

    source = inspect.getsource(demo)
    assert "client" not in source or "no model" in source.lower()
    run_failure_demo(Ledger(str(tmp_path / "d5.db")), run_id="d")  # no key set


def test_the_staged_body_would_really_be_written_by_a_model(tmp_path):
    """Guards the fixture, not the engine.

    If the staged text were something no model would produce, the demo would be
    theatre — a veto of a strawman. It is checked against the promotional token
    list that the rule itself uses, so the two cannot drift apart.
    """
    from recoup.policy.predicates import PROMOTIONAL_TOKENS, contains_promotional_tokens

    result = run_failure_demo(Ledger(str(tmp_path / "d6.db")), run_id="d")
    hit = contains_promotional_tokens(result["original_body"])
    assert hit is not None
    assert any(t in result["original_body"].lower() for t in PROMOTIONAL_TOKENS)


def test_a_second_run_into_the_same_ledger_does_not_corrupt_the_chain(tmp_path):
    """It gets run twice on camera when something goes wrong the first time."""
    from recoup.ledger.verify import verify_chain

    ledger = Ledger(str(tmp_path / "twice.db"))
    run_failure_demo(ledger, run_id="d")
    run_failure_demo(ledger, run_id="d")
    assert verify_chain(ledger).ok


@pytest.mark.parametrize("run_id", ["demo", "recorded-take-3"])
def test_the_rows_carry_the_run_id_they_were_given(tmp_path, run_id):
    ledger = Ledger(str(tmp_path / f"{run_id}.db"))
    run_failure_demo(ledger, run_id=run_id)
    assert {r["run_id"] for r in ledger.rows(run_id)} == {run_id}
