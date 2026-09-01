"""recoup — live demo. Runs the whole sequence with narration.

    python scripts/demo.py            # full run, pauses between sections
    python scripts/demo.py --fast     # no pauses
    python scripts/demo.py --only 3   # one section

WHAT THIS DEMO CLAIMS, AND WHAT IT DOES NOT
-------------------------------------------
It shows the **measuring instrument and the safety layer**, and that they were
built and frozen before the thing they measure.

It does **not** show a recovery-rate lift. The batch runner (Task 22) is not
built, so there is no number yet. Saying otherwise would be the one thing that
actually damages the submission — every guard in this repository exists to stop
exactly that kind of claim.

Open with: "I'll show you the instrument first, because the number is only worth
what the instrument is worth."
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PY = sys.executable
PAUSE = True


def h(title: str, subtitle: str = "") -> None:
    print("\n" + "=" * 74)
    print(f"  {title}")
    if subtitle:
        print(f"  {subtitle}")
    print("=" * 74)


def say(line: str = "") -> None:
    print(f"   {line}" if line else "")


def run(cmd: list[str], cwd: Path = REPO) -> subprocess.CompletedProcess:
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = (result.stdout + result.stderr).rstrip()
    if out:
        print(out)
    print(f"[exit {result.returncode}]")
    return result


def beat() -> None:
    if PAUSE:
        input("\n   -- enter to continue --")
    else:
        time.sleep(0.2)


# ---------------------------------------------------------------- 1
def section_1_frozen() -> None:
    h("1. The simulator is frozen, and the freeze is checkable",
      "The thing that decides whether the agent wins was locked before the agent existed.")
    run([PY, "tasks.py", "verify-sim"])
    say()
    say("Now I break it. One comment line appended to the response curve:")

    curve = REPO / "src/recoup/simulator/curve.py"
    original = curve.read_text(encoding="utf-8")
    curve.write_text(original + "\n# drift\n", encoding="utf-8", newline="")
    try:
        run([PY, "tasks.py", "verify-sim"])
        say()
        say("Exit 1. CI runs this on every push, so drift fails the build.")
    finally:
        curve.write_text(original, encoding="utf-8", newline="")
    run([PY, "tasks.py", "verify-sim"])
    beat()


# ---------------------------------------------------------------- 2
def section_2_ordering() -> None:
    h("2. The instrument was built BEFORE the thing it measures",
      "A tag's date can be set to anything. The pushed history cannot.")

    freeze = subprocess.run(
        ["git", "log", "--all", "--diff-filter=A", "--format=%h %ai", "--", "PARAMS.lock.json"],
        cwd=REPO, capture_output=True, text=True).stdout.strip().splitlines()
    agent = subprocess.run(
        ["git", "log", "--all", "--diff-filter=A", "--format=%h %ai", "--", "src/recoup/agent/"],
        cwd=REPO, capture_output=True, text=True).stdout.strip().splitlines()

    say(f"simulator frozen : {freeze[-1] if freeze else 'not yet'}")
    say(f"agent/ first added: {agent[-1] if agent else 'does not exist yet'}")
    say()
    say("--diff-filter=A finds the commit that ADDED each path, so it is not")
    say("fooled by a file created and later deleted. CI enforces the ordering.")
    beat()


# ---------------------------------------------------------------- 3
def section_3_policy() -> None:
    h("3. The policy engine vetoes the agent — THE demo moment",
      "An LLM prompted to respect limits is a system with no limits.")

    from recoup.ledger.replay import SubscriptionState
    from recoup.models import Action
    from recoup.policy.engine import PolicyEngine

    engine = PolicyEngine(str(REPO / "src/recoup/policy/rules.yaml"))
    now = datetime(2026, 9, 1, tzinfo=UTC)
    state = SubscriptionState(subscription_id="sub_demo", customer_id="cust_demo",
                              arm="treatment")

    def act(body: str) -> Action:
        return Action(
            action_type="send_message", channel="whatsapp", body=body,
            send_at=datetime(2026, 9, 1, 14, 0, tzinfo=UTC), attempt_no=1,
            cost_paise=12, wa_template_category="UTILITY",
            dlt_template_id="TPL_001", dlt_template_approved=True,
            body_matches_registered_template=True,
        )

    clean = "Your payment of Rs 499 could not be processed. Pay here: {link}"
    say("A compliant message:")
    say(f'  "{clean}"')
    v = engine.evaluate(act(clean), state, now=now)
    say(f"  -> allowed={v.allowed}")

    say()
    say("Now the model reaches for persuasion. Reasonable marketing copy:")
    drift = "Payment failed. Don't lose your 40% loyalty discount, upgrade now!"
    say(f'  "{drift}"')
    v = engine.evaluate(act(drift), state, now=now)
    say(f"  -> allowed={v.allowed}")
    for d in v.denials:
        say()
        say(f"  {d.rule_id}  [{d.rule_class}]")
        say(f"  {d.detail}")
        say(f"  source: {d.source_url}")
    say()
    say("In India that is a regulatory reclassification, not a style note.")
    say("Promotional content in a service message forfeits Service-Implicit")
    say("status, and with it 24x7 delivery and DND exemption.")
    say()
    say("The agent does not know that. The policy engine does, and it sits")
    say("OUTSIDE the agent, so the agent cannot argue with it.")
    beat()


# ---------------------------------------------------------------- 4
def section_4_rules_are_data() -> None:
    h("4. The rules are data, not code",
      "Edit the YAML. Touch no Python. Watch the verdict move.")

    from recoup.ledger.replay import SubscriptionState
    from recoup.models import Action
    from recoup.policy.engine import PolicyEngine

    rules = REPO / "src/recoup/policy/rules.yaml"
    original = rules.read_text(encoding="utf-8")
    now = datetime(2026, 9, 1, tzinfo=UTC)

    state = SubscriptionState(subscription_id="sub_demo", customer_id="c", arm="treatment")
    state.attempts_seen = {1, 2}

    action = Action(
        action_type="send_message", channel="whatsapp",
        body="Your payment could not be processed. Pay here: {link}",
        send_at=datetime(2026, 9, 1, 14, 0, tzinfo=UTC), attempt_no=3, cost_paise=12,
        dlt_template_id="TPL_001", dlt_template_approved=True,
        body_matches_registered_template=True,
    )

    say("Customer has had 2 attempts. The cap in rules.yaml is 5.")
    v = PolicyEngine(str(rules)).evaluate(action, state, now=now)
    say(f"  -> allowed={v.allowed}")

    say()
    say('Now I edit ONE LINE of YAML:  "state.attempts < 5"  ->  "state.attempts < 1"')
    rules.write_text(
        original.replace('predicate: "state.attempts < 5"', 'predicate: "state.attempts < 1"'),
        encoding="utf-8", newline="",
    )
    try:
        v = PolicyEngine(str(rules)).evaluate(action, state, now=now)
        say(f"  -> allowed={v.allowed}  denials={v.rule_ids}")
        say()
        say("No Python changed. The compliance surface is auditable without")
        say("reading code, and every predicate is validated at load — a typo in")
        say("a rarely-hit rule fails at startup, not halfway through a batch.")
    finally:
        rules.write_text(original, encoding="utf-8", newline="")
    beat()


# ---------------------------------------------------------------- 5
def section_5_ledger() -> None:
    h("5. Every number is recomputable, and tampering is visible",
      "An append-only hash chain, plus an external anchor for what the chain cannot see.")

    from recoup.ledger.store import Ledger

    work = REPO / "runs" / "demo"
    if work.exists():
        shutil.rmtree(work)
    db = work / "demo.db"
    lg = Ledger(str(db))
    for i in range(5):
        lg.append({
            "run_id": "run-demo", "ts": f"2026-09-01T10:0{i}:00Z",
            "event_type": "action.executed", "subscription_id": f"sub_{i}",
            "customer_id": f"cust_{i}", "arm": "treatment", "transport": "sim",
            "payload": {"channel": "whatsapp", "cost_paise": 12, "attempt_no": 1},
        })
    head = lg.head_hash()
    anchor = work / "run-demo.head"
    anchor.write_text(json.dumps(
        {"run_id": "run-demo", "head_hash": head, "rows_checked": 5}), encoding="utf-8")
    lg.conn.close()

    say("5 rows written. Head hash committed to an anchor file.")
    run([PY, "-m", "recoup.cli", "--db", str(db), "verify-ledger",
         "--expect-head-file", str(anchor)])

    say()
    say("Now I tamper with row 3, the way someone with file access would:")
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("DROP TRIGGER ledger_no_update")
    conn.execute("UPDATE ledger SET payload = '{\"channel\":\"sms\"}' WHERE seq = 3")
    conn.commit()
    conn.close()
    run([PY, "-m", "recoup.cli", "--db", str(db), "verify-ledger"])
    say()
    say("Exit 1, and it names the row. Note the database itself refuses")
    say("UPDATE and DELETE — I had to drop the trigger first.")
    shutil.rmtree(work, ignore_errors=True)
    beat()


# ---------------------------------------------------------------- 6
def section_6_aa() -> None:
    h("6. The instrument was validated before it was trusted",
      "Both arms run the identical policy. If it reports lift here, it manufactures lift.")

    from recoup.eval.aa import AA_N_PER_ARM, AA_SEED, run_preregistered

    say(f"Seed {AA_SEED} and N={AA_N_PER_ARM} were written into EXPERIMENT.md")
    say("and PUSHED before this ran. The git timestamp is the evidence.")
    say()
    r = run_preregistered()
    say(f"arm A: {r.successes_a}/{r.n_per_arm}    arm B: {r.successes_b}/{r.n_per_arm}")
    say(f"difference : {r.diff * 100:+.2f} pp")
    say(f"95% CI     : [{r.ci_low * 100:+.2f}, {r.ci_high * 100:+.2f}] pp")
    say(f"p-value    : {r.p_value:.4f}   PASSED={r.passed}")
    say()
    say("Said precisely: a pass rules out harness bias larger than about")
    say("6.23 percentage points. It does NOT establish an unbiased harness.")
    beat()


# ---------------------------------------------------------------- 7
def section_7_limits() -> None:
    h("7. What this does NOT show",
      "Said first, before anyone has to ask.")
    say("* There is no lift number yet. The batch runner is Day 5.")
    say("* The agent's LLM jobs are built but NOT exercised — no API key,")
    say("  and there is deliberately no stub fallback, because a stand-in")
    say("  producing output that reads like a real run is the failure mode")
    say("  every guard here exists to prevent.")
    say("* 10 of 17 simulator parameters are ASSUMPTIONS with declared sweep")
    say("  ranges. That is on the face of SIMULATOR_FREEZE.md.")
    say("* The counterfactual — whether a customer would have paid anyway — is")
    say("  assumed, not measured. Nothing published measures it.")
    say()
    say("All of that is in README.md under Limitations, written before")
    say("anyone asked for it.")
    print("\n" + "=" * 74)


SECTIONS = [
    section_1_frozen, section_2_ordering, section_3_policy, section_4_rules_are_data,
    section_5_ledger, section_6_aa, section_7_limits,
]


def main() -> int:
    global PAUSE
    parser = argparse.ArgumentParser(description="recoup live demo")
    parser.add_argument("--fast", action="store_true", help="no pauses")
    parser.add_argument("--only", type=int, help="run one section (1-7)")
    args = parser.parse_args()
    PAUSE = not args.fast

    print("\n  recoup — post-halt subscription payment recovery")
    print("  Razorpay AI Buildathon 2026, Track 03")
    print("\n  Showing the instrument first: the number is only worth what the")
    print("  instrument is worth.")

    chosen = [SECTIONS[args.only - 1]] if args.only else SECTIONS
    for section in chosen:
        section()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
