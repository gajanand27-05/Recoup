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

Every predicate is validated at LOAD time, not on first use
------------------------------------------------------------
`CONTEXT_SCHEMA` below is a declared contract: exactly which names a predicate may
reference and, for each, exactly which attributes. Anything outside it is a
`PolicyRuleError` raised when the engine is constructed.

This is not about injection. `rules.yaml` is repo-controlled, and anyone who can
edit it can edit this file just as easily. It is about *arrival time*. Validating
on first use means a typo in a rarely-hit rule surfaces halfway through a
2,000-subscription batch, or never — and a clause that never resolves is a clause
that can never be false.

That is exactly what `RBI-005` was before this: it read `not msg.is_coercive`
while nothing defined `is_coercive`, so half the rule was decorative and no test
could have noticed, because the rule still denied on its other clause. Load-time
name checking makes that class of defect impossible rather than merely unlikely.

`eval` is used, deliberately
-----------------------------
With an explicit namespace and no builtins. The alternative — hard-coding each
rule in Python beside a YAML file that carries decorative predicate strings — is
precisely the defect A-019 documents. See the policy section of README.md.
"""

import ast
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

# The contract. A predicate may reference these names and, for the namespaced
# ones, only these attributes. `_context()` must supply exactly this and nothing
# else -- checked in both directions by test, because a schema that has drifted
# from the runtime context is itself a declared thing with no consumer.
CONTEXT_SCHEMA: dict[str, frozenset[str]] = {
    "msg": frozenset({
        "body", "channel", "category", "send_hour_ist", "dlt_template_id",
        "dlt_template_approved", "body_matches_registered_template",
        "wa_template_category", "is_coercive",
    }),
    "action": frozenset({"uses_rzp_reminder", "send_hour_ist", "action_type", "attempt_no"}),
    "customer": frozenset({"whatsapp_optin"}),
    "link": frozenset({"reminder_count"}),
    "state": frozenset({"attempts", "spend_paise", "opted_out", "ptp_date", "messages_today"}),
}

# Bare values and callables a predicate may name.
CONTEXT_VALUES = frozenset({"today"})
CONTEXT_CALLABLES = frozenset({"contains_promotional_tokens"})

ALLOWED_NAMES = frozenset(CONTEXT_SCHEMA) | CONTEXT_VALUES | CONTEXT_CALLABLES

# Expression forms a predicate may use. Not a security boundary -- a deliberately
# narrow grammar, so that "what can a rule say?" has a short, readable answer.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Name, ast.Load, ast.Attribute, ast.Constant, ast.Tuple, ast.List, ast.Call,
)


class PolicyRuleError(ValueError):
    """A rule is malformed. Raised at load, never at evaluation."""


def validate_predicate(rule_id: str, predicate: str) -> None:
    """Check a predicate against the declared contract, statically.

    Called for every rule when the engine is constructed. A predicate naming
    something the context does not provide fails here, at startup, rather than on
    whichever action first happens to reach that rule.
    """
    try:
        tree = ast.parse(predicate, mode="eval")
    except SyntaxError as exc:
        raise PolicyRuleError(f"rule {rule_id}: predicate does not parse: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise PolicyRuleError(
                f"rule {rule_id}: predicate uses {type(node).__name__}, which is not "
                f"one of the permitted expression forms"
            )

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in CONTEXT_CALLABLES:
                raise PolicyRuleError(
                    f"rule {rule_id}: predicate calls something other than "
                    f"{sorted(CONTEXT_CALLABLES)}"
                )

        if isinstance(node, ast.Attribute):
            root = node.value
            if not isinstance(root, ast.Name):
                raise PolicyRuleError(
                    f"rule {rule_id}: predicate uses a chained attribute, which the "
                    f"context contract does not cover"
                )
            allowed = CONTEXT_SCHEMA.get(root.id)
            if allowed is None:
                raise PolicyRuleError(
                    f"rule {rule_id}: predicate references {root.id!r}, which is not in "
                    f"the context. Permitted: {sorted(ALLOWED_NAMES)}"
                )
            if node.attr not in allowed:
                raise PolicyRuleError(
                    f"rule {rule_id}: predicate references {root.id}.{node.attr}, which "
                    f"the context does not provide. {root.id} offers: {sorted(allowed)}. "
                    f"An undefined field would make this clause unable to be false."
                )

        if isinstance(node, ast.Name) and node.id not in ALLOWED_NAMES:
            raise PolicyRuleError(
                f"rule {rule_id}: predicate references {node.id!r}, which is not in the "
                f"context. Permitted: {sorted(ALLOWED_NAMES)}"
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

        # Validate and compile EVERY predicate now. A typo in a rarely-hit rule
        # must surface at startup, not halfway through a 2,000-subscription batch
        # -- and a clause that never resolves is a clause that can never be false.
        self._compiled = {}
        for rid, rule in self.rules.items():
            validate_predicate(rid, rule["predicate"])
            self._compiled[rid] = compile(rule["predicate"], f"<rule {rid}>", "eval")

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

        Must match `CONTEXT_SCHEMA` exactly, in both directions: a field here and
        not in the schema is unreachable by any rule, and a field in the schema
        and not here would pass load-time validation and then fail at evaluation.
        Both directions are checked by test.
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
