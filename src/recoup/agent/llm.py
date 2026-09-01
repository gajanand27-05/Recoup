"""The model boundary — the same discipline as the transport boundary.

A stand-in producing output that reads like a real run is the INC-006 class:
an artifact making a claim about something outside the repository with nothing
behind it. So the model is a NAMED boundary, exactly like `sim` vs `real`:

* Every `LLMTransport` carries a `name` that is the **specific model id**, not a
  vendor. `gemini-2.5-flash`, not `gemini`.
* Every result records the `model_source` that produced it.
* `require_real_model()` refuses stub and deterministic output, **and refuses to
  pool across models** — mirroring `require_declared_split()`.
* **There is no silent fallback.** Constructing a real client without a key
  raises. A stub that quietly stands in when the key is missing is precisely how
  a plausible-looking run with no model behind it gets made.

Why any real model, but never two at once
------------------------------------------
Which vendor is a free choice — nothing in this design depends on it, and the
structured-output discipline holds for any model that can be asked for a schema
rather than for prose.

What is *not* free is mixing them. **Two models are two instruments, not one
instrument with a setting.** A single accuracy figure computed over Gemini
results and Claude results measures neither, in exactly the way a recovery rate
pooled across `sim` and `real` transports would. So `require_real_model()`
returns the one model id it saw, and raises if it saw more than one.

`StubLLM` exists to exercise the plumbing — schema validation, the deterministic
opt-out path, the shape of a result — and for nothing else.
"""

import json
import os
from typing import Protocol

STUB = "stub"
DETERMINISTIC = "deterministic"

# Sources that are not a model's judgement. Never reportable as a model result.
NON_MODEL_SOURCES = frozenset({STUB, DETERMINISTIC})

# Default model. Reply classification is short-input, structured-output and
# high-volume, so the fast tier is the right one; the pro tier is the fallback if
# accuracy comes in under the pre-registered bar rather than the default.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"


class LLMTransport(Protocol):
    @property
    def name(self) -> str:
        """The specific model id. Recorded on every result it produces."""
        ...

    def classify_reply(self, text: str, today: str) -> dict: ...


class ModelProvenanceError(RuntimeError):
    """Output reached a reported figure that should not have."""


def require_real_model(results, *, run_id: str) -> str:
    """Gate a reported figure. Returns the one model id that produced it.

    Deliberately awkward to bypass: the caller either satisfies it or handles the
    exception, and either way somebody has considered where the numbers came from.
    """
    if not results:
        raise ModelProvenanceError(
            f"run {run_id!r} produced no classifications; nothing to report"
        )

    sources = {getattr(r, "model_source", None) for r in results}

    fake = sources & NON_MODEL_SOURCES
    if fake:
        raise ModelProvenanceError(
            f"run {run_id!r} contains {sorted(fake)} output. Stub output exists to "
            f"exercise the plumbing, and deterministic output is the opt-out matcher "
            f"rather than a model — a figure over either would be a claim about a "
            f"model that never made it."
        )

    unknown = {s for s in sources if not s}
    if unknown:
        raise ModelProvenanceError(
            f"run {run_id!r} contains results with no recorded model_source"
        )

    if len(sources) > 1:
        raise ModelProvenanceError(
            f"run {run_id!r} mixes {sorted(sources)}. Two models are two "
            f"instruments, not one instrument with a setting: a single figure over "
            f"both measures neither. Report per model, or run one model."
        )

    return next(iter(sources))


# --- real clients ------------------------------------------------------------------


def _require_key(env_var: str, supplied: str | None, placeholders: tuple[str, ...]) -> str:
    key = supplied or os.getenv(env_var, "")
    if not key or any(key.startswith(p) for p in placeholders):
        raise ValueError(
            f"{env_var} is not set (or is still the .env placeholder). Refusing to "
            f"construct a real-model client without one. There is deliberately no "
            f"fallback to StubLLM here: a stub that quietly stands in is how a run "
            f"with no model behind it comes to look real."
        )
    return key


class GeminiLLM:
    """Google Gemini via the AI Studio API.

    Structured output via a response schema — the model returns validated JSON or
    it is an error. Prose is never parsed, so a malformed answer is a validation
    failure rather than a plausible-looking string.
    """

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_GEMINI_MODEL) -> None:
        self._key = _require_key("GEMINI_API_KEY", api_key, ("AIza-xxxx", "your-key"))
        self.model = model

    @property
    def name(self) -> str:
        return self.model

    def classify_reply(self, text: str, today: str) -> dict:  # pragma: no cover - needs a key
        from google import genai
        from google.genai import types

        from recoup.agent.prompts import REPLY_JSON_SCHEMA, REPLY_SYSTEM_PROMPT

        client = genai.Client(api_key=self._key)
        response = client.models.generate_content(
            model=self.model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=REPLY_SYSTEM_PROMPT.format(today=today),
                response_mime_type="application/json",
                response_schema=REPLY_JSON_SCHEMA,
                temperature=0.0,
            ),
        )
        raw = getattr(response, "text", None)
        if not raw:
            raise ValueError(
                f"{self.model} returned no content; refusing to guess at an intent"
            )
        return json.loads(raw)


class AnthropicLLM:
    """Anthropic via tool-use. Kept alongside Gemini: the boundary supports more
    than one real model and refuses to pool them, which is more useful than
    having only one."""

    def __init__(
        self, api_key: str | None = None, model: str = DEFAULT_ANTHROPIC_MODEL
    ) -> None:
        self._key = _require_key("ANTHROPIC_API_KEY", api_key, ("sk-ant-xxxx",))
        self.model = model

    @property
    def name(self) -> str:
        return self.model

    def classify_reply(self, text: str, today: str) -> dict:  # pragma: no cover - needs a key
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
    """Deterministic stand-in. **Its output may never appear in a reported figure.**

    It classifies by keyword, which is not an approximation of any model's
    behaviour and is not meant to be: making it *look* good would make its output
    easier to mistake for a real evaluation.
    """

    @property
    def name(self) -> str:
        return STUB

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
