"""Every policy rule carries its legal class, and the class is load-bearing.

Research caught this design about to assert three conventions as regulations
(A-006). Overclaiming a best practice as law is the most likely failure mode of a
compliance document, and a payments judge will find it.

Beyond the plan's checks, this file pins two things the plan does not:

* **Predicates are parsed, not eyeballed.** Each is a Python expression that the
  Task 16 engine must evaluate. A typo in a field name gives a rule that always
  passes or always fails, silently — the INC-005 shape, in a compliance file.
* **The rules that are deliberately ABSENT stay absent.** D-030 puts this system
  strictly after the mandate rail gives up, so RBI-001/002/003 and the NPCI UPI
  Autopay caps are out of scope. Re-adding one would be scope creep dressed as
  diligence.
"""

import ast
import datetime
import pathlib
import re

import pytest
import yaml

_REPO = pathlib.Path(__file__).resolve().parents[1]
RULES_PATH = _REPO / "src" / "recoup" / "policy" / "rules.yaml"

VALID_CLASSES = {
    "HARD_LAW", "INDUSTRY_PRACTICE", "BEST_PRACTICE_BY_ANALOGY", "SELF_IMPOSED",
}

# The names a predicate may reference. This is the contract Task 16's engine must
# satisfy: every one of these has to exist in the evaluation context, or the rule
# it appears in can never fire correctly.
ALLOWED_ROOTS = {
    "msg", "customer", "link", "action", "state", "today",
    "contains_promotional_tokens",
}


def load_rules():
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))["rules"]


def load_doc():
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


# --- schema ---------------------------------------------------------------------


def test_rules_file_parses():
    assert len(load_rules()) >= 10


def test_every_rule_has_the_required_fields():
    for rule in load_rules():
        for field in ("id", "predicate", "class", "reason"):
            assert field in rule, f"rule {rule.get('id')} is missing {field}"


def test_every_rule_has_a_valid_legal_class():
    for rule in load_rules():
        assert rule["class"] in VALID_CLASSES, \
            f"rule {rule['id']} has invalid class {rule['class']}"


def test_every_non_self_imposed_rule_cites_a_source():
    """A rule claiming to be law must say where the law is."""
    for rule in load_rules():
        if rule["class"] == "SELF_IMPOSED":
            continue
        assert rule.get("source_url", "").startswith("http"), \
            f"rule {rule['id']} claims {rule['class']} without a source URL"
        assert re.match(r"\d{4}-\d{2}-\d{2}", str(rule.get("retrieved", ""))), \
            f"rule {rule['id']} has no retrieval date"


def test_a_self_imposed_rule_does_not_dress_itself_in_a_citation():
    """Mirror of the ASSUMPTION-never-cites-a-URL check in the params registry.

    A self-imposed restraint with a plausible-looking URL beside it reads as
    externally required. Either it is sourced or it is our own choice.
    """
    for rule in load_rules():
        if rule["class"] == "SELF_IMPOSED":
            assert not rule.get("source_url"), \
                f"rule {rule['id']} is SELF_IMPOSED but cites {rule['source_url']}"


def test_rule_ids_are_unique():
    ids = [r["id"] for r in load_rules()]
    assert len(ids) == len(set(ids))


def test_no_two_rules_share_a_predicate():
    # A duplicated predicate is dead weight at best, and at worst hides a typo in
    # one of the two: they can never disagree, so one is never really tested.
    seen: dict[str, str] = {}
    for rule in load_rules():
        pred = rule["predicate"].strip()
        assert pred not in seen, f"{rule['id']} duplicates the predicate of {seen[pred]}"
        seen[pred] = rule["id"]


def test_every_reason_is_substantive():
    # A rule whose reason is "because" cannot be audited by anyone.
    for rule in load_rules():
        assert len(rule["reason"].split()) >= 12, \
            f"rule {rule['id']} has a reason too short to audit"


def test_retrieval_dates_are_real_and_not_in_the_future():
    today = datetime.date.today()
    for rule in load_rules():
        if not rule.get("retrieved"):
            continue
        got = rule["retrieved"]
        if isinstance(got, str):
            got = datetime.date.fromisoformat(got)
        assert got <= today, f"rule {rule['id']} was retrieved in the future"
        assert got.year >= 2025, f"rule {rule['id']} cites a suspiciously old retrieval"


# --- predicates are code, and are checked as code ---------------------------------


def test_every_predicate_is_a_parseable_expression():
    for rule in load_rules():
        try:
            ast.parse(rule["predicate"], mode="eval")
        except SyntaxError as exc:  # pragma: no cover - the failure is the message
            pytest.fail(f"rule {rule['id']} predicate does not parse: {exc}")


def test_every_predicate_references_only_the_declared_context():
    """The contract Task 16 must satisfy.

    A predicate naming a field the engine never supplies does not error — it
    raises at evaluation and gets swallowed, or worse, resolves to something
    falsy and vetoes everything. Either way the rule stops meaning what it says.
    """
    offenders = {}
    for rule in load_rules():
        tree = ast.parse(rule["predicate"], mode="eval")
        roots = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        unknown = roots - ALLOWED_ROOTS
        if unknown:
            offenders[rule["id"]] = sorted(unknown)
    assert not offenders, (
        f"predicates reference names outside the declared context: {offenders}. "
        "Either add them to ALLOWED_ROOTS and to the engine's context, or fix the typo."
    )


def test_the_declared_context_is_actually_used():
    """Every allowed root must appear in at least one predicate.

    An entry in ALLOWED_ROOTS that no rule uses is a permission granted for
    nothing — and it would let a future typo through by looking legitimate.
    """
    used: set[str] = set()
    for rule in load_rules():
        tree = ast.parse(rule["predicate"], mode="eval")
        used |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert ALLOWED_ROOTS - used == set(), f"unused context names: {sorted(ALLOWED_ROOTS - used)}"


# --- the specific overclaims this file exists to prevent ---------------------------


def test_the_rbi_recovery_hours_rule_is_not_claimed_as_law():
    """RBI/2022-23/108 binds banks, NBFCs and ARCs -- not a SaaS merchant.
    Claiming otherwise is the single most likely error in a dunning policy."""
    rule = next(r for r in load_rules() if r["id"] == "RBI-005")
    assert rule["class"] == "BEST_PRACTICE_BY_ANALOGY"


def test_service_implicit_messages_are_not_time_restricted():
    """SI is 24x7 and DND-exempt. Imposing a window would be a self-inflicted,
    non-legal constraint -- and would make the failure demo wrong."""
    rule = next(r for r in load_rules() if r["id"] == "DLT-003")
    assert "24" in rule["reason"] or "all-day" in rule["reason"].lower()


def test_the_promotional_drift_rule_exists_and_is_hard_law():
    """This is the rule the staged failure demo fires (A-005)."""
    rule = next(r for r in load_rules() if r["id"] == "DLT-007")
    assert rule["class"] == "HARD_LAW"
    assert "promotional" in rule["reason"].lower()


def test_no_rule_claims_an_rbi_retry_cap():
    """No such cap exists in the E-Mandate Framework. Verified by reading it."""
    for rule in load_rules():
        text = (rule["reason"] + rule.get("source_url", "")).lower()
        assert not ("rbi" in text and "retry" in text and "cap" in text)


def test_the_quiet_hours_window_is_ten_not_nine():
    """The widely-repeated 09:00-21:00 is wrong; Schedule-II gives 10:00-21:00.

    Getting this wrong would have put a false claim on camera (A-005).
    """
    rule = next(r for r in load_rules() if r["id"] == "DLT-004")
    assert "10:00" in rule["reason"]
    assert "10 <= msg.send_hour_ist < 21" in rule["predicate"]


# --- what is deliberately absent (D-030) --------------------------------------------


@pytest.mark.parametrize("absent_id", ["RBI-001", "RBI-002", "RBI-003", "NPCI-001", "NPCI-002"])
def test_out_of_scope_rules_stay_out(absent_id):
    """This system operates strictly after the mandate rail gives up and issues
    no debits, so pre-debit notice and autopay retry caps do not apply to it.

    Re-adding one would be scope creep dressed as diligence, and would invite the
    question of why a system that never debits is modelling debit rules.
    """
    assert absent_id not in {r["id"] for r in load_rules()}


def test_the_scope_line_states_that_no_debit_is_initiated():
    scope = load_doc()["scope"].lower()
    assert "no debit" in scope or "never" in scope
    assert "halted" in scope
