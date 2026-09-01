"""Inbound reply understanding.

Customer replies are untrusted input flowing into a model that informs money
actions. Two things follow, and the ordering of them is the point.

**Opt-out is matched deterministically, UPSTREAM of the model.** A regulatory
hard stop must never depend on a model's reading comprehension. `understand_reply`
reaches an opt-out verdict with `client=None` — no API call is required, and a
test passes exactly that to prove it.

**Every result records which model produced it.** A `ReplyUnderstanding` carries
`model_source`, and `llm.require_real_model()` refuses to let stub output reach
anything that reports numbers. See `llm.py` for why that boundary is named rather
than implicit.
"""

import re
from datetime import date

from pydantic import BaseModel, Field, field_validator

from recoup.agent.llm import DETERMINISTIC, LLMTransport

INTENTS = (
    "promise_to_pay",
    "opt_out",
    "already_paid",
    "wrong_number",
    "dispute",
    "unclear",
)

# Matched before the model runs. Deliberately narrow: a false positive here
# silences a customer permanently, so the patterns are ones that cannot mean
# anything else. Anything ambiguous is left to the model, which can only
# ever ADD an opt-out, never remove one.
#
# class: SELF_IMPOSED. TCCCPR requires honouring opt-out; it does not enumerate
# the words, and Indian replies arrive in English, Hindi and Hinglish.
HARD_OPT_OUT_PATTERNS: tuple[str, ...] = (
    r"^\s*stop\b",
    r"^\s*unsubscribe\b",
    r"\bdo\s*n[o']?t\s+(message|contact|text|call)\s+me\b",
    r"\bdon'?t\s+message\s+me\b",
    r"\bnever\s+(message|contact)\s+me\b",
    r"\bremove\s+me\s+from\b",
    r"\bband\s+kar(o|do|dijiye)\b",
    r"\bmat\s+bhejo\b",
    r"\bmessage\s+mat\b",
)

_OPT_OUT_RE = re.compile("|".join(HARD_OPT_OUT_PATTERNS), re.IGNORECASE)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ReplyUnderstanding(BaseModel):
    """What a reply meant, and which model said so."""

    intent: str = Field(pattern="^(" + "|".join(INTENTS) + ")$")
    promised_date: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""

    # Which model produced this — the SPECIFIC model id, not a vendor, because
    # `require_real_model()` refuses to pool across models and needs to be able
    # to tell `gemini-2.5-flash` from `gemini-2.5-pro`.
    #
    # `deterministic` for the pre-model opt-out path, which is the one verdict
    # that needs no model at all.
    model_source: str = DETERMINISTIC

    @field_validator("promised_date")
    @classmethod
    def _iso_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _ISO_DATE.match(value):
            raise ValueError(
                f"promised_date must be ISO-8601 (YYYY-MM-DD), got {value!r}. "
                "A date the policy engine cannot compare is worse than none."
            )
        date.fromisoformat(value)  # rejects 2026-02-31
        return value


def deterministic_opt_out(text: str) -> bool:
    """True if this reply is unambiguously an opt-out. No model involved."""
    return bool(_OPT_OUT_RE.search(text or ""))


def understand_reply(
    text: str,
    client: LLMTransport | None = None,
    today: str | None = None,
) -> ReplyUnderstanding:
    """Classify one inbound reply.

    Opt-out is decided first and without the model. If `client` is None and the
    reply is not an opt-out, this raises rather than guessing — there is no
    silent stub fallback, because a stand-in that quietly answers is how a run
    with no model behind it comes to look real.
    """
    if deterministic_opt_out(text):
        return ReplyUnderstanding(
            intent="opt_out",
            promised_date=None,
            confidence=1.0,
            evidence="matched a hard opt-out pattern upstream of any model",
            model_source=DETERMINISTIC,
        )

    if client is None:
        raise ValueError(
            "no LLM transport supplied and this reply is not a deterministic "
            "opt-out. Pass GeminiLLM() or AnthropicLLM() for a real "
            "classification, or StubLLM() to exercise the plumbing — but stub "
            "output may never be reported."
        )

    raw = client.classify_reply(text, today=today or date.today().isoformat())
    understanding = ReplyUnderstanding(**raw)
    # The transport names the specific model, and that name is what gets
    # recorded. Nothing here maps a vendor onto a generic label, because a
    # figure that says "gemini" cannot tell flash from pro.
    return understanding.model_copy(update={"model_source": client.name})
