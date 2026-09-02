"""The treatment arm's decision module: propose, and replan after a veto.

WHAT THE MODEL DECIDES
----------------------
Which registered template, which delay, and what goes in the variable slots.
Not the body. PLAN.md had `body: {"type": "string"}` in the tool schema, which
would let the model write copy -- and under DLT a body that does not match its
registered template is not sendable however well it reads. A planner emitting
free text emits unsendable actions, and if the compliance flag were asserted
rather than computed it would emit illegal ones that pass the check.

So the model chooses from `OFFERED_TEMPLATES` and `render()` computes whether
the result matches. The narrower job is the honest one.

WHAT HAPPENS WHEN THE MODEL RETURNS SOMETHING UNUSABLE
------------------------------------------------------
A deterministic action is produced so the batch continues -- but it is LABELLED
`model_source=DETERMINISTIC`, and `require_real_model()` refuses to report over
a run containing any. This matters more than it looks: by report time a fallback
and a model decision are the same shape, both just an Action that got sent. A
run where the model failed schema on half the subscriptions would otherwise be
presented as the agent's work. That is the INC-006 shape -- an artifact making a
claim about something with nothing behind it.

There is no fallback for a MISSING CLIENT. A run with no model configured must
not quietly become a second deterministic arm that is then compared against the
first and reported as lift.
"""

from datetime import datetime, timedelta

from recoup.agent.llm import DETERMINISTIC, LLMTransport
from recoup.agent.prompts import PLANNER_SYSTEM, REPLAN_SYSTEM
from recoup.models import Action
from recoup.render.templates import TemplateError, render

# The templates the planner may choose between. A subset of the registry: the
# control arm's TPL_BASELINE_001 is deliberately NOT offered, so the treatment
# arm cannot converge on being the control and report a lift of zero as a
# finding about outreach rather than about itself.
OFFERED_TEMPLATES: tuple[str, ...] = (
    "TPL_RECOUP_WA_001",
    "TPL_RECOUP_WA_002",
    "TPL_RECOUP_SMS_001",
    "TPL_RECOUP_SMS_002",
    "TPL_RECOUP_EMAIL_001",
)

# MEASURED -- India rate cards, same figures as the control arm uses. Kept in one
# shape in both places on purpose: a cost difference between arms would show up
# as a cost-per-recovery difference that is an artifact of the price list.
COST_PAISE: dict[str, int] = {"whatsapp": 12, "sms": 15, "email": 1, "none": 0}

# ASSUMPTION: a proposal further out than this is a model error rather than a
# plan. Two weeks is already past every published dunning window (Recurly: 90%
# of successful recoveries inside 10 days). Sweep range if ever swept: 168..720.
MAX_HOURS_FROM_NOW = 336

# ASSUMPTION: how many times the model may be asked to fix a vetoed action
# before the turn is abandoned. Without a bound, a model that keeps proposing
# the same vetoed thing loops forever inside one subscription's turn. Sweep
# range: 1..5.
MAX_REPLANS = 2

_ALLOWED_ACTION_TYPES = frozenset({"send_message", "stop", "wait"})


class RecoveryAgent:
    """Jobs 2-4: decide whether to act, what to send, and when."""

    def __init__(self, client: LLMTransport | None = None) -> None:
        self._client = client

    # ------------------------------------------------------------------- jobs
    def propose(self, state, context: dict, now: datetime) -> Action | None:
        if state.opted_out:
            return None
        # Stop when they pay. Same rule as the control -- a difference here would
        # be a difference in when the arms stop spending, not in decisioning.
        if getattr(state, "recovered_paise", 0) > 0:
            return None

        attempt_no = max(state.attempts_seen, default=0) + 1
        raw = self._call(PLANNER_SYSTEM, self._situation(state, context, attempt_no))
        return self._to_action(raw, attempt_no, context, now)

    def replan(self, action: Action, verdict, state, context: dict, now: datetime):
        """Re-propose after a veto, carrying the actual rules that fired.

        The attempt number does NOT advance: a veto is not an attempt. Counting
        it as one would let a replan loop burn through STOP-001's five-attempt
        ceiling without a single message going out.
        """
        replans = action.replans + 1
        if replans > MAX_REPLANS:
            return None

        denial_text = "\n".join(
            f"- {d.rule_id} [{d.rule_class}]: {d.detail}\n"
            f"  regulation: {d.reason}\n"
            f"  source: {d.source_url}"
            for d in verdict.denials
        )
        prompt = (
            f"{self._situation(state, context, action.attempt_no)}\n\n"
            f"You proposed template {action.dlt_template_id} on {action.channel}:\n"
            f"  {action.body}\n\n"
            f"The policy engine REJECTED it:\n{denial_text}\n\n"
            f"Propose a compliant alternative."
        )

        raw = self._call(REPLAN_SYSTEM, prompt)
        replanned = self._to_action(raw, action.attempt_no, context, now)
        if replanned is not None:
            replanned = replanned.model_copy(update={"replans": replans})
        return replanned

    # --------------------------------------------------------------- internals
    def _call(self, system: str, prompt: str) -> dict | None:
        if self._client is None:
            raise ValueError(
                "RecoveryAgent has no model client. There is deliberately no "
                "deterministic fallback for a missing client: a run with no model "
                "configured would quietly become a second deterministic arm, "
                "which would then be compared against the first and reported as "
                "the agent's lift."
            )
        return self._client.propose_action(system, prompt)

    def _situation(self, state, context: dict, attempt_no: int) -> str:
        return (
            f"Subscription {state.subscription_id} is halted.\n"
            f"Amount outstanding: Rs {context.get('amount_paise', 0) // 100}\n"
            f"Customer name: {context.get('customer_name', 'there')}\n"
            f"Original decline reason: {context.get('reason_code', 'unknown')}\n"
            f"Hard decline (needs a new payment method): "
            f"{context.get('is_hard_decline', False)}\n"
            f"Days since halt: {context.get('day_offset', 0)}\n"
            f"Attempts already made: {len(state.attempts_seen)}\n"
            f"Spent so far: {state.spend_paise} paise\n"
            f"This would be attempt {attempt_no}.\n"
            f"Templates you may choose: {', '.join(OFFERED_TEMPLATES)}"
        )

    def _to_action(
        self, raw: dict | None, attempt_no: int, context: dict, now: datetime
    ) -> Action | None:
        model = self._client.name if self._client is not None else DETERMINISTIC

        if not raw:
            return self._fallback(attempt_no, context, now, "model returned nothing")

        action_type = raw.get("action_type", "send_message")
        if action_type == "charge":
            # Not a fallback. D-030 is not a preference the model gets to test,
            # and a run where the model asked for a debit is a run to stop and
            # look at rather than one to quietly paper over.
            raise ValueError(
                "the model proposed action_type='charge'. Post-halt there is no "
                "mandate and no code path may initiate a debit (D-030)."
            )
        if action_type not in _ALLOWED_ACTION_TYPES:
            return self._fallback(
                attempt_no, context, now, f"unknown action_type {action_type!r}"
            )

        if action_type in {"stop", "wait"}:
            return Action(
                action_type=action_type,
                channel="none",
                body="",
                send_at=now,
                attempt_no=attempt_no,
                cost_paise=0,
                dlt_template_id=None,
                rationale=raw.get("rationale", ""),
                model_source=model,
            )

        hours = raw.get("hours_from_now", 0)
        if not isinstance(hours, int) or not 0 <= hours <= MAX_HOURS_FROM_NOW:
            return self._fallback(
                attempt_no, context, now, f"hours_from_now out of range: {hours!r}"
            )

        template_id = raw.get("template_id")
        if template_id not in OFFERED_TEMPLATES:
            return self._fallback(
                attempt_no, context, now, f"template {template_id!r} was not offered"
            )

        variables = dict(raw.get("variables") or {})
        variables.setdefault("link", "{link}")
        try:
            rendered = render(template_id, variables)
        except TemplateError as exc:
            return self._fallback(attempt_no, context, now, f"render refused: {exc}")

        if not rendered.matches_registered_template:
            return self._fallback(
                attempt_no, context, now, "rendered body did not match its template"
            )

        return Action(
            action_type="send_message",
            channel=rendered.channel,
            body=rendered.body,
            send_at=now + timedelta(hours=hours),
            attempt_no=attempt_no,
            cost_paise=COST_PAISE.get(rendered.channel, 0),
            wa_template_category="UTILITY",
            dlt_template_id=rendered.dlt_template_id,
            dlt_template_approved=True,
            body_matches_registered_template=rendered.matches_registered_template,
            uses_rzp_reminder=False,
            rationale=raw.get("rationale", ""),
            model_source=model,
        )

    def _fallback(
        self, attempt_no: int, context: dict, now: datetime, why: str
    ) -> Action:
        """A sendable action when the model returned nothing usable.

        Labelled DETERMINISTIC, so `require_real_model()` refuses to report over
        a run containing it. The batch continues; the CLAIM does not.
        """
        rendered = render(
            "TPL_RECOUP_WA_001",
            {
                "name": str(context.get("customer_name", "there")),
                "amount": str(context.get("amount_paise", 0) // 100),
                "link": "{link}",
            },
        )
        return Action(
            action_type="send_message",
            channel=rendered.channel,
            body=rendered.body,
            send_at=now + timedelta(hours=2),
            attempt_no=attempt_no,
            cost_paise=COST_PAISE[rendered.channel],
            wa_template_category="UTILITY",
            dlt_template_id=rendered.dlt_template_id,
            dlt_template_approved=True,
            body_matches_registered_template=rendered.matches_registered_template,
            rationale=f"fallback: {why}",
            model_source=DETERMINISTIC,
        )
