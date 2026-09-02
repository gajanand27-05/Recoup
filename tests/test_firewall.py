"""The firewall between the holdout arm and the ground-truth labels.

A README paragraph promising not to peek is not a guarantee. A failing test is.

Ground-truth labels and a holdout arm are two different measurement systems.
The simulator decides who recovers, so computing lift from its labels would be
measuring the simulator against itself. D-011.

Two things the obvious version of this test gets wrong, both already paid for
elsewhere in this build:

1. **Direct imports are not enough.** `lift.py` importing a helper that imports
   the generator reaches the label just as surely. The closure is walked.
2. **A raw string search is a proxy, not the artifact.** `eval/__init__.py`
   contains the sentence "the ONLY module permitted to read would_self_recover"
   in its docstring — a grep flags the rule for stating itself. This is the same
   failure the build-order guard hit when it grepped for "recoup.agent" and fired
   on the docstring forbidding it. So: AST, and docstrings excluded.
"""

import ast
import dataclasses
from pathlib import Path

import pytest

from recoup.eval.views import LiftView

SRC = Path(__file__).resolve().parents[1] / "src"
LABEL = "would_self_recover"

# Who may not reach whom, transitively.
FORBIDDEN_IMPORTS: dict[str, set[str]] = {
    # lift computes the reported effect and may never reach the labels, nor the
    # module that is allowed to read them.
    "recoup.eval.lift": {"recoup.simulator.generator", "recoup.eval.diagnostics"},
    # diagnostics reads the labels, so it must never be able to feed lift.
    "recoup.eval.diagnostics": {"recoup.eval.lift"},
}

# The only modules permitted to mention the label at all.
LABEL_ALLOWED_IN = {
    "recoup.simulator.generator",  # produces it
    "recoup.eval.diagnostics",     # the one consumer (D-011)
}


# --- import graph, over the artifact ------------------------------------------------


def module_path(module: str) -> Path | None:
    flat = SRC / (module.replace(".", "/") + ".py")
    if flat.exists():
        return flat
    pkg = SRC / module.replace(".", "/") / "__init__.py"
    return pkg if pkg.exists() else None


def direct_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            # `from recoup.eval import diagnostics` imports a MODULE, not a name.
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return {m for m in found if m.startswith("recoup")}


def transitive_imports(module: str) -> set[str]:
    """Every recoup module reachable from `module`, following imports."""
    seen: set[str] = set()
    queue = [module]
    while queue:
        current = queue.pop()
        path = module_path(current)
        if path is None:
            continue
        for imported in direct_imports(path):
            if imported not in seen:
                seen.add(imported)
                queue.append(imported)
    return seen


def label_references(path: Path) -> list[int]:
    """Lines where the label is actually USED — not merely written about.

    Counts attribute access, bare names, keyword arguments and string literals
    (for `row["would_self_recover"]`), and excludes docstrings so that a module
    describing the rule does not violate it.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))

    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == LABEL:
            hits.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id == LABEL:
            hits.append(node.lineno)
        elif isinstance(node, ast.keyword) and node.arg == LABEL:
            hits.append(node.lineno)
        elif isinstance(node, ast.Constant) and node.value == LABEL:
            if id(node) not in docstrings:
                hits.append(node.lineno)
    return sorted(hits)


def all_recoup_modules() -> list[str]:
    out = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        out.append(".".join(parts))
    return out


# --- the view ------------------------------------------------------------------------


def test_lift_never_touches_ground_truth():
    """The view exposed to lift.py must not carry the label column."""
    assert LABEL not in LiftView.__columns__


def test_lift_view_exposes_only_the_permitted_columns():
    assert LiftView.__columns__ == frozenset({
        "subscription_id", "arm", "status", "amount_paise",
        "recovered_paise", "spend_paise", "attempts",
    })


def test_the_declared_columns_match_the_actual_fields():
    """`__columns__` is a declaration; the dataclass fields are the artifact.

    A field added without updating `__columns__` would be readable by lift while
    the firewall test kept passing on a stale declaration.
    """
    actual = {f.name for f in dataclasses.fields(LiftView)}
    assert LiftView.__columns__ == actual


def test_the_view_is_immutable():
    view = LiftView(
        subscription_id="s", arm="control", status="new",
        amount_paise=1, recovered_paise=0, spend_paise=0, attempts=0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.arm = "treatment"  # type: ignore[misc]


def test_the_view_is_buildable_from_state_a_real_run_produces():
    """The input shape here comes from `replay()`, not from a hand-built object.

    A declared view with no way to construct it from real data is the INC-005
    shape: registered, described, never wired up — and it reads as working.
    """
    from recoup.assign.arms import assign_arm
    from recoup.ledger.replay import replay

    rows = [
        {"seq": 1, "event_type": "webhook.received", "subscription_id": "sub_1",
         "customer_id": "cust_1", "arm": None, "transport": "sim",
         "payload": {"event": "subscription.halted"}},
        {"seq": 2, "event_type": "arm.assigned", "subscription_id": "sub_1",
         "customer_id": "cust_1", "arm": assign_arm("cust_1", "recoup-2026-08"),
         "transport": "sim", "payload": {}},
        {"seq": 3, "event_type": "action.executed", "subscription_id": "sub_1",
         "customer_id": "cust_1", "arm": None, "transport": "sim",
         "payload": {"channel": "whatsapp", "cost_paise": 12, "attempt_no": 1}},
        {"seq": 4, "event_type": "outcome.recovered", "subscription_id": "sub_1",
         "customer_id": "cust_1", "arm": None, "transport": "sim",
         "payload": {"amount_paise": 49900}},
    ]
    state = replay(rows)["sub_1"]
    view = LiftView.from_state(state, amount_paise=49900)

    assert view.recovered_paise == 49900
    assert view.spend_paise == 12
    assert view.attempts == 1
    assert view.status == "recovered"
    assert set(view.as_dict()) == LiftView.__columns__


def test_a_subscription_with_no_arm_cannot_enter_a_lift_calculation():
    from recoup.ledger.replay import SubscriptionState

    with pytest.raises(ValueError, match="no arm"):
        LiftView.from_state(SubscriptionState(subscription_id="sub_x"), amount_paise=1)


# --- the import closure ----------------------------------------------------------------


def test_no_module_reaches_a_forbidden_import():
    """⚠️ VALIDATED BY PLANTING. `lift.py` does not exist yet.

    Until it does, this check is vacuous for the rule that matters — there is no
    subject to fail on. It has been exercised anyway, by writing a genuinely
    violating `lift.py` into `src/recoup/eval/` and confirming both the import
    closure and the label scan catch it. See:

        test_the_firewall_fires_on_a_violating_lift_module
        test_the_firewall_fires_on_an_indirect_violation

    Those two run on every suite, so this is not a claim about something done once
    in the past — they re-plant, re-check, and delete on every run. If you are
    about to write `lift.py`, they are your evidence that the firewall works.
    """
    problems = []
    for module, forbidden in FORBIDDEN_IMPORTS.items():
        if module_path(module) is None:
            continue  # not built yet; the planted-failure test below covers the checker
        reachable = transitive_imports(module)
        for target in forbidden & reachable:
            problems.append(f"{module} reaches {target}")
    assert not problems, problems


def test_views_does_not_import_the_generator():
    """lift.py will import views.py, so views.py is inside lift's closure.

    If views.py imported the generator to fetch `amount_paise`, lift would reach
    the labels transitively through the very module built to prevent that.
    """
    assert "recoup.simulator.generator" not in transitive_imports("recoup.eval.views")


def test_the_label_is_only_mentioned_where_it_is_allowed():
    """⚠️ VALIDATED BY PLANTING — see the note on the import check above.

    This one is NOT vacuous today: it scans every module that exists. But the
    module it exists to police, `lift.py`, is not among them, so its reach against
    that module is established by the planted-failure tests at the bottom of this
    file rather than by this one passing.
    """
    offenders = {}
    for module in all_recoup_modules():
        if module in LABEL_ALLOWED_IN:
            continue
        path = module_path(module)
        if path is None:
            continue
        lines = label_references(path)
        if lines:
            offenders[module] = lines
    assert not offenders, offenders


def test_the_generator_does_define_the_label():
    # If it did not, the allowlist would be protecting nothing and the scan above
    # would pass because the label had simply gone missing.
    path = module_path("recoup.simulator.generator")
    assert path is not None
    assert label_references(path), "the label is not defined where the allowlist says it is"


# --- the scanner must tell a rule from a sentence about a rule --------------------------


def test_a_docstring_describing_the_rule_is_not_a_violation(tmp_path):
    prose = tmp_path / "prose.py"
    prose.write_text(
        '"""diagnostics.py is the only module permitted to read would_self_recover."""\n',
        encoding="utf-8",
    )
    assert label_references(prose) == []


def test_a_comment_mentioning_the_label_is_not_a_violation(tmp_path):
    commented = tmp_path / "commented.py"
    commented.write_text("# never read would_self_recover here\nX = 1\n", encoding="utf-8")
    assert label_references(commented) == []


@pytest.mark.parametrize(
    "snippet",
    [
        "def f(row):\n    return row.would_self_recover\n",
        'def f(row):\n    return row["would_self_recover"]\n',
        "def f(**kw):\n    return f(would_self_recover=True)\n",
        "def f(s):\n    would_self_recover = s\n    return would_self_recover\n",
    ],
    ids=["attribute", "dict-key", "keyword", "bare-name"],
)
def test_every_way_of_actually_reading_the_label_is_caught(tmp_path, snippet):
    """Four real access shapes. A checker that catches only `.attr` has a hole
    the width of `row["would_self_recover"]`."""
    mod = tmp_path / "reader.py"
    mod.write_text(snippet, encoding="utf-8")
    assert label_references(mod), snippet


# --- the planted failure: prove the firewall fires the moment lift.py lands ---------------


def test_the_firewall_fires_on_a_violating_lift_module():
    """Written when lift.py did not exist, and kept now that it does.

    A guard whose subject does not exist has never been shown to fire, so this
    writes a genuinely violating module into the real source tree, confirms both
    checks catch it, and removes it.

    It plants `_planted_lift.py` rather than `lift.py`. The first version used
    the real name and asserted the file was absent — which was true while the
    module was unwritten and became a collision the moment Task 22 landed. The
    firewall's own name for the real module is checked by
    `test_lift_module_reaches_no_forbidden_import` above; this one is about
    whether the CHECKER fires, and any module name proves that.
    """
    planted = SRC / "recoup" / "eval" / "_planted_lift.py"
    assert not planted.exists(), "a previous run left the plant behind"

    planted.write_text(
        "from recoup.simulator.generator import Scenario\n"
        "\n"
        "def lift(rows):\n"
        '    return sum(r["would_self_recover"] for r in rows)\n',
        encoding="utf-8",
    )
    try:
        reachable = transitive_imports("recoup.eval._planted_lift")
        assert "recoup.simulator.generator" in reachable, "import closure missed the violation"
        assert label_references(planted), "label scan missed the violation"
    finally:
        planted.unlink()

    assert not planted.exists()


def test_the_firewall_fires_on_an_indirect_violation():
    """The transitive case, which a direct-import check would pass.

    lift.py imports a harmless-looking helper; the helper imports the generator.
    Nothing in lift.py itself is wrong, and the label never appears in it.
    """
    helper = SRC / "recoup" / "eval" / "_planted_helper.py"
    planted = SRC / "recoup" / "eval" / "_planted_lift.py"
    assert not planted.exists() and not helper.exists()

    helper.write_text(
        "from recoup.simulator.generator import generate_scenarios\n"
        "\n"
        "def load(n, seed):\n"
        "    return generate_scenarios(n, seed)\n",
        encoding="utf-8",
    )
    planted.write_text(
        "from recoup.eval._planted_helper import load\n"
        "\n"
        "def lift(n):\n"
        "    return len(load(n, 1))\n",
        encoding="utf-8",
    )
    try:
        assert direct_imports(planted) == {
            "recoup.eval._planted_helper",
            "recoup.eval._planted_helper.load",
        }
        assert "recoup.simulator.generator" not in direct_imports(planted), (
            "the direct check must NOT see this -- that is the point of the test"
        )
        assert "recoup.simulator.generator" in transitive_imports(
            "recoup.eval._planted_lift"
        ), "the transitive check missed an indirect route to the labels"
        assert label_references(planted) == [], "the label genuinely does not appear here"
    finally:
        planted.unlink()
        helper.unlink()
