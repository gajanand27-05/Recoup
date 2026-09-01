"""The model boundary — the same discipline as the transport boundary.

`ANTHROPIC_API_KEY` is not set, so no real model has run. That is a perfectly
ordinary state for a build in progress, and it has exactly one dangerous failure
mode: **a stand-in producing output that reads like a real run.**

That is the INC-006 class again. There, the test suite wrote a fixture that the
manifest reported as a captured Razorpay payload. Here, a stub model could
produce reply classifications that a report presents as an evaluation result. In
both cases the artifact makes a claim about something outside the repository that
nothing behind it supports.

So the model is a NAMED boundary, exactly like `sim` vs `real`:

* Every `LLMTransport` carries a `name`.
* Every result records the `model_source` that produced it.
* `require_real_model()` raises rather than letting stub output be reported —
  mirroring `require_declared_split()`, and for the same reason.
* **There is no silent fallback.** Constructing `AnthropicLLM` without a key
  raises. A stub that quietly stands in when the key is missing is precisely how
  a plausible-looking run with no model behind it gets made.

`StubLLM` exists to exercise the plumbing — schema validation, the deterministic
opt-out path, the shape of a result — and for nothing else.
"""

import os
from typing import Protocol

STUB = "stub"
ANTHROPIC = "anthropic"

# The model id is fixed here rather than at call sites so a report can state
# which model produced a number without going looking.
MODEL_ID = "claude-sonnet-5"


class LLMTransport(Protocol):
    @property
    def name(self) -> str:
        """`anthropic` or `stub`. Recorded on every result it produces."""
        ...

    def classify_reply(self, text: str, today: str) -> dict: ...


class AnthropicLLM:
    """The real model. Structured output via tool-use, validated by Pydantic.

    Never parses prose: the model is asked for a tool call and the arguments are
    validated, so a malformed answer is a validation error rather than a
    plausible-looking string.
    """

    name = ANTHROPIC

    def __init__(self, api_key: str | None = None, model: str = MODEL_ID) -> None:
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not key or key.startswith("sk-ant-xxxx"):
            raise ValueError(
                "ANTHROPIC_API_KEY is not set (or is still the .env placeholder). "
                "Refusing to construct a real-model client without one. There is "
                "deliberately no fallback to StubLLM here: a stub that quietly "
                "stands in is how a run with no model behind it comes to look real."
            )
        self._key = key
        self.model = model

    def classify_reply(self, text: str, today: str) -> dict:  # pragma: no cover
        # Not exercised: no key. Written now so the only missing input is the key.
        import anthropic

        from recoup.agent.prompts import REPLY_SYSTEM_PROMPT, REPLY_TOOL

        client = anthropic.Anthropic(api_key=self._key)
        response = client.messages.create(
            model=self.model,
            max_tokens=512,
            system=REPLY_SYSTEM_PROMPT.format(today=today),
            tools=[REPLY_TOOL],
            tool_choice={"type": "tool", "name": REPLY_TOOL["name"]},
            messages=[{"role": "user", "content": text}],
        )
        for block in response.content:
            if block.type == "tool_use":
                return dict(block.input)
        raise ValueError("model returned no tool call; refusing to parse prose")


class StubLLM:
    """Deterministic stand-in. **Its output may never appear in the report.**

    It exists to exercise the plumbing — schema validation, the deterministic
    opt-out path, the shape of a result. It classifies by keyword, which is not
    an approximation of the model's behaviour and is not meant to be: making it
    *look* good would make its output easier to mistake for a real evaluation.
    """

    name = STUB

    def classify_reply(self, text: str, today: str) -> dict:
        low = text.lower()
        if any(w in low for w in ("already paid", "pay kar diya", "kar diya tha")):
            intent = "already_paid"
        elif any(w in low for w in ("not my number", "galat number", "wrong number")):
            intent = "wrong_number"
        elif any(w in low for w in ("cancel", "dispute", "galat hai")):
            intent = "dispute"
        elif any(w in low for w in ("pay", "paisa", "salary", "tarikh")):
            intent = "promise_to_pay"
        else:
            intent = "unclear"
        return {
            "intent": intent,
            "promised_date": None,
            "confidence": 0.0,  # a stub is never confident; it is not a model
            "evidence": "stub keyword match — NOT a model classification",
        }


class ModelProvenanceError(RuntimeError):
    """Stub output reached something that reports numbers."""


def require_real_model(results, *, run_id: str):
    """Gate any reported figure on it having come from a real model.

    Mirrors `eval.transport_split.require_declared_split()`. Deliberately
    awkward to bypass: the caller either satisfies it or handles the exception,
    and either way somebody has considered where the numbers came from.
    """
    sources = {getattr(r, "model_source", None) for r in results}
    if not results:
        raise ModelProvenanceError(
            f"run {run_id!r} produced no classifications; nothing to report"
        )
    if sources - {ANTHROPIC}:
        raise ModelProvenanceError(
            f"run {run_id!r} contains output from {sorted(s or 'unknown' for s in sources)}. "
            f"Only {ANTHROPIC!r} output may appear as a result. Stub output exists to "
            f"exercise the plumbing, and a number derived from it would be a claim "
            f"about a model that never ran."
        )
    return sorted(sources)
