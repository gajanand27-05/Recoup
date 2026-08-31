"""The veto layer.

Sits OUTSIDE the agent. Every action from BOTH arms passes through it. An LLM
prompted to respect limits is a system with no limits; an LLM whose output is
validated by a separate deterministic component is a system with limits (D-014).

The rules really are data
-------------------------
`rules.yaml` carries a `predicate` for each rule, and **this engine evaluates
it**. It does not re-implement the rules in Python beside them.

That distinction is the whole value of the file. An engine that hard-codes the
logic while the YAML carries decorative predicate strings would let an auditor
read a document that does not drive the system — a rule could be edited, or be
plainly wrong, and nothing would change. Every rule in the file is evaluated, and
`test_editing_a_predicate_in_the_file_changes_the_verdict` proves the direction
of causation by rewriting a predicate and watching the verdict move.

Each denial carries the rule's legal class and source, so the report can group
vetoes by whether they were law or our own restraint.

Evaluation is deliberately strict
---------------------------------
A predicate that cannot be evaluated raises. Swallowing the error would turn a
broken compliance rule into a green light, which is the worst available direction
for this particular failure.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from types import SimpleNamespace

import yaml

from recoup.models import Action
from recoup.policy.predicates import (
    classify_message,
    contains_coercive_tokens,
    contains_promotional_tokens,
    find_promotional_tokens,
    ist_hour,
)

VALID_CLASSES = frozenset(
    {"HARD_LAW", "INDUSTRY_PRACTICE", "BEST_PRACTICE_BY_ANALOGY", "SELF_IMPOSED"}
)


@dataclass(frozen=True)
class Denial:
    rule_id: str
    rule_class: str
    reason: str
    detail: str
    source_url: str = ""


@dataclass
class Verdict:
    allowed: bool
    denials: list[Denial] = field(default_factory=list)

    @property
    def rule_ids(self) -> list[str]:
        return [d.rule_id for d in self.denials]

    def as_ledger_payload(self) -> dict:
        return {
            "allowed": self.allowed,
            "denials": [
                {
                    "rule_id": d.rule_id,
                    "class": d.rule_class,
                    "reason": d.reason,
                    "detail": d.detail,
                    "source_url": d.source_url,
                }
                for d in self.denials
            ],
        }


class PolicyEvaluationError(RuntimeError):
    """A rule could not be evaluated. Never treated as 'allowed'."""


# Per-rule detail. The predicate decides *whether* to deny; this says *why*, with
# the specific values involved, because "DLT-007 denied" is unactionable in a
# report. Kept in Python rather than in the YAML so the file stays free of
# format strings, and pinned by `test_every_rule_has_a_detail_formatter`.
_DETAIL = {
    "DLT-001": lambda c: "no approved DLT content template id on this message",
    "DLT-003": lambda c: (
        f"message classifies as {c['msg'].category}, not SERVICE_IMPLICIT; "
        f"promotional content forfeits 24x7 delivery and DND exemption"
    ),
    "DLT-004": lambda c: (
        f"send hour {c['msg'].send_hour_ist:02d}:00 IST is outside the 10:00-21:00 "
        f"window that applies to {c['msg'].category} messages"
    ),
    "DLT-007": lambda c: (
        "body contains promotional token(s) "
        + ", ".join(f"'{t}'" for t in find_promotional_tokens(c["msg"].body))
        + ", which reclassifies this message from SERVICE_IMPLICIT to PROMOTIONAL "
        "and forfeits 24x7 delivery and DND exemption"
    ),
    "DLT-008": lambda c: "message body does not match a registered DLT template",
    "WA-002": lambda c: (
        f"WhatsApp template category is {c['msg'].wa_template_category}, "
        f"must be UTILITY for a payment-failure notice"
    ),
    "WA-003": lambda c: "no recorded WhatsApp opt-in for this customer",
    "RZP-001": lambda c: (
        f"payment link already has {c['link'].reminder_count} reminders; "
        f"Razorpay permits at most 3 and silently drops the rest"
    ),
    "RZP-002": lambda c: (
        f"Razorpay sends reminders only 11:00-12:00 and 15:00-17:00 IST; "
        f"{c['action'].send_hour_ist:02d}:00 would silently do nothing"
    ),
    "RBI-005": lambda c: (
        (
            f"body contains coercive language "
            f"'{contains_coercive_tokens(c['msg'].body)}'"
            if contains_coercive_tokens(c["msg"].body)
            else f"voice contact at {c['msg'].send_hour_ist:02d}:00 IST is outside 08:00-19:00"
        )
        + " (adopted voluntarily; not binding on a non-regulated entity)"
    ),
    "STOP-001": lambda c: f"already made {c['state'].attempts} attempts, cap is 5",
    "STOP-002": lambda c: (
        f"already spent {c['state'].spend_paise} paise on this customer, cap is 5000"
    ),
    "STOP-003": lambda c: "customer has opted out; this is permanent",
    "STOP-004": lambda c: (
        f"customer promised to pay by {c['state'].ptp_date}; contact suppressed "
        f"until the day after"
    ),
    "SELF-001": lambda c: (
        f"{c['state'].messages_today} message(s) already sent to this customer today; "
        f"cap is 1 across all channels"
    ),
}


class PolicyEngine:
    def __init__(self, rules_path: str) -> None:
        with open(rules_path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)

        self.scope: str = doc.get("scope", "")
        self.rules: dict[str, dict] = {}
        for rule in doc["rules"]:
            if rule.get("class") not in VALID_CLASSES:
                raise ValueError(
                    f"rule {rule.get('id')} has class {rule.get('class')!r}, which is "
                    f"not one of {sorted(VALID_CLASSES)}"
                )
            self.rules[rule["id"]] = rule

        # Compile once. A syntactically broken predicate is a load-time failure,
        # not a surprise on the first action that happens to reach it.
        self._compiled = {
            rid: compile(r["predicate"], f"<rule {rid}>", "eval")
            for rid, r in self.rules.items()
        }

    def evaluated_rule_ids(self) -> set[str]:
        """Every rule this engine actually evaluates.

        Compared against the file by test, so a rule cannot sit in `rules.yaml`
        as a compliance claim with no enforcement behind it.
        """
        return set(self._compiled)

    def rules_without_detail(self) -> list[str]:
        return sorted(set(self.rules) - set(_DETAIL))

    def _context(self, action: Action, state, now: datetime) -> dict:
        """The names a predicate may reference.

        Mirrors `ALLOWED_ROOTS` in `tests/test_policy_rules.py`, which fails if a
        predicate names anything not provided here.
        """
        sending = action.action_type in ("send_message", "create_link", "escalate")
        hour = ist_hour(action.send_at)

        msg = SimpleNamespace(
            body=action.body,
            channel=action.channel if sending else "none",
            category=classify_message(action.body) if sending else "SERVICE_IMPLICIT",
            send_hour_ist=hour,
            dlt_template_id=action.dlt_template_id if sending else "n/a",
            dlt_template_approved=action.dlt_template_approved or not sending,
            body_matches_registered_template=(
                action.body_matches_registered_template or not sending
            ),
            wa_template_category=action.wa_template_category,
            is_coercive=bool(contains_coercive_tokens(action.body)),
        )
        return {
            "msg": msg,
            "action": SimpleNamespace(
                uses_rzp_reminder=action.uses_rzp_reminder,
                send_hour_ist=hour,
                action_type=action.action_type,
                attempt_no=action.attempt_no,
            ),
            "customer": SimpleNamespace(
                whatsapp_optin=getattr(state, "whatsapp_optin", True),
            ),
            "link": SimpleNamespace(
                reminder_count=getattr(state, "reminder_count", 0),
            ),
            "state": SimpleNamespace(
                attempts=state.attempts,
                spend_paise=state.spend_paise,
                opted_out=state.opted_out,
                ptp_date=date.fromisoformat(state.ptp_date) if state.ptp_date else None,
                messages_today=getattr(state, "messages_today", 0),
            ),
            "today": now.date() if isinstance(now, datetime) else now,
            "contains_promotional_tokens": contains_promotional_tokens,
        }

    def evaluate(self, action: Action, state, now: datetime) -> Verdict:
        context = self._context(action, state, now)
        denials: list[Denial] = []

        for rule_id, code in self._compiled.items():
            try:
                ok = eval(code, {"__builtins__": {}}, dict(context))  # noqa: S307
            except Exception as exc:
                raise PolicyEvaluationError(
                    f"rule {rule_id} could not be evaluated: {exc!r}. A compliance "
                    f"rule that cannot be evaluated is not an allowed action."
                ) from exc

            if not ok:
                rule = self.rules[rule_id]
                detail_fn = _DETAIL.get(rule_id)
                denials.append(
                    Denial(
                        rule_id=rule_id,
                        rule_class=rule["class"],
                        reason=" ".join(rule["reason"].split()),
                        detail=detail_fn(context) if detail_fn else rule["predicate"],
                        source_url=rule.get("source_url", "") or "",
                    )
                )

        return Verdict(allowed=not denials, denials=denials)
