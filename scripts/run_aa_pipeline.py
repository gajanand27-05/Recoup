"""The full-pipeline A/A, pre-registered in EXPERIMENT.md for after Task 22.

    python scripts/run_aa_pipeline.py --check-detection   # can it find anything?
    python scripts/run_aa_pipeline.py                     # the A/A itself

WHAT IT IS
----------
Both arms run the **identical control policy** through the real path — generator,
arm assignment, policy engine, transport, ledger, replay, lift. Only the arm
label differs. Expected result: no significant difference.

The statistical A/A (Task 13) drew two binomials and compared them. This one puts
the whole machine on the bench, which is a different and stronger check: a bias
introduced by arm assignment, by the ledger, by replay or by the lift calculation would
appear here and could not appear there.

It costs nothing to run. The control decider makes no model calls, so this does
not touch the provider's quota.

⚠️ A TEST THAT PASSES BY FINDING NOTHING
-----------------------------------------
This is the easiest place in the build for a vacuous pass to hide. "No
significant difference" is exactly what a completely broken pipeline reports —
one that recovers nobody, or assigns every subscription to one arm, or loses
every recovery on the way to the lift.

So `--check-detection` runs first and **injects a known effect**: arm B gets a
strictly better schedule. If the pipeline cannot report *that*, its silence about
the real A/A means nothing. The detection check is not optional and its result is
printed beside the A/A's.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from recoup.assign.arms import TREATMENT  # noqa: E402
from recoup.baseline.fixed import FixedIntervalOutreach  # noqa: E402
from recoup.batch.runner import BatchRunner  # noqa: E402
from recoup.eval.lift import compute_lift  # noqa: E402
from recoup.eval.views import LiftView  # noqa: E402
from recoup.execute.sim import SimTransport  # noqa: E402
from recoup.ledger.replay import replay  # noqa: E402
from recoup.simulator.generator import generate_scenarios  # noqa: E402

RULES = str(REPO / "src" / "recoup" / "policy" / "rules.yaml")

#: Drawn from OUTSIDE the powered N (D-032), so the A/A does not consume
#: subscriptions the main experiment is entitled to. A different seed is a
#: different cohort.
AA_SEED = 20260904
AA_N = 2000

#: The injected effect for the detection check: the most aggressive schedule in
#: `SCHEDULE_ALTERNATIVES`, five messages on five consecutive days.
#:
#: I wrote "chosen to be well above the ~6.2pp MDE" here before running it. That
#: was wrong, and the measurement says so: the injection produces **+4.21 pp,
#: p = 0.0451** — a detection, but a marginal one, and the effect is BELOW the
#: 6.23 pp this design is powered for.
#:
#: That is not a badly calibrated check. It is the ceiling: the largest
#: difference any legitimate policy change can produce here is about 4 pp,
#: because STOP-001 caps attempts at five and (0,1,2,3,4) is the most front-loaded
#: schedule those five allow. **The best possible schedule improvement is smaller
#: than the effect this experiment is powered to detect.** That bounds what the
#: main run could ever have shown, and it is reported rather than tuned around.
DETECTION_SCHEDULE = (0, 1, 2, 3, 4)


def _both_arms_control(arm: str, client=None):
    """Identical policy for both arms. Only the label differs."""
    return FixedIntervalOutreach()


def _injected(arm: str, client=None):
    """Arm B gets a strictly better schedule. Used ONLY by --check-detection."""
    return FixedIntervalOutreach(
        schedule_days=DETECTION_SCHEDULE if arm == TREATMENT else None
    )


def _run(run_id: str, factory, n: int) -> tuple:
    db = REPO / "runs" / f"{run_id}.db"
    for stale in (db, db.with_suffix(".summary.json"),
                  REPO / "runs" / "checkpoints" / f"{run_id}.jsonl"):
        stale.unlink(missing_ok=True)

    runner = BatchRunner(
        db_path=str(db), rules_path=RULES, run_id=run_id, seed=AA_SEED,
        transport=SimTransport(seed=AA_SEED), llm_client=None,
        decider_factory=factory,
        checkpoint_dir=str(REPO / "runs" / "checkpoints"),
    )
    runner.run(n, progress_every=0)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = []
        for r in conn.execute("SELECT * FROM ledger WHERE run_id = ?", (run_id,)):
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            rows.append(d)
    finally:
        conn.close()

    amounts = {s.subscription_id: s.amount_paise
               for s in generate_scenarios(n, seed=AA_SEED)}
    views = [
        LiftView.from_state(s, amount_paise=amounts.get(s.subscription_id, 49900))
        for s in replay(rows).values() if s.arm is not None
    ]
    return compute_lift(views, run_id=run_id, ledger_rows=rows), views


def _describe(label: str, result) -> None:
    print(f"\n{'=' * 70}\n  {label}\n{'=' * 70}")
    print(result.describe())


def main() -> int:
    ap = argparse.ArgumentParser(description="full-pipeline A/A")
    ap.add_argument("--n", type=int, default=AA_N)
    ap.add_argument("--check-detection", action="store_true",
                    help="only run the injected-effect check")
    ap.add_argument("--skip-detection", action="store_true",
                    help="NOT RECOMMENDED: run the A/A without proving it can detect")
    args = ap.parse_args()

    detected = None
    if not args.skip_detection:
        injected, _ = _run("aa-pipeline-detection", _injected, args.n)
        _describe("DETECTION CHECK — arm B given a strictly better schedule", injected)
        detected = injected.is_significant
        print(f"\n  can this pipeline detect a real difference? "
              f"{'YES' if detected else 'NO'}")
        if not detected:
            print("\n  *** THE A/A BELOW WOULD BE MEANINGLESS. ***")
            print("  A pipeline that cannot report an injected effect reports")
            print("  'no difference' for a broken pipeline and a working one alike.")
            return 1

    if args.check_detection:
        return 0

    aa, _ = _run("aa-pipeline", _both_arms_control, args.n)
    _describe("FULL-PIPELINE A/A — both arms on the identical control policy", aa)

    print()
    if aa.is_significant:
        print("  *** THE A/A FAILED. The pipeline reports a difference between two")
        print("      arms running identical policy, so it manufactures lift. The")
        print("      main figure cannot be trusted until this is explained.")
    else:
        print("  The A/A passed: no significant difference between two arms running")
        print("  identical policy through the real path.")
        print()
        print("  Scope, which travels with the result: a pass rules out harness bias")
        print("  larger than about 6.23 percentage points. It does NOT establish an")
        print("  unbiased harness — a smaller bias would not be visible here.")
    if detected is not None:
        print(f"\n  Detection check: the pipeline DID report the injected effect "
              f"({injected.diff_pp:+.2f} pp), so this A/A's silence is informative.")
    return 0 if not aa.is_significant else 1


if __name__ == "__main__":
    raise SystemExit(main())
