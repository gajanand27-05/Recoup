"""Task 22 — run both arms over N subscriptions and record everything.

WHAT THIS PRODUCES
------------------
Ledger rows, and a per-arm accounting of what happened. It does NOT compute lift;
that is `eval/`, deliberately, so the thing that runs the experiment and the thing
that measures it are separate modules and the measurement firewall has something
to be a firewall between.

RESUMABLE, BECAUSE 3.5 HOURS IS LONGER THAN THINGS STAY UP
-----------------------------------------------------------
Progress is checkpointed per subscription. A re-invocation with the same run_id
skips subscriptions already completed and continues, rather than repeating them.
That is not a convenience: a batch that must restart from zero on any interruption
does not fit in the time available, and the temptation when it dies at hour three
is to report the partial run as if it were whole.

IDEMPOTENT PER SUBSCRIPTION+ATTEMPT
------------------------------------
`reference_id = sha256(subscription_id|action_type|attempt_no)[:40]` — the same
rule as A-009, for the same reason. On resume, an action whose reference_id is
already in the ledger is not re-executed. Without that, resuming would send a
customer a second copy of a message they already received, and the ledger would
show two attempts where one happened.

WHY THE FALLBACK RATE IS COUNTED PER ARM
-----------------------------------------
The control calls no model, so its fallback rate is structurally zero. Pooling the
two would hide the only number that matters: how often the treatment arm stopped
being the treatment. A treatment fallback rate near 100% means the agent was
absent and the "lift" is a comparison of the control against itself — INC-007 in a
new place, and `RunSummary.is_valid` refuses it.
"""

import concurrent.futures as cf
import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path

from recoup.agent.llm import DETERMINISTIC, NON_MODEL_SOURCES
from recoup.assign.arms import CONTROL, TREATMENT, assign_arm
from recoup.assign.registry import decider_for
from recoup.clock import now_utc, to_iso_z
from recoup.ledger.store import Ledger
from recoup.policy.engine import PolicyEngine
from recoup.simulator.generator import generate_scenarios

#: Days simulated per subscription. The control's schedule ends at day 10 and
#: STOP-001 caps attempts at 5, so 15 leaves room for both arms to finish and
#: for a late recovery to land. DERIVED from SCHEDULE_DAYS + Recurly's 10-day
#: window; sweep range 10..30.
HORIZON_DAYS = 15

#: ASSUMPTION: a treatment arm whose actions are this often deterministic
#: fallbacks was not really running an agent. Chosen before any run: at 50% the
#: arm is half control by construction and no lift figure over it means what it
#: appears to. Sweep range 0.2..0.6.
MAX_TREATMENT_FALLBACK_RATE = 0.5


#: Rule-id prefixes meaning "this subscription is finished", as opposed to "this
#: message is wrong". The distinction decides whether a veto is worth replanning:
#: a content veto can be fixed by proposing something else, a stopping veto cannot.
STOPPING_RULE_PREFIXES = ("STOP-",)


def _is_stopping(verdict) -> bool:
    return any(
        d.rule_id.startswith(STOPPING_RULE_PREFIXES) for d in verdict.denials
    )


def reference_id(subscription_id: str, action_type: str, attempt_no: int) -> str:
    """A-009. Deterministic, so a resumed run recognises its own prior work."""
    raw = f"{subscription_id}|{action_type}|{attempt_no}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


@dataclass
class ArmStats:
    """Per arm, never pooled. See the module docstring."""

    subscriptions: int = 0
    actions_proposed: int = 0
    actions_sent: int = 0
    actions_vetoed: int = 0
    replans: int = 0
    model_decided: int = 0
    fallbacks: int = 0
    recovered: int = 0
    recovered_paise: int = 0
    spend_paise: int = 0

    @property
    def fallback_rate(self) -> float:
        decided = self.model_decided + self.fallbacks
        return self.fallbacks / decided if decided else 0.0

    @property
    def recovery_rate(self) -> float:
        return self.recovered / self.subscriptions if self.subscriptions else 0.0


@dataclass
class RunSummary:
    run_id: str
    n: int
    seed: int
    horizon_days: int
    model_identity: dict = field(default_factory=dict)
    arms: dict = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    resumed_from: int = 0

    @property
    def invalidations(self) -> list[str]:
        """Why this run may NOT be reported as a lift figure. Empty means it may.

        A list rather than a boolean so the report can print the reasons. A run
        that fails here is reported AS FAILING — not quietly dropped, and not
        rendered as a number with a footnote.
        """
        problems = []
        for arm, stats in self.arms.items():
            s = ArmStats(**stats) if isinstance(stats, dict) else stats
            if s.subscriptions == 0:
                problems.append(f"arm {arm!r} had no subscriptions")
            elif s.actions_sent == 0:
                problems.append(
                    f"arm {arm!r} sent NOTHING across {s.subscriptions} "
                    f"subscriptions — it recovers nothing and the other arm's "
                    f"lift is an artifact (INC-007)"
                )
            if arm == TREATMENT and s.fallback_rate > MAX_TREATMENT_FALLBACK_RATE:
                problems.append(
                    f"treatment fallback rate {s.fallback_rate:.1%} exceeds "
                    f"{MAX_TREATMENT_FALLBACK_RATE:.0%} — the agent was mostly "
                    f"absent and this is a comparison of the control against itself"
                )
        return problems

    @property
    def is_valid(self) -> bool:
        return not self.invalidations


class BatchRunner:
    def __init__(
        self,
        *,
        db_path: str,
        rules_path: str,
        run_id: str,
        seed: int,
        transport,
        llm_client=None,
        checkpoint_dir: str = "runs/checkpoints",
        horizon_days: int = HORIZON_DAYS,
        concurrency: int = 1,
    ) -> None:
        self.run_id = run_id
        self.seed = seed
        self.horizon_days = horizon_days
        self.transport = transport
        self.llm_client = llm_client
        # check_same_thread=False plus an explicit lock: subscriptions run on a
        # pool, and SQLite will hand out a connection to another thread happily
        # while corrupting the hash chain if two append at once. The lock is what
        # makes prev_hash correct, not the connection flag.
        self.ledger = Ledger(db_path, check_same_thread=True) if concurrency == 1 else (
            Ledger(db_path, check_same_thread=False)
        )
        self.engine = PolicyEngine(rules_path)
        self.checkpoint = Path(checkpoint_dir) / f"{run_id}.jsonl"
        self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        self.concurrency = concurrency
        self._ledger_lock = threading.Lock()
        self._checkpoint_lock = threading.Lock()

    # ---------------------------------------------------------------- resume
    def _completed(self) -> set[str]:
        """Subscription ids this run has already finished.

        Read from the checkpoint rather than from the ledger: the ledger records
        actions, and a subscription that legitimately took no action would look
        unstarted. The checkpoint records completion, which is the question.
        """
        if not self.checkpoint.exists():
            return set()
        done = set()
        for line in self.checkpoint.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["subscription_id"])
                except (ValueError, KeyError):
                    continue  # a torn final line from a kill mid-write
        return done

    def _mark_done(self, subscription_id: str, stats: dict) -> None:
        with self._checkpoint_lock, self.checkpoint.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"subscription_id": subscription_id, "stats": stats},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            fh.flush()

    def _already_executed(self, ref: str) -> bool:
        with self._ledger_lock:
            row = self.ledger.conn.execute(
                "SELECT 1 FROM ledger WHERE json_extract(payload, '$.reference_id') = ? "
                "LIMIT 1",
                (ref,),
            ).fetchone()
        return row is not None

    def _restore_state(self, state, scenario) -> None:
        """Rebuild a subscription's state from its own ledger rows.

        Without this, a resumed subscription starts fresh and does not know its
        customer already paid — so it carries on messaging past the day the
        original run stopped. The reference_id dedupe does NOT catch that: those
        are attempts the first run never made, so they have no prior row to
        collide with, and they are written as new outreach to someone who has
        already recovered.

        Found by `test_a_partial_checkpoint_resumes_rather_than_repeating`, which
        truncates the checkpoint and expected the row count to hold. It did not:
        one extra message went out.

        The ledger is the authority here rather than the checkpoint, because the
        checkpoint is what was lost.
        """
        with self._ledger_lock:
            rows = self.ledger.conn.execute(
                "SELECT payload FROM ledger WHERE subscription_id = ? AND run_id = ?",
                (scenario.subscription_id, self.run_id),
            ).fetchall()
        for (payload,) in rows:
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            state.attempts_seen.add(int(data.get("attempt_no", 0)))
            state.spend_paise += int(data.get("cost_paise", 0))
            if data.get("recovered"):
                state.recovered_paise = scenario.amount_paise
        state.attempts = len(state.attempts_seen)

    def _append(self, row: dict) -> None:
        """Serialised. The hash chain reads prev_hash and writes hash; two
        threads interleaving there produce a chain that verify-ledger rejects."""
        with self._ledger_lock:
            self.ledger.append(row)

    # ------------------------------------------------------------------- run
    def run(self, n: int, *, progress_every: int = 25) -> RunSummary:
        scenarios = generate_scenarios(n, seed=self.seed)
        done = self._completed()
        summary = RunSummary(
            run_id=self.run_id,
            n=n,
            seed=self.seed,
            horizon_days=self.horizon_days,
            started_at=to_iso_z(now_utc()),
            resumed_from=len(done),
        )
        stats = {CONTROL: ArmStats(), TREATMENT: ArmStats()}

        # Replay prior arms' counts from the checkpoint so a resumed run reports
        # the whole batch rather than only the part after the interruption.
        for line in (
            self.checkpoint.read_text(encoding="utf-8").splitlines()
            if self.checkpoint.exists()
            else []
        ):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)["stats"]
            except (ValueError, KeyError):
                continue
            arm = rec.pop("arm", None)
            if arm in stats:
                for key, value in rec.items():
                    setattr(stats[arm], key, getattr(stats[arm], key) + value)

        pending = [s for s in scenarios if s.subscription_id not in done]
        t0 = time.time()
        completed = 0
        stats_lock = threading.Lock()

        def work(scenario):
            arm = assign_arm(scenario.customer_id, salt=str(self.seed))
            per = self._run_one(scenario, arm)
            with stats_lock:
                for key, value in per.items():
                    setattr(stats[arm], key, getattr(stats[arm], key) + value)
            self._mark_done(scenario.subscription_id, {"arm": arm, **per})
            return arm

        def report(i: int) -> None:
            rate = i / max(time.time() - t0, 1e-9)
            remaining = (len(pending) - i) / rate if rate else 0
            print(
                f"  {len(done) + i}/{n}  {rate:.2f} sub/s  "
                f"eta {remaining / 60:.0f}m  "
                f"control_sent={stats[CONTROL].actions_sent} "
                f"treatment_sent={stats[TREATMENT].actions_sent} "
                f"fallback={stats[TREATMENT].fallback_rate:.0%}",
                flush=True,
            )

        if self.concurrency <= 1:
            for scenario in pending:
                work(scenario)
                completed += 1
                if progress_every and completed % progress_every == 0:
                    report(completed)
        else:
            # Concurrency is bounded by MEASUREMENT, not by guesswork: the
            # provider returned `429 too many concurrent requests` at width 8 and
            # above on 2026-09-02, so OllamaLLM.OBSERVED_CONCURRENCY_LIMIT is 7
            # and the caller passes something under it.
            with cf.ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                futures = [pool.submit(work, s) for s in pending]
                for future in cf.as_completed(futures):
                    future.result()  # re-raise rather than losing it in the pool
                    completed += 1
                    if progress_every and completed % progress_every == 0:
                        report(completed)

        summary.finished_at = to_iso_z(now_utc())
        summary.arms = {arm: asdict(s) for arm, s in stats.items()}
        return summary

    def _run_one(self, scenario, arm: str) -> dict:
        """One subscription across the horizon. Returns its own counts."""
        counts = dict(
            subscriptions=1, actions_proposed=0, actions_sent=0, actions_vetoed=0,
            replans=0, model_decided=0, fallbacks=0, recovered=0,
            recovered_paise=0, spend_paise=0,
        )
        state = _State(scenario, arm)
        self._restore_state(state, scenario)
        decider = decider_for(arm, client=self.llm_client)
        start = now_utc()

        for day in range(self.horizon_days):
            if state.recovered_paise > 0 or state.opted_out:
                break
            now = start + timedelta(days=day)
            context = {
                "day_offset": day,
                "amount_paise": scenario.amount_paise,
                "reason_code": scenario.reason_code,
                "is_hard_decline": scenario.is_hard_decline,
                "customer_name": "there",
            }

            action = decider.propose(state, context, now=now)
            if action is None:
                continue
            counts["actions_proposed"] += 1

            verdict = self.engine.evaluate(action, state, now=now)
            if not verdict.allowed:
                counts["actions_vetoed"] += 1
                # A STOP-class veto cannot be replanned around. "You have made
                # five attempts" is not fixable with different copy or a different
                # template, and asking the model to try costs a call to be told
                # the same thing. Measured on a 12-subscription dry run: 60 of 94
                # treatment proposals were vetoed and every one was replanned,
                # almost all on STOP-001.
                if _is_stopping(verdict):
                    break
                if arm == TREATMENT and hasattr(decider, "replan"):
                    action = decider.replan(action, verdict, state, context, now=now)
                    if action is None:
                        continue
                    counts["replans"] += 1
                    verdict = self.engine.evaluate(action, state, now=now)
                    if not verdict.allowed:
                        continue
                else:
                    continue

            if action.action_type != "send_message":
                continue

            if action.model_source in NON_MODEL_SOURCES:
                counts["fallbacks"] += 1
            elif action.model_source:
                counts["model_decided"] += 1

            ref = reference_id(scenario.subscription_id, action.action_type, action.attempt_no)
            if self._already_executed(ref):
                continue  # resumed onto work this run already did

            result = self.transport.execute(action, {**context, "reference_id": ref,
                 "subscription_id": scenario.subscription_id, "scenario": scenario})
            counts["actions_sent"] += 1
            counts["spend_paise"] += result.cost_paise
            state.attempts_seen.add(action.attempt_no)
            state.attempts = len(state.attempts_seen)
            state.spend_paise += result.cost_paise

            self._append({
                "run_id": self.run_id,
                "ts": to_iso_z(now),
                "event_type": "action.executed",
                "subscription_id": scenario.subscription_id,
                "customer_id": scenario.customer_id,
                "arm": arm,
                "transport": self.transport.name,
                # A DICT, not a JSON string. `Ledger.append` canonicalises the
                # payload itself, so pre-encoding it stores a JSON string inside
                # a JSON string — and `json_extract(payload, '$.reference_id')`
                # then matches nothing, so the resume dedupe silently never
                # fires and every resumed subscription is re-executed. Found by
                # planting a mid-run kill; the double encoding was invisible
                # until something tried to read a field back out.
                "payload": {
                    "reference_id": ref,
                    "action_type": action.action_type,
                    "channel": action.channel,
                    "attempt_no": action.attempt_no,
                    "dlt_template_id": action.dlt_template_id,
                    "model_source": action.model_source,
                    "cost_paise": result.cost_paise,
                    "recovered": result.recovered,
                    "provider_ref": result.provider_ref,
                },
            })

            if result.recovered:
                state.recovered_paise = scenario.amount_paise
                counts["recovered"] = 1
                counts["recovered_paise"] = scenario.amount_paise

        return counts


class _State:
    """The mutable per-subscription state both arms read.

    Not `SubscriptionState`: that one is rebuilt from ledger rows by replay and
    carries a different contract. This is the in-flight version the deciders and
    the policy engine see during a run.
    """

    def __init__(self, scenario, arm: str) -> None:
        self.subscription_id = scenario.subscription_id
        self.customer_id = scenario.customer_id
        self.arm = arm
        self.attempts_seen: set[int] = set()
        self.attempts = 0
        self.spend_paise = 0
        self.opted_out = False
        self.recovered_paise = 0
        self.ptp_date = None
        self.messages_today = 0
        self.whatsapp_optin = True


__all__ = [
    "ArmStats", "BatchRunner", "DETERMINISTIC", "HORIZON_DAYS",
    "MAX_TREATMENT_FALLBACK_RATE", "RunSummary", "reference_id",
]
