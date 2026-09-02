"""Task 22 — run the batch.

    python scripts/run_batch.py --n 20 --dry     # small-N end-to-end check
    python scripts/run_batch.py --n 2000         # the real thing
    python scripts/run_batch.py --n 2000         # again: RESUMES, does not repeat

The dry pass is not optional and not a formality. INC-007 was an arm that
silently did nothing while every test passed; a treatment arm falling back 100%
of the time is that same defect in a new place. So `--dry` asserts that both arms
act AND that a non-trivial fraction of treatment actions were decided by the
model, before three hours are spent finding out otherwise.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from recoup.agent.identity import capture_ollama_identity  # noqa: E402
from recoup.agent.llm import OllamaLLM, client_for  # noqa: E402
from recoup.assign.arms import CONTROL, TREATMENT  # noqa: E402
from recoup.batch.runner import ArmStats, BatchRunner  # noqa: E402
from recoup.clock import now_utc, to_iso_z  # noqa: E402
from recoup.config import settings  # noqa: E402
from recoup.execute.sim import SimTransport  # noqa: E402

RULES = str(REPO / "src" / "recoup" / "policy" / "rules.yaml")

#: ASSUMPTION: below this share of treatment actions decided by the model, the
#: dry pass refuses to bless the batch. Chosen before running: at 30% the arm is
#: mostly control by construction. Sweep range 0.2..0.8.
MIN_DRY_MODEL_FRACTION = 0.3


def main() -> int:
    ap = argparse.ArgumentParser(description="recoup batch runner")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20260902)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--dry", action="store_true", help="small-N gate; asserts both arms act")
    ap.add_argument("--no-llm", action="store_true",
                    help="deterministic path only; produces an UNREPORTABLE run")
    ap.add_argument("--concurrency", type=int, default=OllamaLLM.SAFE_CONCURRENCY,
                    help=f"parallel subscriptions; provider ceiling measured at "
                         f"{OllamaLLM.OBSERVED_CONCURRENCY_LIMIT} concurrent requests")
    args = ap.parse_args()

    if args.concurrency > OllamaLLM.OBSERVED_CONCURRENCY_LIMIT:
        print(f"refusing --concurrency {args.concurrency}: the provider returned "
              f"429 above {OllamaLLM.OBSERVED_CONCURRENCY_LIMIT} concurrent "
              f"requests when measured. Retrying into a known limit wastes a batch.")
        return 1

    run_id = args.run_id or f"batch-{args.n}-{args.seed}"
    db = args.db or str(REPO / "runs" / f"{run_id}.db")
    Path(db).parent.mkdir(parents=True, exist_ok=True)

    client = None
    identity = None
    if not args.no_llm:
        client = client_for(settings.llm_model)
        identity = capture_ollama_identity(
            settings.llm_model, settings.ollama_api_key, settings.ollama_host,
            now_iso=to_iso_z(now_utc()),
        )
        print(f"model: {identity.describe()}\n")
    else:
        # A StubLLM, NOT None. `None` raises by design — there is no fallback for
        # a missing client, because a run with no model configured must not
        # quietly become a second deterministic arm. The stub is the explicit
        # way to say "no model on purpose": it returns nothing usable, every
        # action is labelled DETERMINISTIC, and the provenance gate refuses to
        # report over it.
        from recoup.agent.llm import StubLLM

        client = StubLLM()
        print("--no-llm: StubLLM. Every treatment action will be a labelled\n"
              "  DETERMINISTIC fallback. This run is UNREPORTABLE BY\n"
              "  CONSTRUCTION and exists to exercise the plumbing.\n")

    runner = BatchRunner(
        db_path=db, rules_path=RULES, run_id=run_id, seed=args.seed,
        transport=SimTransport(seed=args.seed), llm_client=client,
        concurrency=1 if args.no_llm else args.concurrency,
    )
    if runner.checkpoint.exists():
        print(f"resuming from {runner.checkpoint} "
              f"({len(runner._completed())} subscriptions already done)\n")

    summary = runner.run(args.n)
    if identity is not None:
        summary.model_identity = identity.as_dict()

    print(f"\n{'=' * 70}\n  run {run_id}  n={args.n}  seed={args.seed}\n{'=' * 70}")
    header = f"{'':22}{'control':>12}{'treatment':>12}"
    print(header)
    control = ArmStats(**summary.arms[CONTROL])
    treatment = ArmStats(**summary.arms[TREATMENT])
    for label, attr in (
        ("subscriptions", "subscriptions"), ("actions proposed", "actions_proposed"),
        ("actions sent", "actions_sent"), ("vetoed by policy", "actions_vetoed"),
        ("replans", "replans"), ("model-decided", "model_decided"),
        ("fallbacks", "fallbacks"), ("recovered", "recovered"),
        ("spend (paise)", "spend_paise"),
    ):
        print(f"  {label:20}{getattr(control, attr):>12}{getattr(treatment, attr):>12}")
    print(f"  {'fallback rate':20}{'n/a — no model':>12}"
          f"{treatment.fallback_rate:>11.1%}")
    print(f"  {'recovery rate':20}{control.recovery_rate:>11.1%}"
          f"{treatment.recovery_rate:>11.1%}")

    out = Path(db).with_suffix(".summary.json")
    out.write_text(json.dumps(summary.__dict__, indent=2, default=str), encoding="utf-8")
    print(f"\nsummary written to {out}")

    if summary.invalidations:
        print("\n*** THIS RUN MAY NOT BE REPORTED AS A LIFT FIGURE ***")
        for problem in summary.invalidations:
            print(f"  - {problem}")

    if args.dry:
        print(f"\n{'-' * 70}\nDRY PASS CHECKS\n{'-' * 70}")
        failures = []
        if control.actions_sent == 0:
            failures.append("control arm sent nothing")
        if treatment.actions_sent == 0:
            failures.append("treatment arm sent nothing")
        decided = treatment.model_decided + treatment.fallbacks
        fraction = treatment.model_decided / decided if decided else 0.0
        if not args.no_llm and fraction < MIN_DRY_MODEL_FRACTION:
            failures.append(
                f"only {fraction:.0%} of treatment actions were model-decided "
                f"(need >= {MIN_DRY_MODEL_FRACTION:.0%}); the agent is mostly absent"
            )
        for line in (
            f"  control sent           : {control.actions_sent}",
            f"  treatment sent         : {treatment.actions_sent}",
            f"  model-decided fraction : {fraction:.0%}",
        ):
            print(line)
        if failures:
            print("\nDRY PASS FAILED:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("\nDRY PASS OK — both arms act and the model is genuinely deciding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
