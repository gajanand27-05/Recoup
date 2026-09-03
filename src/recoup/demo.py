"""The staged failure: promotional drift, vetoed, replanned (D-023, amended by A-005).

WHY NOT QUIET HOURS
-------------------
The original design staged a quiet-hours violation. That is **factually wrong**.
A payment-failure notice is Service-Implicit under TCCCPR 2018, which makes it
24x7 and DND-exempt — there is no quiet-hours violation to catch, and staging one
would be wrong on camera in front of people who know the rules.

Promotional drift is the better trigger anyway. It is a failure mode only a
language model produces: nobody hand-writes "don't lose your 40% loyalty
discount" into a dunning template, and a model reaching for persuasion writes it
every time. The veto is not catching a typo, it is catching the thing the model
is *for*.

WHY THERE IS NO MODEL IN HERE
-----------------------------
The offending body is a FIXTURE of what a model produces, not a live call. This
runs on camera, and it must not depend on a key, a quota, or the model happening
to reach for persuasion on that take. What is being demonstrated is the ENGINE's
response, which is fully deterministic — so the demo is too.

`tests/test_demo_failure.py` guards the fixture as well as the engine: the staged
body is checked against the same `PROMOTIONAL_TOKENS` list the rule uses, so a
strawman cannot drift in.
"""

from datetime import UTC, datetime

from recoup.clock import to_iso_z
from recoup.ledger.store import Ledger
from recoup.models import Action
from recoup.policy.engine import PolicyEngine
from recoup.policy.predicates import contains_promotional_tokens
from recoup.render.templates import render

RULES_PATH = "src/recoup/policy/rules.yaml"

#: 11:00 IST — comfortably inside every send-window rule, so the veto is
#: unambiguously about CONTENT. A demo that fires on the clock as well as the
#: copy leaves the audience unsure which rule did the work.
DEMO_NOW = datetime(2026, 9, 3, 5, 30, tzinfo=UTC)

#: What a model writes when asked to recover a payment and left to its own
#: judgement about tone. Every promotional token here is in the list DLT-007
#: uses, and a test asserts that rather than trusting this comment.
DRIFTED_BODY = (
    "Hi Priya, your payment failed. Don't lose your 40% loyalty discount — "
    "upgrade now and save on your next renewal!"
)

DEMO_AMOUNT_PAISE = 49900


class _DemoState:
    """The minimum the engine reads. Not a `SubscriptionState`: this is staged,
    and borrowing the real type would imply a replay produced it."""

    subscription_id = "sub_demo_0001"
    customer_id = "cust_demo_0001"
    arm = "treatment"
    attempts_seen: set = frozenset({1})
    attempts = 1
    spend_paise = 12
    opted_out = False
    recovered_paise = 0
    ptp_date = None
    # ZERO, and this matters. With `messages_today = 1` the SELF-001 daily cap
    # vetoes everything, including the compliant replan -- so the demo would
    # show a veto, a replan, and a second veto, and the audience would learn
    # that the engine says no rather than that it says no TO THIS COPY. The
    # staged failure has to be about content and nothing else.
    messages_today = 0
    whatsapp_optin = True


def run_failure_demo(ledger: Ledger, *, run_id: str = "demo") -> dict:
    """Propose a drifted message, watch it vetoed, replan, and record both.

    Returns everything the narration needs, so the script reads values rather
    than restating them — a demo whose commentary is written separately from its
    output is a demo that can contradict itself live.
    """
    engine = PolicyEngine(RULES_PATH)
    state = _DemoState()

    # 1. What the model proposed. Free text, so it matches no registered
    #    template — `body_matches_registered_template` is COMPUTED as False
    #    rather than asserted, exactly as it would be in a real run.
    proposed = Action(
        action_type="send_message",
        channel="whatsapp",
        body=DRIFTED_BODY,
        send_at=DEMO_NOW,
        attempt_no=2,
        cost_paise=12,
        wa_template_category="UTILITY",
        dlt_template_id="TPL_RECOUP_WA_001",
        dlt_template_approved=True,
        body_matches_registered_template=False,
        model_source="staged-fixture",
        rationale="model reached for persuasion",
    )
    verdict = engine.evaluate(proposed, state, now=DEMO_NOW)

    # DLT-007 is the one the demo is about. Others may also fire — the body
    # matches no template, so DLT-008 fires too — and the narration names the
    # content rule specifically rather than whichever came first.
    denial = next(
        (d for d in verdict.denials if d.rule_id == "DLT-007"),
        verdict.denials[0] if verdict.denials else None,
    )
    token = contains_promotional_tokens(DRIFTED_BODY)

    ledger.append({
        "run_id": run_id,
        "ts": to_iso_z(DEMO_NOW),
        "event_type": "policy.denied",
        "subscription_id": state.subscription_id,
        "customer_id": state.customer_id,
        "arm": state.arm,
        "transport": "sim",
        "payload": {
            "body": DRIFTED_BODY,
            "denials": [d.rule_id for d in verdict.denials],
            "rule_id": denial.rule_id if denial else None,
            "rule_class": denial.rule_class if denial else None,
            "offending_token": token,
        },
    })

    # 2. The replan. Not "the model tried again" — the model does not get to
    #    write the body at all. It picks a REGISTERED template and the system
    #    fills the slots, which is why the second attempt cannot drift.
    rendered = render(
        "TPL_RECOUP_WA_001",
        {"name": "Priya", "amount": str(DEMO_AMOUNT_PAISE // 100), "link": "{link}"},
    )
    replanned = proposed.model_copy(update={
        "body": rendered.body,
        "dlt_template_id": rendered.dlt_template_id,
        "body_matches_registered_template": rendered.matches_registered_template,
        "rationale": "replanned onto a registered template after DLT-007",
        "replans": 1,
    })
    replanned_verdict = engine.evaluate(replanned, state, now=DEMO_NOW)

    ledger.append({
        "run_id": run_id,
        "ts": to_iso_z(DEMO_NOW),
        "event_type": "agent.replanned",
        "subscription_id": state.subscription_id,
        "customer_id": state.customer_id,
        "arm": state.arm,
        "transport": "sim",
        "payload": {
            "body": rendered.body,
            "dlt_template_id": rendered.dlt_template_id,
            "allowed": replanned_verdict.allowed,
        },
    })

    return {
        "vetoed": not verdict.allowed,
        "rule_id": denial.rule_id if denial else None,
        "rule_class": denial.rule_class if denial else None,
        "reason": denial.reason if denial else "",
        "detail": denial.detail if denial else "",
        "source_url": denial.source_url if denial else "",
        "all_denials": [d.rule_id for d in verdict.denials],
        "offending_token": token or "",
        "original_body": DRIFTED_BODY,
        "replanned_body": rendered.body,
        "replanned_template_id": rendered.dlt_template_id,
        "replanned_allowed": replanned_verdict.allowed,
    }


def narrate(result: dict) -> str:
    """The demo's own words, generated from its own output.

    Written here rather than in the video script so the commentary cannot
    contradict what the run actually did.
    """
    lines = [
        "The model proposed this:",
        f'  "{result["original_body"]}"',
        "",
        f"VETOED by {result['rule_id']} [{result['rule_class']}]",
        f"  {result['detail']}",
        f"  source: {result['source_url']}",
        "",
        f"The offending token is {result['offending_token']!r}. In India that is",
        "not a style note: promotional content in a service message forfeits",
        "Service-Implicit status, and with it 24x7 delivery and DND exemption.",
        "",
        "The agent does not know that. The policy engine does, and it sits",
        "outside the agent, so the agent cannot argue with it.",
        "",
        "Replanned onto a registered template:",
        f'  "{result["replanned_body"]}"',
        f"  allowed: {result['replanned_allowed']}",
    ]
    return "\n".join(lines)
