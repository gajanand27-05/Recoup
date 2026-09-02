"""Inbound reply understanding — and the model boundary around it.

The accuracy tests are marked `llm` and deselected by default (`addopts` in
pyproject), so they need both a key and an opt-in `-m llm`, and CI never has one.

The one thing that must not happen while a key is missing is a stand-in producing
output that reads like a real evaluation. That is the INC-006 class: an artifact
making a claim about something outside the repository with nothing behind it. So
the model is a named boundary and `require_real_model()` refuses stub output,
exactly as `require_declared_split()` refuses a mixed transport.

**Any real model is permitted; two at once are not.** Which vendor is a free
choice — the structured-output discipline holds for anything that can be asked
for a schema rather than for prose. Mixing is not free: two models are two
instruments, and one figure over both measures neither.
"""

import json
import pathlib

import pytest
from pydantic import ValidationError

from recoup.agent.llm import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_GEMINI_MODEL,
    NON_MODEL_SOURCES,
    OLLAMA_MODELS,
    RATE_LIMIT_MAX_ATTEMPTS,
    STUB,
    AnthropicLLM,
    DailyQuotaExhausted,
    GeminiLLM,
    ModelProvenanceError,
    StubLLM,
    _retry_after_seconds,
    call_through_rate_limit,
    client_for,
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


def _configured_client():
    """The model named by RECOUP_LLM_MODEL, using whichever key is set.

    Used only by the `llm`-marked evals. Raises rather than falling back, so a
    missing key is a failed eval and never a quietly stubbed one.
    """
    from recoup.config import Settings

    return client_for(Settings().llm_model)


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


@pytest.mark.parametrize(
    "client,env",
    [(GeminiLLM, "GEMINI_API_KEY"), (AnthropicLLM, "ANTHROPIC_API_KEY")],
    ids=["gemini", "anthropic"],
)
def test_a_real_client_refuses_to_exist_without_a_key(client, env, monkeypatch):
    """No silent fallback. This is the whole point of the boundary.

    A stub that quietly stands in when the key is missing is how a run with no
    model behind it comes to look real.
    """
    monkeypatch.delenv(env, raising=False)
    with pytest.raises(ValueError, match=env):
        client()


@pytest.mark.parametrize(
    "client,env,placeholder",
    [
        (GeminiLLM, "GEMINI_API_KEY", "your-key-from-aistudio"),
        (AnthropicLLM, "ANTHROPIC_API_KEY", "sk-ant-xxxxxxxx"),
    ],
    ids=["gemini", "anthropic"],
)
def test_a_placeholder_key_is_refused_too(client, env, placeholder, monkeypatch):
    monkeypatch.setenv(env, placeholder)
    with pytest.raises(ValueError, match="placeholder"):
        client()


def test_a_client_names_the_specific_model_not_the_vendor(monkeypatch):
    """`gemini` cannot tell flash from pro, and those are different instruments."""
    monkeypatch.setenv("GEMINI_API_KEY", "real-looking-key")
    assert GeminiLLM().name == DEFAULT_GEMINI_MODEL
    assert GeminiLLM(model="gemini-2.5-pro").name == "gemini-2.5-pro"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    assert AnthropicLLM().name == DEFAULT_ANTHROPIC_MODEL


def test_the_default_model_is_the_fast_tier():
    # Reply classification is short-input, structured-output, high-volume.
    assert DEFAULT_GEMINI_MODEL == "gemini-2.5-flash"


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


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "claude-sonnet-5", "gemini-2.5-pro"])
def test_any_single_real_model_passes_the_gate(model):
    """Vendor is a free choice. The gate permits any real model and returns which.

    Nothing in this design depends on whose API is called — the
    structured-output discipline holds for any model that can be asked for a
    schema rather than for prose.
    """
    passing = [
        ReplyUnderstanding(intent="unclear", confidence=0.5, evidence="x", model_source=model)
    ]
    assert require_real_model(passing, run_id="run-19") == model


def test_two_models_in_one_figure_are_refused():
    """Two models are two instruments, not one instrument with a setting.

    A single accuracy figure over Gemini results and Claude results measures
    neither — the same category error as pooling `sim` and `real` transports.
    """
    mixed = [
        ReplyUnderstanding(intent="unclear", confidence=0.5, evidence="",
                           model_source="gemini-2.5-flash"),
        ReplyUnderstanding(intent="unclear", confidence=0.5, evidence="",
                           model_source="claude-sonnet-5"),
    ]
    with pytest.raises(ModelProvenanceError, match="two instruments"):
        require_real_model(mixed, run_id="run-19")


def test_two_tiers_of_the_same_vendor_are_also_refused():
    """flash and pro are different models. A vendor-level label would hide that."""
    mixed = [
        ReplyUnderstanding(intent="unclear", confidence=0.5, evidence="",
                           model_source="gemini-2.5-flash"),
        ReplyUnderstanding(intent="unclear", confidence=0.5, evidence="",
                           model_source="gemini-2.5-pro"),
    ]
    with pytest.raises(ModelProvenanceError, match="two instruments"):
        require_real_model(mixed, run_id="run-19")


def test_a_result_with_no_recorded_model_is_refused():
    orphan = [ReplyUnderstanding(intent="unclear", confidence=0.5, evidence="",
                                 model_source="")]
    with pytest.raises(ModelProvenanceError, match="no recorded model_source"):
        require_real_model(orphan, run_id="run-19")


def test_deterministic_opt_outs_also_fail_the_gate():
    """Deliberate. An opt-out needs no model, but a REPORTED accuracy figure
    computed over a set that includes them would be measuring the matcher, not
    the model — so the gate refuses them too and the caller must separate them.
    """
    mixed = [
        understand_reply("STOP", client=None),
        ReplyUnderstanding(
            intent="unclear", confidence=0.5, evidence="", model_source=DEFAULT_GEMINI_MODEL
        ),
    ]
    with pytest.raises(ModelProvenanceError, match="deterministic"):
        require_real_model(mixed, run_id="run-19")


# --- rate limiting ----------------------------------------------------------------------
#
# The free tier allows 5 requests/minute, found the hard way: the first live eval
# got 5 fixtures in and then every remaining call 429'd. These tests run with no
# SDK and no key because `call_through_rate_limit` was lifted out of the client
# for exactly that reason — see its docstring.


class _FakeClientError(Exception):
    """Shaped like google.genai's ClientError: a `.code` and a repr'd body."""

    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code


_REAL_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': "
    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaValue': '5'}]}, "
    "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '46s'}]}}"
)

# Copied verbatim from the failure it describes, NOT hand-written to match the
# parser. The per-day RetryInfo still says ~59s, so anything reading only the
# delay treats "come back tomorrow" as "wait a minute" -- which is exactly what
# the first eval did, for 11m33s.
_REAL_429_PER_DAY = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': "
    "'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
    "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
    "'quotaDimensions': {'location': 'global', 'model': 'gemini-2.5-flash'}, "
    "'quotaValue': '20'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', "
    "'retryDelay': '59s'}]}}"
)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_FakeClientError(429, _REAL_429), 46.0),
        (_FakeClientError(429, "429 RESOURCE_EXHAUSTED. quota gone, no RetryInfo"), 30.0),
        (_FakeClientError(401, "401 UNAUTHENTICATED. invalid api key"), None),
        (_FakeClientError(500, "500 INTERNAL. something broke"), None),
    ],
    ids=["429-honours-retrydelay", "429-falls-back", "401-never-retried", "500-never-retried"],
)
def test_only_rate_limits_are_retried(exc, expected):
    """A 401 retried six times is five minutes of waiting for a wrong key."""
    assert _retry_after_seconds(exc) == expected


def test_a_rate_limited_call_is_retried_and_then_succeeds():
    slept: list[float] = []
    attempts = {"n": 0}

    def send():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _FakeClientError(429, _REAL_429)
        return "classified"

    assert call_through_rate_limit(send, sleep=slept.append) == "classified"
    assert attempts["n"] == 3
    assert slept == [47.0, 47.0]  # the server's 46s floor, plus a second


def test_a_non_rate_limit_error_is_raised_on_the_first_attempt():
    attempts = {"n": 0}

    def send():
        attempts["n"] += 1
        raise _FakeClientError(401, "401 UNAUTHENTICATED. invalid api key")

    with pytest.raises(_FakeClientError):
        call_through_rate_limit(send, sleep=lambda _: None)
    assert attempts["n"] == 1, "a bad key must fail now, not after six waits"


def test_a_daily_quota_is_not_slept_on():
    """The defect this test exists for cost 11m33s of sleeping before it raised."""
    slept: list[float] = []
    attempts = {"n": 0}

    def send():
        attempts["n"] += 1
        raise _FakeClientError(429, _REAL_429_PER_DAY)

    with pytest.raises(DailyQuotaExhausted, match="per-day"):
        call_through_rate_limit(send, sleep=slept.append)
    assert attempts["n"] == 1, "a daily quota must fail on the first attempt"
    assert slept == [], "no sleeping on a quota that resets tomorrow"


def test_a_per_minute_quota_is_still_slept_on():
    """The fix must not turn every 429 into a hard failure."""
    assert _retry_after_seconds(_FakeClientError(429, _REAL_429)) == 46.0


def test_retrying_gives_up_rather_than_waiting_forever():
    def send():
        raise _FakeClientError(429, _REAL_429)

    slept: list[float] = []
    with pytest.raises(_FakeClientError):
        call_through_rate_limit(send, sleep=slept.append)
    assert len(slept) == RATE_LIMIT_MAX_ATTEMPTS - 1


# --- LLM eval (needs the key for RECOUP_LLM_MODEL; NOT run in CI) -----------------------


@pytest.mark.llm
def test_intent_accuracy_meets_the_bar():  # pragma: no cover - needs a key
    """Accuracy over the MODEL-classified subset, not over all 60.

    The first run of this test failed at `require_real_model()`, and the guard was
    right. `deterministic_opt_out()` runs upstream of the model on purpose — a
    regulatory hard stop must not depend on a model's comprehension — so every
    opt-out fixture carries `model_source="deterministic"`. An "accuracy over 60"
    figure would have pooled two instruments and reported the number as the
    model's, which is the same category error as pooling `sim` and `real`.

    So the two are measured and printed separately. The deterministic matcher's
    correctness is already pinned exactly by
    `test_every_labelled_opt_out_is_caught_without_the_model`; what is unknown,
    and what this measures, is the model's.
    """
    fixtures = load_fixtures()
    client = _configured_client()
    results = [understand_reply(f["text"], client=client, today="2026-09-01") for f in fixtures]

    pairs = list(zip(results, fixtures, strict=True))
    by_model = [(r, f) for r, f in pairs if r.model_source not in NON_MODEL_SOURCES]
    deterministic = [(r, f) for r, f in pairs if r.model_source in NON_MODEL_SOURCES]

    model_id = require_real_model([r for r, _ in by_model], run_id="task-19-eval")

    det_correct = sum(r.intent == f["intent"] for r, f in deterministic)
    correct = sum(r.intent == f["intent"] for r, f in by_model)
    accuracy = correct / len(by_model)

    print("\n--- reply understanding eval -------------------------------")
    print(f"model                : {model_id}")
    print(f"fixtures             : {len(fixtures)}")
    print(f"handled deterministic: {len(deterministic)} "
          f"({det_correct}/{len(deterministic)} correct) -- opt-out matcher, not the model")
    print(f"classified by model  : {len(by_model)}")
    print(f"INTENT ACCURACY      : {accuracy:.1%} ({correct}/{len(by_model)})")

    wrong = [
        (f["text"][:40], f["intent"], r.intent)
        for r, f in by_model
        if r.intent != f["intent"]
    ]
    for text, expected, got in wrong:
        print(f"  MISS  {text!r:48} expected={expected:<15} got={got}")
    print("------------------------------------------------------------")

    assert accuracy >= 0.85


@pytest.mark.llm
def test_promise_to_pay_date_extraction_meets_the_bar():  # pragma: no cover - needs a key
    dated = [f for f in load_fixtures() if f["promised_date"]]
    client = _configured_client()
    results = [understand_reply(f["text"], client=client, today="2026-09-01") for f in dated]
    require_real_model(results, run_id="task-19-eval")

    pairs = list(zip(results, dated, strict=True))
    correct = sum(r.promised_date == f["promised_date"] for r, f in pairs)
    accuracy = correct / len(dated)
    print(f"\nDATE EXTRACTION      : {accuracy:.1%} ({correct}/{len(dated)})")
    for r, f in pairs:
        if r.promised_date != f["promised_date"]:
            print(f"  MISS  {f['text'][:40]!r:44} "
                  f"expected={f['promised_date']} got={r.promised_date}")
    assert accuracy >= 0.80


# --- Ollama Cloud: the schema is NOT enforced by the provider (A-024) ---------------


def test_the_router_knows_every_configured_model():
    """A router that quietly picks a default is how a run measures a model nobody
    chose. An unrecognised id must raise, not fall through."""
    with pytest.raises(ValueError, match="no known client"):
        client_for("some-model-nobody-configured")


def test_the_router_refuses_an_ollama_typo():
    """`gpt-oss:120B` is not `gpt-oss:120b`. Falling through to a request for a
    model that does not exist wastes a batch to find out."""
    with pytest.raises(ValueError, match="no known client"):
        client_for("gpt-oss:120B")


@pytest.mark.parametrize("model", sorted(OLLAMA_MODELS))
def test_an_ollama_client_refuses_to_exist_without_a_key(model, monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OLLAMA_API_KEY"):
        client_for(model)


def test_an_ollama_client_reports_the_specific_model_id(monkeypatch):
    """Not 'ollama'. The vendor cannot tell 120b from 20b, and those are two
    instruments -- require_real_model() refuses to pool them."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key-not-real")
    assert client_for("gpt-oss:120b").name == "gpt-oss:120b"
    assert client_for("ollama/gpt-oss:20b").name == "gpt-oss:20b"


def test_two_ollama_tiers_are_refused_as_one_figure(monkeypatch):
    from types import SimpleNamespace

    results = [
        SimpleNamespace(model_source="gpt-oss:120b"),
        SimpleNamespace(model_source="gpt-oss:20b"),
    ]
    with pytest.raises(ModelProvenanceError, match="two instruments"):
        require_real_model(results, run_id="run-ollama-mixed")
