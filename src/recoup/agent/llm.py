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
import re
import time
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


def _require_sdk(module: str, extra: str):
    """Import a model SDK, or say which extra installs it.

    The SDKs are optional extras imported lazily, so the suite runs with neither.
    The cost is that the first real call fails with a bare ModuleNotFoundError,
    which reads like broken code rather than a missing install — and the first
    real call is the one most likely to happen in front of someone.
    """
    from importlib import import_module

    try:
        return import_module(module)
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised by the planted test
        raise ModuleNotFoundError(
            f"{module} is not installed. It is an optional extra so the suite can "
            f'run without any model SDK: install it with `pip install -e ".[{extra}]"`. '
            f"The client is otherwise configured correctly — this is a missing "
            f"dependency, not a missing key."
        ) from exc


RATE_LIMIT_MAX_ATTEMPTS = 6  # ASSUMPTION: covers a ~5min stall at the observed 5 rpm free tier
RATE_LIMIT_FALLBACK_SECONDS = 30.0  # ASSUMPTION: used only when the 429 carries no retryDelay


class DailyQuotaExhausted(RuntimeError):
    """The per-DAY quota is gone. Waiting will not help; say so immediately."""


def _is_daily_quota(exc: Exception) -> bool:
    """True when the exhausted quota resets tomorrow rather than next minute.

    Google sends both limits as a plain 429 with a RetryInfo, and the RetryInfo
    on a per-day exhaustion still says ~59s -- which is true only in the sense
    that retrying then will also fail. The quotaId is the only thing that
    distinguishes them.
    """
    return "PerDay" in str(exc)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Seconds the server asked us to wait, or None if this is not a rate limit.

    Read out of the 429 body rather than guessed: Google returns a RetryInfo with
    the exact delay, and sleeping less than it just burns another request against
    the same quota.

    Raises rather than returning a wait when the exhausted quota is the DAILY
    one. Found the hard way: the first full eval spent 11m33s sleeping 59s at a
    time against `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, which had
    already given out all 20 of its requests for the day. A retry that cannot
    tell "wait a minute" from "come back tomorrow" turns a clear failure into a
    slow one.
    """
    if getattr(exc, "code", None) != 429 and "RESOURCE_EXHAUSTED" not in str(exc):
        return None
    if _is_daily_quota(exc):
        raise DailyQuotaExhausted(
            "the per-day free-tier quota is exhausted (20 requests/day for "
            "gemini-2.5-flash). Retrying cannot help: it resets on a daily "
            "boundary, not in the ~59s the RetryInfo suggests. Enable billing, "
            "or run the eval tomorrow and say in the report that it was not run "
            "today rather than reporting a partial one."
        ) from exc
    match = re.search(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'", str(exc))
    return float(match.group(1)) if match else RATE_LIMIT_FALLBACK_SECONDS


def call_through_rate_limit(send, *, sleep=time.sleep):
    """Call `send()`, waiting out 429s and re-raising everything else at once.

    Lifted out of the client so it can be tested with no SDK installed and no
    key. A retry loop living inside `classify_reply` would only ever be exercised
    on a machine that could reach the API, which is the one place the test would
    not run — and an untested retry loop is how a 500 comes to be retried six
    times before the error the caller needed arrives five minutes late.
    """
    for attempt in range(1, RATE_LIMIT_MAX_ATTEMPTS + 1):
        try:
            return send()
        except Exception as exc:
            wait = _retry_after_seconds(exc)
            if wait is None or attempt == RATE_LIMIT_MAX_ATTEMPTS:
                raise
            sleep(wait + 1.0)  # +1s: the server's delay is a floor, not a target
    raise AssertionError("unreachable: the loop either returns or raises")


class GeminiLLM:
    """Google Gemini via the AI Studio API.

    Structured output via a response schema — the model returns validated JSON or
    it is an error. Prose is never parsed, so a malformed answer is a validation
    failure rather than a plausible-looking string.

    Retries on 429 only. That is safe here and is NOT a licence to retry
    elsewhere: classification is a read with no side effect, so a duplicate call
    costs quota and nothing else. The opposite rule still governs anything that
    creates — a Payment Link create is never blind-retried (A-009), because there
    the duplicate is a second link, not a second opinion.
    """

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_GEMINI_MODEL) -> None:
        self._key = _require_key("GEMINI_API_KEY", api_key, ("AIza-xxxx", "your-key"))
        self.model = model

    @property
    def name(self) -> str:
        return self.model

    def classify_reply(self, text: str, today: str) -> dict:  # pragma: no cover - needs a key
        genai = _require_sdk("google.genai", "gemini")
        types = _require_sdk("google.genai.types", "gemini")

        from recoup.agent.prompts import REPLY_JSON_SCHEMA, REPLY_SYSTEM_PROMPT

        client = genai.Client(api_key=self._key)
        config = types.GenerateContentConfig(
            system_instruction=REPLY_SYSTEM_PROMPT.format(today=today),
            response_mime_type="application/json",
            response_schema=REPLY_JSON_SCHEMA,
            temperature=0.0,
        )

        response = call_through_rate_limit(
            lambda: client.models.generate_content(
                model=self.model, contents=text, config=config
            )
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
        anthropic = _require_sdk("anthropic", "anthropic")

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
