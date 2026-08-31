"""Deterministic checkable functions used by the policy engine.

None of these call an LLM. The whole point of the veto layer is that it is
decidable without a model in the loop — a regulatory hard stop must never depend
on a model's reading comprehension.
"""

import re
from datetime import datetime, timedelta, timezone

# Tokens that reclassify a service message as promotional under TCCCPR.
# Source: https://msg91.com/help/dlt-content-template-faqs (retrieved 2026-08-28)
# class: INDUSTRY_PRACTICE -- operators scrub on content, and the published
# guidance names these categories rather than an exhaustive word list, so the
# specific tokens are our reading of it.
PROMOTIONAL_TOKENS: tuple[str, ...] = (
    "discount", "offer", "upgrade", "save", "sale", "deal", "free",
    "limited-time", "limited time", "exclusive", "refer", "referral",
    "bonus", "cashback", "coupon", "promo", "loyalty",
)

# Language that would make outreach coercive. RBI-005 reads "not msg.is_coercive",
# and without a definition that predicate can never be false -- the rule would be
# declared, evaluated, and incapable of firing.
#
# class: SELF_IMPOSED. RBI/2022-23/108 prohibits coercive practices without
# enumerating language, and it does not bind a SaaS merchant in any case. This
# list is our own reading of what "coercive" means in a dunning message.
COERCIVE_TOKENS: tuple[str, ...] = (
    "legal action", "lawyer", "court", "police", "agents", "recovery agent",
    "credit bureau", "cibil", "blacklist", "defaulter", "final warning",
    "seize", "consequences will",
)

IST = timezone(timedelta(hours=5, minutes=30))


def _word_matcher(tokens: tuple[str, ...]) -> re.Pattern:
    return re.compile(
        r"\b(" + "|".join(re.escape(t) for t in tokens) + r")\b", re.IGNORECASE
    )


_PROMO_RE = _word_matcher(PROMOTIONAL_TOKENS)
_COERCIVE_RE = _word_matcher(COERCIVE_TOKENS)


def contains_promotional_tokens(body: str | None) -> str | None:
    """Return the first offending token, or None.

    Word-boundary matched, so 'offer' does not fire on 'coffee'. This is the form
    `rules.yaml` calls, where only truthiness matters.
    """
    match = _PROMO_RE.search(body or "")
    return match.group(0) if match else None


def find_promotional_tokens(body: str | None) -> list[str]:
    """Every offending token, in order of appearance, de-duplicated.

    The denial detail names all of them rather than whichever the regex reached
    first. "Don't lose your loyalty discount, upgrade now" trips three tokens,
    and a veto that reports one understates what the model actually did — which
    matters, because this is the message that goes on camera.
    """
    seen: list[str] = []
    for match in _PROMO_RE.finditer(body or ""):
        token = match.group(0)
        if token.lower() not in {s.lower() for s in seen}:
            seen.append(token)
    return seen


def contains_coercive_tokens(body: str | None) -> str | None:
    match = _COERCIVE_RE.search(body or "")
    return match.group(0) if match else None


def classify_message(body: str | None) -> str:
    """SERVICE_IMPLICIT unless promotional content drags it out.

    This is the classification the whole compliance position rests on: SI is
    24x7 and DND-exempt, and promotional content forfeits both.
    """
    return "PROMOTIONAL" if contains_promotional_tokens(body) else "SERVICE_IMPLICIT"


def ist_hour(dt: datetime) -> int:
    """Hour of day in IST. Storage is always UTC; only display and policy convert.

    Naive datetimes are refused rather than assumed UTC. On a machine already set
    to IST, guessing puts every policy window five and a half hours off its
    boundary while looking entirely normal — the same reasoning as
    `clock.to_iso_z`.
    """
    if dt.tzinfo is None:
        raise ValueError(
            "refusing to convert a naive datetime to IST; attach a timezone. "
            "Assuming UTC here would move every policy window by 5h30m."
        )
    return dt.astimezone(IST).hour
