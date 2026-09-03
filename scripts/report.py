"""Task 24 — render the run as a report.

    python scripts/report.py --run-id batch-2000

WHAT IT REFUSES TO DO
---------------------
* Pool `real` and `sim` rows. `require_declared_split()` raises rather than
  filtering, because with `sim` as the default the split is usually trivially
  empty and a correct filter yields one silent pooled number (D-009).
* Render a figure whose provenance touches a stub or a not-run eval
  (`provenance_gate`, A-023).
* Print a lift figure for a run whose treatment arm mostly fell back. That is
  INC-007 in a new place — an arm that stopped being itself — and it prints the
  invalidation instead.
* Quote the lift without the toward-null caveat, or the A/A without its scope.

Every refusal is loud. A report that quietly omits a number it could not justify
looks exactly like a report that had nothing to say.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from recoup.assign.arms import CONTROL, TREATMENT  # noqa: E402
from recoup.batch.runner import ArmStats  # noqa: E402
from recoup.eval.lift import compute_lift  # noqa: E402
from recoup.eval.stats import wilson_interval  # noqa: E402
from recoup.eval.views import LiftView  # noqa: E402
from recoup.ledger.replay import count_unattributable, replay  # noqa: E402

#: MEASURED 2026-09-02, `gpt-oss:120b`, 52 model-classified fixtures.
#: Carried here so the lift never appears without the accuracy of the component
#: that produced the decisions. See EVAL_RESULTS.md.
INTENT_ACCURACY = (49, 52)


def _load(db: str, run_id: str):
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
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="render the batch as a report")
    ap.add_argument("--run-id", default="batch-2000")
    ap.add_argument("--db", default=None)
    ap.add_argument("--amount-paise", type=int, default=49900)
    ap.add_argument("--out", default=None, help="write markdown here as well")
    args = ap.parse_args()

    db = args.db or str(REPO / "runs" / f"{args.run_id}.db")
    summary_path = Path(db).with_suffix(".summary.json")

    rows = _load(db, args.run_id)
    if not rows:
        print(f"no ledger rows for run {args.run_id!r} in {db}")
        return 1

    states = replay(rows)
    views = [
        LiftView.from_state(s, amount_paise=args.amount_paise)
        for s in states.values()
        if s.arm is not None
    ]

    out = []

    def say(line: str = "") -> None:
        out.append(line)
        print(line)

    say(f"# recoup — run `{args.run_id}`")
    say()

    # --- what ran ---------------------------------------------------------
    summary = {}
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        identity = summary.get("model_identity") or {}
        if identity:
            say("## The model")
            say()
            checkable = identity.get("confirmation") == "CONFIRMED_BY_REGISTRY"
            say(f"- id: `{identity.get('model_id')}`")
            say(f"- digest: `{identity.get('digest') or '(none)'}`")
            say(f"- {identity.get('confirmation')}"
                + ("" if checkable else " — **nothing proves which weights ran**"))
            say()

    # --- per arm, never pooled --------------------------------------------
    if summary.get("arms"):
        say("## Per arm")
        say()
        say("The control calls no model, so its fallback rate is structurally zero.")
        say("Pooling the two would hide the only number that matters: how often the")
        say("treatment arm stopped being the treatment.")
        say()
        control = ArmStats(**summary["arms"][CONTROL])
        treatment = ArmStats(**summary["arms"][TREATMENT])
        say("| | control | treatment |")
        say("|---|---|---|")
        for label, attr in (
            ("subscriptions", "subscriptions"), ("actions proposed", "actions_proposed"),
            ("actions sent", "actions_sent"), ("vetoed by policy", "actions_vetoed"),
            ("replans", "replans"), ("model-decided", "model_decided"),
            ("fallbacks (schema violations)", "fallbacks"),
        ):
            say(f"| {label} | {getattr(control, attr)} | {getattr(treatment, attr)} |")
        say(f"| **fallback rate** | n/a — no model | **{treatment.fallback_rate:.1%}** |")
        say()

        invalidations = summary.get("invalidations")
        if invalidations is None:
            from recoup.batch.runner import RunSummary

            invalidations = RunSummary(
                run_id=args.run_id, n=summary.get("n", 0), seed=summary.get("seed", 0),
                horizon_days=summary.get("horizon_days", 0), arms=summary["arms"],
            ).invalidations
        if invalidations:
            say("### ⛔ THIS RUN MAY NOT BE REPORTED AS A LIFT FIGURE")
            say()
            for problem in invalidations:
                say(f"- {problem}")
            say()
            return 1

    # --- the fallback rate as a SERIES ------------------------------------
    from recoup.batch.series import fallback_series, read_checkpoint, render_series

    checkpoint = REPO / "runs" / "checkpoints" / f"{args.run_id}.jsonl"
    windows = fallback_series(read_checkpoint(checkpoint))
    if windows:
        say("## Fallback rate over the run")
        say()
        say("Not a closing figure. 5% overall is consistent with 5% throughout and")
        say("with 1% rising to 12%, and those are different claims about the")
        say("toward-null bias. Windows are SUBMISSION-index ranges, not completion")
        say("order — control subscriptions finish in milliseconds and treatment ones")
        say("in ~20s, so a window of completions is a window of whichever arm is")
        say("faster.")
        say()
        for line in render_series(windows):
            say(line)
        say()

    # --- the number -------------------------------------------------------
    say("## Recovery lift")
    say()
    try:
        result = compute_lift(views, run_id=args.run_id, ledger_rows=rows)
    except Exception as exc:  # noqa: BLE001 - the refusal is the output
        say(f"**REFUSED:** {exc}")
        say()
        return 1

    say("```")
    for line in result.describe().splitlines():
        say(line)
    say("```")
    say()

    lo, hi = wilson_interval(*INTENT_ACCURACY)
    say(f"**Carried with this figure:** the reply classifier scored "
        f"{INTENT_ACCURACY[0]}/{INTENT_ACCURACY[1]} = "
        f"{INTENT_ACCURACY[0] / INTENT_ACCURACY[1]:.1%} on hand-labelled fixtures, "
        f"95% CI [{lo:.1%}, {hi:.1%}] — a lower bound below the 85% bar. A lift "
        f"quoted without the accuracy of the component that made the decisions is "
        f"a claim about a system whose main moving part is unmeasured.")
    say()
    say("**Direction of the known bias:** schema violations drive a "
        "`DETERMINISTIC`-labelled fallback, which behaves like a control action, "
        "so violations pull measured lift **toward null**. A small or null lift "
        "may cite them; a large positive lift may not (EXPERIMENT.md Addendum 2).")
    say()

    # --- completeness -----------------------------------------------------
    orphans = count_unattributable(rows)
    say("## Completeness")
    say()
    say(f"- ledger rows: {len(rows)}")
    say(f"- subscriptions replayed: {len(states)}")
    say(f"- rows attributable to no subscription: {orphans}"
        + ("" if orphans == 0 else " — **these shorten every denominator**"))
    say()

    if args.out:
        Path(args.out).write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
