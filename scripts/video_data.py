"""Emit every figure the video displays, from the producer that computed it.

    python scripts/video_data.py

WHY THIS EXISTS
---------------
A hardcoded number in a video is the same class as a hardcoded fixture: it agrees
with the report until something changes, and then it silently disagrees — and a
video is the artifact where nobody will notice, because you cannot grep a frame.

So no figure is typed into the Remotion source. Every one is written here by the
code that produces it — the ledger via `compute_lift`, the frozen curve via
`recovery_probability`, the power design via `mde_at_n`, the run manifest as
committed — and the video reads this file at render time.

`tests/test_video_no_literals.py` fails if a number appears in a caption rather
than coming from here.

WHAT IS NOT HERE
----------------
Anything that would have to be re-derived by hand. If a figure cannot be produced
by running something, it does not go on screen.
"""

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from recoup.baseline.fixed import SCHEDULE_ALTERNATIVES, SCHEDULE_DAYS  # noqa: E402
from recoup.eval.lift import compute_lift  # noqa: E402
from recoup.eval.power import BASELINE_P1, DEFAULT_ALPHA, DEFAULT_POWER, mde_at_n  # noqa: E402
from recoup.eval.stats import wilson_interval  # noqa: E402
from recoup.eval.views import LiftView  # noqa: E402
from recoup.ledger.replay import count_unattributable, replay  # noqa: E402
from recoup.simulator.curve import recovery_probability  # noqa: E402
from recoup.simulator.generator import generate_scenarios  # noqa: E402

RUN_ID = "batch-2000"
N = 2000
SEED = 20260902

#: MEASURED 2026-09-02, gpt-oss:120b, 52 model-classified fixtures out of 60.
#: The 8 not counted are handled by the deterministic opt-out matcher upstream of
#: the model; pooling them would report the matcher's correctness as the model's.
INTENT_CORRECT, INTENT_N = 49, 52
DATE_CORRECT, DATE_N = 10, 11

#: MEASURED 2026-08-31, the component A/A. Run once; not re-run (EXPERIMENT.md).
AA_A, AA_B, AA_N_PER_ARM = 513, 510, 1000


def _cumulative_recovery(schedule) -> float:
    """Probability at least one attempt in this schedule recovers, soft decline,
    whatsapp. Computed over the FROZEN curve, so it is the same arithmetic the
    control arm's own choice was made with."""
    miss = 1.0
    for attempt_no, day in enumerate(schedule, start=1):
        miss *= 1.0 - recovery_probability(
            day_offset=day, channel="whatsapp",
            attempt_no=attempt_no, is_hard_decline=False,
        )
    return 1.0 - miss


def main() -> int:
    db = REPO / "runs" / f"{RUN_ID}.db"
    if not db.exists():
        print(f"no run at {db}; the video cannot be built without the figure it reports")
        return 1

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = []
        for r in conn.execute("SELECT * FROM ledger WHERE run_id = ?", (RUN_ID,)):
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            rows.append(d)
    finally:
        conn.close()

    amounts = {s.subscription_id: s.amount_paise for s in generate_scenarios(N, seed=SEED)}
    states = replay(rows)
    views = [
        LiftView.from_state(s, amount_paise=amounts[s.subscription_id])
        for s in states.values() if s.arm is not None
    ]
    lift = compute_lift(views, run_id=RUN_ID, ledger_rows=rows)

    provenance = json.loads(
        (REPO / "runs" / f"{RUN_ID}.provenance.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (REPO / "runs" / f"{RUN_ID}.summary.json").read_text(encoding="utf-8")
    )

    per_arm = min(lift.control.n, lift.treatment.n)
    harmonic = int(2 * lift.control.n * lift.treatment.n / (lift.control.n + lift.treatment.n))

    schedules = [
        {"days": list(s), "recovery": round(_cumulative_recovery(s), 4),
         "is_control": list(s) == list(SCHEDULE_DAYS)}
        for s in SCHEDULE_ALTERNATIVES
    ]
    best = max(schedules, key=lambda s: s["recovery"])
    control_schedule = next(s for s in schedules if s["is_control"])
    ceiling_pp = round((best["recovery"] - control_schedule["recovery"]) * 100, 2)
    mde_pp = round(mde_at_n(BASELINE_P1, harmonic) * 100, 2)

    intent_lo, intent_hi = wilson_interval(INTENT_CORRECT, INTENT_N)
    date_lo, date_hi = wilson_interval(DATE_CORRECT, DATE_N)

    data = {
        "_generated_by": "scripts/video_data.py",
        "_rule": "No figure on screen is a literal. Every number here was computed "
                 "by the module that owns it, at the moment this file was written.",
        "run": {
            "run_id": RUN_ID, "n": lift.control.n + lift.treatment.n,
            "planned_n": N, "seed": SEED,
            "transport": provenance["transport"],
            "model": provenance["model"],
            "code_pins": provenance["code_pins"],
            "concurrency_schedule": provenance["concurrency_schedule"],
        },
        "lift": {
            "control": {"recovered": lift.control.recovered, "n": lift.control.n,
                        "rate_pct": round(lift.control.rate * 100, 2)},
            "treatment": {"recovered": lift.treatment.recovered, "n": lift.treatment.n,
                          "rate_pct": round(lift.treatment.rate * 100, 2)},
            "diff_pp": round(lift.diff_pp, 2),
            "ci_low_pp": round(lift.diff_ci_pp[0], 2),
            "ci_high_pp": round(lift.diff_ci_pp[1], 2),
            "p_value": round(lift.p_value, 4),
            "significant": lift.is_significant,
            "mde_pp": mde_pp,
            "min_arm": per_arm,
        },
        "power_ceiling": {
            "schedules": schedules,
            "best_pp": round(best["recovery"] * 100, 2),
            "control_pp": round(control_schedule["recovery"] * 100, 2),
            "ceiling_pp": ceiling_pp,
            "mde_pp": mde_pp,
            "ratio": round(mde_pp / ceiling_pp, 1),
            "n_needed": round(N * (mde_pp / ceiling_pp) ** 2, -3),
            "alpha": DEFAULT_ALPHA, "power": DEFAULT_POWER, "baseline_p1": BASELINE_P1,
        },
        "arms": summary["arms"],
        "accuracy": {
            "intent": {"correct": INTENT_CORRECT, "n": INTENT_N,
                       "pct": round(100 * INTENT_CORRECT / INTENT_N, 1),
                       "ci_low": round(intent_lo * 100, 1), "ci_high": round(intent_hi * 100, 1),
                       "bar": 85.0},
            "date": {"correct": DATE_CORRECT, "n": DATE_N,
                     "pct": round(100 * DATE_CORRECT / DATE_N, 1),
                     "ci_low": round(date_lo * 100, 1), "ci_high": round(date_hi * 100, 1),
                     "bar": 80.0},
        },
        "aa": {
            "a": AA_A, "b": AA_B, "n_per_arm": AA_N_PER_ARM,
            "bound_pp": round(mde_at_n(BASELINE_P1, AA_N_PER_ARM) * 100, 2),
        },
        "completeness": {
            "ledger_rows": len(rows),
            "subscriptions": len(states),
            "unattributable": count_unattributable(rows),
        },
    }

    out = REPO / "video" / "data" / "figures.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(f"  lift {data['lift']['diff_pp']:+.2f} pp, MDE {mde_pp} pp")
    print(f"  ceiling {ceiling_pp} pp -> ratio {data['power_ceiling']['ratio']}x, "
          f"n_needed {data['power_ceiling']['n_needed']:,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
