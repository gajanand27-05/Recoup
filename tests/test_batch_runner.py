"""The batch runner: resumability, idempotence, and per-arm accounting.

The two defects this file exists for were both found by planting rather than by
reading, and both are recorded at the assertions that now cover them:

1. The payload was **double-encoded** — `json.dumps()`d by the runner and
   canonicalised again by `Ledger.append`. `json_extract(payload, '$.reference_id')`
   then matched nothing, so the resume dedupe silently never fired and a resumed
   run would have re-executed every subscription it had already done. Invisible
   until something read a field back out.

2. Replanning against a STOP-class veto is futile. "You have made five attempts"
   is not fixable with different copy, and a 12-subscription dry run spent 60 of
   94 treatment proposals learning that — at ~2.5s per model call, most of a batch.
"""

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from recoup.assign.arms import CONTROL, TREATMENT
from recoup.batch.runner import (
    MAX_TREATMENT_FALLBACK_RATE,
    ArmStats,
    BatchRunner,
    RunSummary,
    reference_id,
)
from recoup.execute.sim import SimTransport

RULES = "src/recoup/policy/rules.yaml"


class _PlanningLLM:
    """Returns a well-formed proposal. Its CONTENT is never what is asserted."""

    name = "fake-planner-1"

    def __init__(self):
        self.calls = 0

    def classify_reply(self, text, today):  # pragma: no cover - wrong role
        raise AssertionError("the planner must not use the reply path")

    def propose_action(self, system, prompt):
        self.calls += 1
        return {
            "action_type": "send_message",
            "template_id": "TPL_RECOUP_WA_001",
            "hours_from_now": 0,
            "variables": {"name": "there", "amount": "499"},
            "rationale": "test",
        }


def _runner(tmp_path, client=None, **kw):
    return BatchRunner(
        db_path=str(tmp_path / "b.db"),
        rules_path=RULES,
        run_id=kw.pop("run_id", "t"),
        seed=kw.pop("seed", 7),
        transport=SimTransport(seed=7),
        llm_client=client or _PlanningLLM(),
        checkpoint_dir=str(tmp_path / "cp"),
        **kw,
    )


def _refs(db_path) -> list[str]:
    """reference_ids of ACTION rows only.

    `outcome.recovered` rows carry the same reference_id as the action that
    caused them — deliberate linkage, so a recovery can be traced to the message
    that produced it. The uniqueness invariant is therefore "one action.executed
    per reference_id", not "one row per reference_id".
    """
    conn = sqlite3.connect(str(db_path))
    try:
        return [
            json.loads(r[0])["reference_id"]
            for r in conn.execute(
                "SELECT payload FROM ledger WHERE event_type = 'action.executed'"
            )
        ]
    finally:
        conn.close()


# --- reference_id -------------------------------------------------------------


def test_reference_id_is_deterministic_and_scoped():
    a = reference_id("sub_1", "send_message", 1)
    assert a == reference_id("sub_1", "send_message", 1)
    assert a != reference_id("sub_1", "send_message", 2)
    assert a != reference_id("sub_2", "send_message", 1)
    assert len(a) == 40


# --- the payload must be READABLE, not just written ---------------------------


def test_the_reference_id_can_be_read_back_out_of_the_ledger(tmp_path):
    """DEFECT 1. The runner used to json.dumps() the payload and Ledger.append
    canonicalised it again, producing a JSON string inside a JSON string.
    Everything looked right — rows were written, the chain verified — and
    `json_extract(payload, '$.reference_id')` matched nothing, so the resume
    dedupe never fired.

    Asserting the row was written is not enough. The field has to be readable
    by the query that the dedupe actually uses.
    """
    runner = _runner(tmp_path)
    runner.run(6, progress_every=0)

    refs = _refs(tmp_path / "b.db")
    assert refs, "no rows written"
    assert all(len(r) == 40 for r in refs), f"reference_ids are malformed: {refs[:3]}"

    # The exact query the dedupe uses, not a re-implementation of it.
    conn = sqlite3.connect(str(tmp_path / "b.db"))
    try:
        found = conn.execute(
            "SELECT COUNT(*) FROM ledger "
            "WHERE json_extract(payload, '$.reference_id') = ?",
            (refs[0],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert found >= 1, (
        "json_extract cannot see reference_id — the payload is double-encoded and "
        "the resume dedupe would silently never fire"
    )


# --- resumability -------------------------------------------------------------


def test_re_invocation_adds_nothing(tmp_path):
    runner = _runner(tmp_path)
    first = runner.run(8, progress_every=0)
    before = _refs(tmp_path / "b.db")

    again = _runner(tmp_path)
    second = again.run(8, progress_every=0)
    after = _refs(tmp_path / "b.db")

    assert after == before, "re-invocation wrote more rows"
    assert len(after) == len(set(after)), "duplicate reference_ids"
    assert second.resumed_from == first.n


def test_a_partial_checkpoint_resumes_rather_than_repeating(tmp_path):
    """Simulates the kill: run some, truncate the checkpoint, run again."""
    runner = _runner(tmp_path)
    runner.run(10, progress_every=0)
    full = _refs(tmp_path / "b.db")

    lines = runner.checkpoint.read_text(encoding="utf-8").splitlines()
    runner.checkpoint.write_text("\n".join(lines[:4]) + "\n", encoding="utf-8")

    resumed = _runner(tmp_path)
    resumed.run(10, progress_every=0)
    after = _refs(tmp_path / "b.db")

    assert len(after) == len(set(after)), "resume produced duplicate outreach"
    assert set(full) <= set(after), "resume lost rows written before the interruption"
    assert len(after) == len(full), (
        "resume re-executed subscriptions whose checkpoint lines were lost — the "
        "ledger dedupe should have caught them even though the checkpoint did not"
    )


def test_a_torn_checkpoint_line_does_not_crash_the_resume(tmp_path):
    """A kill mid-write leaves a partial JSON line. That must be skipped, not
    raise — otherwise the interruption that resume exists for prevents resume."""
    runner = _runner(tmp_path)
    runner.run(6, progress_every=0)
    with runner.checkpoint.open("a", encoding="utf-8") as fh:
        fh.write('{"subscription_id": "sub_tor')  # torn

    resumed = _runner(tmp_path)
    resumed.run(6, progress_every=0)  # must not raise
    refs = _refs(tmp_path / "b.db")
    assert len(refs) == len(set(refs))


# --- per-arm accounting -------------------------------------------------------


def test_both_arms_act(tmp_path):
    """INC-007's assertion at the batch level."""
    summary = _runner(tmp_path).run(24, progress_every=0)
    control = ArmStats(**summary.arms[CONTROL])
    treatment = ArmStats(**summary.arms[TREATMENT])
    assert control.subscriptions > 0 and treatment.subscriptions > 0
    assert control.actions_sent > 0, "control sent nothing"
    assert treatment.actions_sent > 0, "treatment sent nothing"


def test_a_model_backed_run_records_no_fallbacks(tmp_path):
    summary = _runner(tmp_path).run(16, progress_every=0)
    treatment = ArmStats(**summary.arms[TREATMENT])
    assert treatment.model_decided > 0
    assert treatment.fallback_rate == 0.0


def test_a_stubbed_run_is_invalid_rather_than_merely_worse(tmp_path):
    """A stub produces sendable actions, so the batch completes and yields a
    number. The refusal has to be explicit."""
    from recoup.agent.llm import StubLLM

    summary = _runner(tmp_path, client=StubLLM()).run(16, progress_every=0)
    treatment = ArmStats(**summary.arms[TREATMENT])
    assert treatment.actions_sent > 0, "the stub still sends — that is the danger"
    assert treatment.fallback_rate == 1.0
    assert not summary.is_valid
    assert any("fallback rate" in p for p in summary.invalidations)


def test_an_arm_that_sends_nothing_invalidates_the_run():
    summary = RunSummary(run_id="r", n=10, seed=1, horizon_days=15, arms={
        CONTROL: ArmStats(subscriptions=5, actions_sent=0).__dict__,
        TREATMENT: ArmStats(subscriptions=5, actions_sent=20, model_decided=20).__dict__,
    })
    assert not summary.is_valid
    assert any("INC-007" in p for p in summary.invalidations)


def test_a_healthy_run_is_valid():
    summary = RunSummary(run_id="r", n=10, seed=1, horizon_days=15, arms={
        CONTROL: ArmStats(subscriptions=5, actions_sent=20).__dict__,
        TREATMENT: ArmStats(
            subscriptions=5, actions_sent=20, model_decided=19, fallbacks=1
        ).__dict__,
    })
    assert summary.is_valid, summary.invalidations


def test_the_fallback_ceiling_is_a_stated_constant():
    """A threshold chosen after seeing a run is not a threshold."""
    assert 0.0 < MAX_TREATMENT_FALLBACK_RATE < 1.0


# --- ledger integrity ---------------------------------------------------------


def test_every_row_carries_a_transport(tmp_path):
    _runner(tmp_path).run(8, progress_every=0)
    conn = sqlite3.connect(str(tmp_path / "b.db"))
    try:
        transports = {r[0] for r in conn.execute("SELECT transport FROM ledger")}
    finally:
        conn.close()
    assert transports == {"sim"}, transports


def test_every_row_carries_an_arm(tmp_path):
    _runner(tmp_path).run(8, progress_every=0)
    conn = sqlite3.connect(str(tmp_path / "b.db"))
    try:
        arms = {r[0] for r in conn.execute("SELECT arm FROM ledger")}
    finally:
        conn.close()
    assert arms <= {CONTROL, TREATMENT} and arms, arms


def test_no_row_records_a_charge(tmp_path):
    """D-030 at the batch level: not 'the planner cannot propose one' but
    'nothing that happened was one'."""
    _runner(tmp_path).run(12, progress_every=0)
    conn = sqlite3.connect(str(tmp_path / "b.db"))
    try:
        types = {
            json.loads(r[0])["action_type"]
            for r in conn.execute(
                "SELECT payload FROM ledger WHERE event_type = 'action.executed'"
            )
        }
    finally:
        conn.close()
    assert "charge" not in types
    assert types <= {"send_message"}, types


def test_the_chain_verifies_after_a_concurrent_run(tmp_path):
    """Concurrency reads prev_hash and writes hash. Two threads interleaving
    there produce a chain verify-ledger rejects, and the run would be lost."""
    from recoup.ledger.verify import verify_chain

    runner = _runner(tmp_path, concurrency=4)
    runner.run(24, progress_every=0)
    from recoup.ledger.store import Ledger

    result = verify_chain(Ledger(str(tmp_path / "b.db")))
    assert result.ok, getattr(result, "error", result)


def test_concurrency_produces_the_same_rows_as_sequential(tmp_path, tmp_path_factory):
    """If ordering changed the outcome, the run would not be reproducible."""
    seq_dir = tmp_path_factory.mktemp("seq")
    con_dir = tmp_path_factory.mktemp("con")
    _runner(seq_dir, concurrency=1, seed=11, run_id="s").run(16, progress_every=0)
    _runner(con_dir, concurrency=4, seed=11, run_id="s").run(16, progress_every=0)
    assert sorted(_refs(seq_dir / "b.db")) == sorted(_refs(con_dir / "b.db"))


# --- the horizon --------------------------------------------------------------


def test_a_recovered_subscription_stops_being_messaged(tmp_path):
    summary = _runner(tmp_path).run(40, progress_every=0)
    for arm in (CONTROL, TREATMENT):
        stats = ArmStats(**summary.arms[arm])
        if stats.recovered:
            assert stats.actions_sent < stats.subscriptions * 15, (
                f"arm {arm} kept messaging across the whole horizon despite "
                f"{stats.recovered} recoveries"
            )


@pytest.mark.parametrize("now", [datetime(2026, 9, 2, 5, 0, tzinfo=UTC)])
def test_the_runner_never_calls_datetime_now_at_a_call_site(now):
    """All timestamps go through recoup.clock. A naive datetime here would be
    hashed into ledger rows in the wrong format."""
    import inspect

    from recoup.batch import runner as mod

    source = inspect.getsource(mod)
    assert "datetime.now(" not in source, "call recoup.clock.now_utc() instead"


# --- the round trip: what the batch WRITES must be what the eval READS ----------


def _replayed(db_path, run_id="t"):
    """Read the run back the way the report does, not the way the writer does."""
    import sqlite3

    from recoup.ledger.replay import replay

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = []
        for r in conn.execute("SELECT * FROM ledger WHERE run_id = ?", (run_id,)):
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            rows.append(d)
    finally:
        conn.close()
    return replay(rows), rows


def test_replay_can_see_the_recoveries_the_batch_recorded(tmp_path):
    """THE DEFECT THIS EXISTS FOR.

    The runner first recorded recovery as a `recovered: true` flag inside the
    `action.executed` payload. `replay()` reads recovery ONLY from a separate
    `outcome.recovered` event, so it reported zero recoveries for every
    subscription — while 247 rows in a live run said otherwise.

    Both arms would then have shown a 0% recovery rate, and the lift would have
    come out exactly 0.00 pp with a tight interval: a clean-looking null result
    rather than an error. Nothing raised. The suite was green.

    Asserting the runner's own counters is not enough — those were right the
    whole time. The assertion has to cross the boundary.
    """
    summary = _runner(tmp_path).run(60, progress_every=0)
    states, rows = _replayed(tmp_path / "b.db")

    counted = sum(ArmStats(**s).recovered for s in summary.arms.values())
    assert counted > 0, "no recoveries in this cohort; the test proves nothing"

    replayed = sum(1 for s in states.values() if s.recovered_paise > 0)
    assert replayed == counted, (
        f"the runner counted {counted} recoveries and replay found {replayed}. "
        f"The eval reads replay, so the report would show {replayed}."
    )


def test_the_run_emits_the_event_type_replay_reads(tmp_path):
    """Named explicitly, so deleting the emitter fails here rather than silently
    zeroing the headline."""
    _runner(tmp_path).run(60, progress_every=0)
    _, rows = _replayed(tmp_path / "b.db")
    kinds = {r["event_type"] for r in rows}
    assert "action.executed" in kinds
    assert "outcome.recovered" in kinds, (
        f"only {sorted(kinds)} were written; replay() reads recovery from "
        f"'outcome.recovered' and would report a 0% rate for both arms"
    )


def test_views_built_from_the_run_carry_non_zero_recovery(tmp_path):
    """One step further: the projection lift.py actually consumes."""
    from recoup.eval.views import LiftView

    _runner(tmp_path).run(60, progress_every=0)
    states, _ = _replayed(tmp_path / "b.db")
    views = [
        LiftView.from_state(s, amount_paise=49900)
        for s in states.values()
        if s.arm is not None
    ]
    assert views, "no views could be built from the run"
    assert any(v.recovered_paise > 0 for v in views), (
        "every view reports zero recovered — the lift would be 0.00 pp in both arms"
    )
    assert any(v.spend_paise > 0 for v in views), "every view reports zero spend"


def test_a_lift_computed_from_the_run_is_not_structurally_zero(tmp_path):
    """End to end: runner -> ledger -> replay -> view -> lift.

    A lift of exactly 0.00 with both rates at zero is the signature of a broken
    pipeline, not of an ineffective agent. This distinguishes them.
    """
    from recoup.eval.lift import compute_lift
    from recoup.eval.views import LiftView

    _runner(tmp_path).run(80, progress_every=0)
    states, rows = _replayed(tmp_path / "b.db")
    views = [
        LiftView.from_state(s, amount_paise=49900)
        for s in states.values()
        if s.arm is not None
    ]
    result = compute_lift(views, run_id="t", ledger_rows=rows, bootstrap_iterations=200)

    assert not (result.control.rate == 0 and result.treatment.rate == 0), (
        "both arms recovered nothing — that is a pipeline failure wearing the "
        "clothes of a null result"
    )
