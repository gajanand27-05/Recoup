"""A second opinion on the sign, computed without lift.py.

WHY THIS EXISTS SEPARATELY
---------------------------
Two of the three stats helpers take (baseline, comparison) and return
`second - first`. Both were called with the arms reversed. That was caught — and
the first fix had a hole: only ONE of the two sign tests fired, because the money
test asserted on `money_diff`, which is computed straight from the two means and
survives an inverted bootstrap untouched.

So this is a defect that survived a round of fixing. It does not get to be
checked only by the tests that already missed it once.

WHAT MAKES THIS INDEPENDENT
----------------------------
It counts recoveries per arm **straight off the ledger rows**, with plain
arithmetic and no import from `recoup.eval.lift` or `recoup.eval.stats`. If both
paths agree on direction, a sign inversion would have to exist identically in
two implementations that share no code. If they disagree, one is wrong and the
run does not get reported until it is known which.

It deliberately does NOT re-derive the interval. A second implementation of
Newcombe would be a second chance to make the same mistake; direction is the
thing that was actually wrong, and direction is what this checks.
"""

import json
import sqlite3

import pytest

from recoup.assign.arms import CONTROL, TREATMENT

RULES = "src/recoup/policy/rules.yaml"


def recovery_counts_from_ledger(db_path: str, run_id: str) -> dict[str, dict]:
    """Recoveries and subscriptions per arm, by counting rows. Nothing else.

    A subscription counts as recovered if it has at least one `outcome.recovered`
    row — `max`, not a sum, for the same reason `replay()` uses max: at-least-once
    delivery means one recovery can be recorded twice, and adding would invent
    money nobody paid.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT arm, event_type, subscription_id FROM ledger WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    seen: dict[str, set] = {CONTROL: set(), TREATMENT: set()}
    recovered: dict[str, set] = {CONTROL: set(), TREATMENT: set()}
    for arm, event_type, subscription_id in rows:
        if arm not in seen:
            continue
        seen[arm].add(subscription_id)
        if event_type == "outcome.recovered":
            recovered[arm].add(subscription_id)

    return {
        arm: {
            "subscriptions": len(seen[arm]),
            "recovered": len(recovered[arm]),
            "rate": len(recovered[arm]) / len(seen[arm]) if seen[arm] else 0.0,
        }
        for arm in (CONTROL, TREATMENT)
    }


def direction_from_ledger(db_path: str, run_id: str) -> int:
    """+1 treatment ahead, -1 control ahead, 0 exactly level. Plain subtraction."""
    counts = recovery_counts_from_ledger(db_path, run_id)
    delta = counts[TREATMENT]["rate"] - counts[CONTROL]["rate"]
    return (delta > 0) - (delta < 0)


# --- the cross-check, against a run this test produces itself -------------------


@pytest.fixture
def run(tmp_path):
    """A real run, not a fixture of rows. The input shape has to come from the
    code path that produces it in anger."""
    from recoup.batch.runner import BatchRunner
    from recoup.execute.sim import SimTransport

    class _LLM:
        name = "fake-planner-1"

        def classify_reply(self, text, today):  # pragma: no cover
            raise AssertionError("wrong role")

        def propose_action(self, system, prompt):
            return {
                "action_type": "send_message",
                "template_id": "TPL_RECOUP_WA_001",
                "hours_from_now": 0,
                "variables": {"name": "there", "amount": "499"},
                "rationale": "x",
            }

    db = str(tmp_path / "x.db")
    runner = BatchRunner(
        db_path=db, rules_path=RULES, run_id="x", seed=5,
        transport=SimTransport(seed=5), llm_client=_LLM(),
        checkpoint_dir=str(tmp_path / "cp"),
    )
    runner.run(120, progress_every=0)
    return db


def _views_and_rows(db: str, run_id: str = "x"):
    from recoup.eval.views import LiftView
    from recoup.ledger.replay import replay

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = []
        for r in conn.execute("SELECT * FROM ledger WHERE run_id = ?", (run_id,)):
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            rows.append(d)
    finally:
        conn.close()
    states = replay(rows)
    views = [
        LiftView.from_state(s, amount_paise=49900)
        for s in states.values()
        if s.arm is not None
    ]
    return views, rows


def test_the_two_paths_agree_on_direction(run):
    """THE ASSERTION. Two implementations sharing no code must agree on sign."""
    from recoup.eval.lift import compute_lift

    views, rows = _views_and_rows(run)
    result = compute_lift(views, run_id="x", ledger_rows=rows, bootstrap_iterations=200)

    ledger_direction = direction_from_ledger(run, "x")
    lift_direction = (result.diff_pp > 0) - (result.diff_pp < 0)

    counts = recovery_counts_from_ledger(run, "x")
    assert ledger_direction == lift_direction, (
        f"the two paths disagree on SIGN.\n"
        f"  raw ledger: control {counts[CONTROL]['recovered']}/"
        f"{counts[CONTROL]['subscriptions']} = {counts[CONTROL]['rate']:.2%}, "
        f"treatment {counts[TREATMENT]['recovered']}/"
        f"{counts[TREATMENT]['subscriptions']} = {counts[TREATMENT]['rate']:.2%} "
        f"-> direction {ledger_direction:+d}\n"
        f"  lift.py   : {result.diff_pp:+.2f} pp -> direction {lift_direction:+d}\n"
        f"One of them is inverted. The run must not be reported until it is known "
        f"which."
    )


def test_the_two_paths_agree_on_the_rates_themselves(run):
    """Direction agreeing by coincidence is possible; the rates agreeing is not."""
    from recoup.eval.lift import compute_lift

    views, rows = _views_and_rows(run)
    result = compute_lift(views, run_id="x", ledger_rows=rows, bootstrap_iterations=200)
    counts = recovery_counts_from_ledger(run, "x")

    assert result.control.recovered == counts[CONTROL]["recovered"]
    assert result.treatment.recovered == counts[TREATMENT]["recovered"]
    assert result.control.n == counts[CONTROL]["subscriptions"]
    assert result.treatment.n == counts[TREATMENT]["subscriptions"]


def test_the_interval_agrees_with_the_ledger_direction_when_it_excludes_zero(run):
    """The half that the first fix missed: a correct point estimate with an
    inverted interval around it."""
    from recoup.eval.lift import compute_lift

    views, rows = _views_and_rows(run)
    result = compute_lift(views, run_id="x", ledger_rows=rows, bootstrap_iterations=200)
    low, high = result.diff_ci_pp
    if low > 0 or high < 0:  # only meaningful when the interval takes a side
        interval_direction = 1 if low > 0 else -1
        assert interval_direction == direction_from_ledger(run, "x"), (
            f"CI [{low:.2f}, {high:.2f}] points the opposite way to the raw counts"
        )


# --- the plant, permanent ---------------------------------------------------------


def test_the_crosscheck_fires_when_an_arm_is_inverted(run):
    """Swap the two arms' labels in a COPY of the ledger and confirm the raw
    count direction flips. If it did not, this cross-check would agree with
    lift.py no matter what either of them computed — a second opinion that always
    says yes is not a second opinion.
    """
    import shutil

    original = direction_from_ledger(run, "x")
    if original == 0:
        pytest.skip("this cohort is exactly level; there is no sign to invert")

    swapped = run + ".swapped"
    shutil.copy(run, swapped)
    conn = sqlite3.connect(swapped)
    try:
        # The trigger blocks UPDATE on the ledger — that is the point of the
        # ledger — so the swap is done on a copy with the trigger dropped, which
        # is also how the demo tampers with it.
        conn.executescript(
            "DROP TRIGGER IF EXISTS ledger_no_update;"
            "UPDATE ledger SET arm = CASE arm "
            "WHEN 'control' THEN 'treatment' ELSE 'control' END;"
        )
        conn.commit()
    finally:
        conn.close()

    assert direction_from_ledger(swapped, "x") == -original, (
        "inverting the arms did not flip the measured direction — the cross-check "
        "is not actually reading the arms"
    )
