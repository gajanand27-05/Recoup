"""Inbound reply understanding — and the model boundary around it.

`ANTHROPIC_API_KEY` is not set, so **no real model has run**. The accuracy tests
are marked `llm` and are deselected by `-m "not llm"`, which is what CI runs.
That is reported as **built, not exercised** — different from done and different
from dropped.

The one thing that must not happen while the key is missing is a stand-in
producing output that reads like a real evaluation. That is the INC-006 class:
an artifact making a claim about something outside the repository with nothing
behind it. So the model is a named boundary and `require_real_model()` refuses
stub output, exactly as `require_declared_split()` refuses a mixed transport.
"""

import json
import pathlib

import pytest
from pydantic import ValidationError

from recoup.agent.llm import (
    ANTHROPIC,
    STUB,
    AnthropicLLM,
    ModelProvenanceError,
    StubLLM,
    require_real_model,
)
from recoup.agent.replies import (
    INTENTS,
    ReplyUnderstanding,
    deterministic_opt_out,
    understand_reply,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "replies_labelled.jsonl"


def load_fixtures():
    return [
        json.loads(line)
        for line in FIXTURES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --- deterministic layer: no LLM, must be exact ------------------------------------


@pytest.mark.parametrize("text", [
    "STOP", "stop", "Stop.", "UNSUBSCRIBE", "don't message me again",
    "do not contact me", "band karo", "band karo ye messages",
    "message mat bhejo", "remove me from your list",
])
def test_opt_out_is_caught_deterministically(text):
    assert deterministic_opt_out(text) is True


@pytest.mark.parametrize("text", [
    "will pay tomorrow", "I already paid", "stopped working yesterday",
    "this is not my number", "ok", "kal kar dunga pakka",
])
def test_normal_replies_are_not_false_opt_outs(text):
    """A false positive here silences a customer permanently.

    'stopped working yesterday' is the one to watch: a naive `stop` substring
    match would opt out a customer who was complaining about the service.
    """
    assert deterministic_opt_out(text) is False


def test_opt_out_runs_before_the_llm():
    """A regulatory hard stop must not depend on a model's comprehension.

    Passing client=None proves no API call is needed to reach this verdict — and
    with no key set, no API call is even possible.
    """
    result = understand_reply("STOP", client=None)
    assert result.intent == "opt_out"
    assert result.confidence == 1.0
    assert result.model_source == "deterministic"


def test_every_labelled_opt_out_is_caught_without_the_model():
    """The fixture's opt-outs must all be reachable deterministically.

    If any needed the model, the hard stop would depend on a key being present.
    """
    missed = [
        f["text"] for f in load_fixtures()
        if f["intent"] == "opt_out" and not deterministic_opt_out(f["text"])
    ]
    assert not missed, f"these opt-outs would need the model: {missed}"


def test_no_non_opt_out_fixture_trips_the_deterministic_matcher():
    false_positives = [
        f["text"] for f in load_fixtures()
        if f["intent"] != "opt_out" and deterministic_opt_out(f["text"])
    ]
    assert not false_positives, false_positives


# --- schema -------------------------------------------------------------------------


def test_the_schema_rejects_an_unknown_intent():
    with pytest.raises(ValidationError):
        ReplyUnderstanding(intent="nonsense", promised_date=None, confidence=0.9, evidence="")


@pytest.mark.parametrize("bad", ["3rd Sept", "2026-13-01", "2026-02-31", "01/09/2026", "tomorrow"])
def test_the_schema_rejects_a_malformed_date(bad):
    """A date the policy engine cannot compare is worse than none.

    STOP-004 does `today > state.ptp_date`. A phrase there would raise mid-batch,
    or worse, compare as a string and suppress contact for the wrong window.
    """
    with pytest.raises(ValidationError):
        ReplyUnderstanding(
            intent="promise_to_pay", promised_date=bad, confidence=0.9, evidence=""
        )


def test_the_schema_accepts_a_null_date_for_a_vague_promise():
    # "next month" is a promise with no determinable day. Inventing one would put
    # a fabricated date into a policy rule.
    ok = ReplyUnderstanding(
        intent="promise_to_pay", promised_date=None, confidence=0.8, evidence="next month"
    )
    assert ok.promised_date is None


def test_confidence_is_bounded():
    for bad in (-0.1, 1.5):
        with pytest.raises(ValidationError):
            ReplyUnderstanding(intent="unclear", confidence=bad, evidence="")


# --- the labelled fixture itself ------------------------------------------------------


def test_the_fixture_is_well_formed_and_labelled_before_any_model_ran():
    rows = load_fixtures()
    assert len(rows) >= 55, f"only {len(rows)} labelled replies"
    for row in rows:
        assert row["intent"] in INTENTS, row
        if row["promised_date"] is not None:
            ReplyUnderstanding(
                intent=row["intent"], promised_date=row["promised_date"],
                confidence=1.0, evidence="fixture",
            )


def test_the_fixture_covers_every_intent_with_enough_of_each():
    from collections import Counter

    counts = Counter(f["intent"] for f in load_fixtures())
    for intent in INTENTS:
        assert counts[intent] >= 6, f"{intent}: only {counts[intent]} examples"


def test_the_fixture_contains_hinglish_not_just_english():
    """Replies arrive in Hindi and Hinglish. An English-only eval would measure
    the easy half and report it as the whole."""
    hinglish_markers = (
        "kar dunga", "tarikh", "galat", "band karo", "paisa", "kal kar",
        "maine", "nahi", "mujhe", "kisi", "haan", "theek hai", "achha",
        "dekhta", "mat bhejo", "bhai", "agle mahine", "thoda", "kat gaye",
        "karta hu", "kar diya", "kya", "aa raha",
    )
    rows = [f["text"].lower() for f in load_fixtures()]
    hits = sum(any(m in t for m in hinglish_markers) for t in rows)
    assert hits >= 15, f"only {hits} Hinglish examples out of {len(rows)}"


# --- the model boundary ----------------------------------------------------------------


def test_a_real_client_refuses_to_exist_without_a_key(monkeypatch):
    """No silent fallback. This is the whole point of the boundary.

    A stub that quietly stands in when the key is missing is how a run with no
    model behind it comes to look real.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicLLM()


def test_a_placeholder_key_is_refused_too(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxxxxxxx")
    with pytest.raises(ValueError, match="placeholder"):
        AnthropicLLM()


def test_understand_reply_refuses_to_guess_without_a_client():
    with pytest.raises(ValueError, match="no LLM transport"):
        understand_reply("will pay tomorrow", client=None)


def test_stub_output_is_labelled_as_stub():
    result = understand_reply("will pay tomorrow", client=StubLLM(), today="2026-09-01")
    assert result.model_source == STUB
    assert result.confidence == 0.0, "a stub is never confident; it is not a model"
    assert "NOT a model" in result.evidence


def test_stub_output_cannot_be_reported():
    """`require_real_model` is to the model what `require_declared_split` is to
    the transport. Stub output exists to exercise plumbing, never to be a result."""
    results = [
        understand_reply(f["text"], client=StubLLM(), today="2026-09-01")
        for f in load_fixtures()[:10]
    ]
    with pytest.raises(ModelProvenanceError, match="stub"):
        require_real_model(results, run_id="run-19")


def test_an_empty_result_set_is_not_silently_reportable():
    with pytest.raises(ModelProvenanceError, match="no classifications"):
        require_real_model([], run_id="run-19")


def test_real_model_output_would_pass_the_gate():
    """The gate must be satisfiable, or it is a wall rather than a check."""
    passing = [
        ReplyUnderstanding(
            intent="unclear", confidence=0.5, evidence="x", model_source=ANTHROPIC
        )
    ]
    assert require_real_model(passing, run_id="run-19") == [ANTHROPIC]


def test_deterministic_opt_outs_also_fail_the_gate():
    """Deliberate. An opt-out needs no model, but a REPORTED accuracy figure
    computed over a set that includes them would be measuring the matcher, not
    the model — so the gate refuses them too and the caller must separate them.
    """
    mixed = [
        understand_reply("STOP", client=None),
        ReplyUnderstanding(intent="unclear", confidence=0.5, evidence="", model_source=ANTHROPIC),
    ]
    with pytest.raises(ModelProvenanceError, match="deterministic"):
        require_real_model(mixed, run_id="run-19")


# --- LLM eval (needs ANTHROPIC_API_KEY; NOT run in CI) ----------------------------------


@pytest.mark.llm
def test_intent_accuracy_meets_the_bar():  # pragma: no cover - needs a key
    fixtures = load_fixtures()
    client = AnthropicLLM()
    results = [understand_reply(f["text"], client=client, today="2026-09-01") for f in fixtures]
    require_real_model(results, run_id="task-19-eval")

    correct = sum(r.intent == f["intent"] for r, f in zip(results, fixtures, strict=True))
    accuracy = correct / len(fixtures)
    print(f"\nintent accuracy: {accuracy:.1%} ({correct}/{len(fixtures)})")
    assert accuracy >= 0.85


@pytest.mark.llm
def test_promise_to_pay_date_extraction_meets_the_bar():  # pragma: no cover - needs a key
    dated = [f for f in load_fixtures() if f["promised_date"]]
    client = AnthropicLLM()
    results = [understand_reply(f["text"], client=client, today="2026-09-01") for f in dated]
    require_real_model(results, run_id="task-19-eval")

    pairs = zip(results, dated, strict=True)
    correct = sum(r.promised_date == f["promised_date"] for r, f in pairs)
    accuracy = correct / len(dated)
    print(f"\ndate extraction: {accuracy:.1%} ({correct}/{len(dated)})")
    assert accuracy >= 0.80
