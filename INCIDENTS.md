# INCIDENTS

Live build log. Entries are written **when the thing happens**, not reconstructed
afterwards. Timestamps are IST (UTC+05:30) because that is the clock the build ran on;
everything inside the system itself is UTC.

Nothing here is edited to look better in hindsight. Failures that were my own fault are
recorded as my own fault.

---

## INC-001 — The ledger accused itself of tampering

**2026-08-29 19:47 IST** · severity: high (silent, would have surfaced on camera) · status: fixed

**What happened**

Task 3 shipped `Ledger.append()` and `compute_hash()` with a hash-chained, append-only
store. All eight tests passed. A code review question — *does `compute_hash(prev, row)`
project correctly when handed a full row out of `rows()`, which is a different shape than
what `append()` passes in?* — turned out to have a bad answer.

`append()` hashed the row via `row.get("payload")`, which is `None` when the key is absent,
but *stored* the column via `row.get("payload", {})`, which is `{}`. So a row appended
without a `payload` key was hashed as `null` and persisted as `{}`.

On read-back, `rows()` parses the column and returns `{}`. Recomputing the hash then yields
a different digest than the one stored. That row can never verify. Not once, not ever.

**Why it mattered more than it looks**

`verify_chain()` reports this as `hash mismatch at seq N`. That is the exact message the
ledger emits when someone has tampered with a row. There is no way, from the output, to tell
a self-inflicted projection bug from an actual attack.

The intended demo is running `recoup verify-ledger` on camera and reading out the head hash.
The failure mode was: one webhook lands without a payload, the chain reports tampering, and
the thing being demonstrated as an integrity guarantee is the thing that breaks.

**How it was found**

Not by the test suite. The eight Task 3 tests all constructed rows through a `_row()` helper
that always set `payload`, so the divergent shape was never exercised. It was found by a
reviewer asking whether two callers with different input shapes could disagree.

**Fix**

Both callers now go through a single `_material(row)` projection, which normalises a missing
payload to `{}`. `append()` writes its columns *from that projection* rather than from the
caller's dict, so the hashed bytes and the stored bytes come from the same object. The two
paths cannot diverge by construction; it is no longer a convention that has to hold.

Commit `ce577e1`.

**What was added so it cannot come back**

- Round-trip tests over six row shapes — missing payload, explicit `None` optionals, nested
  dicts, non-ASCII — each asserting a row read back out of `rows()` rehashes to its stored hash
- A golden-hash pin: a fixed row asserted against a literal 64-char digest
- A frozen `_HASHED_FIELDS` tuple pin

**Second finding, from testing the fix**

Verifying that the golden pin could actually fail, by swapping two entries in
`_HASHED_FIELDS`, showed the hash *did not change*. `canonical_json` sorts keys, so field
**order** is not load-bearing — only membership is. The source comment claimed otherwise
("Fields hashed, in this order"), which would have misled anyone reasoning about the chain
rule later. Comment corrected.

A pin test that is never watched failing is an assumption wearing a test's clothes.

**Lesson kept**

A test helper that only ever builds one row shape tests one row shape. The bug lived in the
gap between what the helper produced and what the system would actually receive.

---

## INC-002 — A commit message that claimed a property the code did not have

**2026-08-29 22:31 IST** · severity: medium (no runtime defect; a false claim, pushed) · status: fixed

**What happened**

Task 5 changed webhook dedupe from keyed-on-arrival to keyed-on-completion, so that only a
`processed` event counts as a duplicate. The reasoning given, in commit `16b10ca` and in
`DECISION.md` A-014, was that this stops events being lost when the process crashes with jobs
still in the in-memory queue.

It does not, and the reasoning was wrong on a point of fact about how Razorpay behaves.

Redelivery only happens when Razorpay did **not** receive a 2xx. The ordering is: record the
id, enqueue, ACK, worker runs, mark processed. The crash being defended against happens
*after* the ACK — so Razorpay considers the event delivered and will never send it again.
Nothing arrives to trigger the re-enqueue that `status='received'` was built to enable.

The window redelivery genuinely covers is between the INSERT and the ACK: a few
milliseconds, and largely the same window in which the row was never committed either. As a
crash-recovery mechanism it was close to worthless.

**Why this is logged as an incident and not a design note**

Nothing broke at runtime. What was wrong is the claim, and the claim was already pushed to a
public repository in a commit message. The code did roughly the right thing for a stated
reason that did not hold, which means anyone reading the commit — including me, later — would
have believed the hole was closed.

A wrong explanation attached to correct-looking code is harder to catch than a bug, because
it reads as considered. This project's entire argument is that its claims are checkable, so a
commit message asserting a property the system lacks is exactly the failure it cannot afford.

**How it was found**

Code review. The reviewer traced the actual ordering of record → enqueue → ACK → crash and
pointed out that the redelivery the design depended on would never arrive. Not by a test —
every test passed, because the tests exercised redelivery directly rather than asking whether
redelivery would ever happen.

**Fix**

`seen_events` now stores the raw body, and `sweep_unfinished()` re-enqueues every row still
marked `received` at startup, before the server binds its socket. Recovery is performed by us
from the durable record, not requested from Razorpay. The row was already being written; it
simply was never read back.

This also repairs the *rejection* recorded in A-014. Declining to build a durable job queue
is now correct rather than merely convenient: `seen_events` already is one. Without the sweep
it was only a record that work had been lost.

Commit `191bb19`. `DECISION.md` A-014 carries a dated correction rather than a rewrite.

**Verification**

Not simulated. A server process was started, sent four webhooks, ACKed all four, then killed
outright with `taskkill /F`. Restarted against the same database:

```
=== boot 1 ===
  RECOVERED_ON_BOOT=0
  sent evt_crash_0..3: 202 {'accepted': True, 'duplicate': False, 'redelivered': False}
>>> taskkill /F. Razorpay already ACKed all 4. <<<
=== boot 2, same database ===
  RECOVERED_ON_BOOT=4  ->  ALL BACK
```

**Lesson kept**

The tests proved the mechanism worked when triggered. Nobody had tested whether the trigger
would ever fire. A mechanism verified only from the inside is an assumption about the outside
world, and this one was wrong.

---

## INC-003 — Pre-freeze audit of the simulator: four findings

**2026-08-30 20:53 IST** · severity: high (freezing would have made all four permanent) · status: fixed

**Why this audit happened**

Two arithmetic/provenance errors had already been found in `curve.py` and `generator.py` —
a 100× unit error on the SMS channel multiplier, and a reason mix summing to 1.1000. Task 10
freezes `simulator/` and tags it, after which corrections stop being cheap and start being a
claim that the file has not moved. So the files were re-read against `PARAMS.md` on the
assumption that a third error existed.

Four did.

### F-1 · A swept parameter that nothing read — **the serious one**

`residual_bucket_is_soft` was registered as an `ASSUMPTION` with a sweep range of 0–30% and
**implemented nowhere**. No code read it.

Task 23b sweeps every parameter marked `ASSUMPTION`. It would have varied this one across its
declared range, observed an identical result at every point, and recorded it as **insensitive**
— manufacturing evidence of robustness for a parameter that had never been wired up. In the
one analysis whose entire job is to find where the result is fragile, that is a false negative
produced by the analysis itself.

Fixed: it is now `residual_hard_fraction`, read by `generate_scenarios`. `unread_assumptions()`
fails any swept `ASSUMPTION` that no constant implements.

Two related registry gaps surfaced from the same check: `channel_multiplier_sms` and
`channel_multiplier_whatsapp` were swept assumptions naming **no constant at all** — they are
entries inside `CHANNEL_MULTIPLIER`, and the registry had no way to say so. The sweep would
have had nothing to move. The registry now supports `constant_key`.

### F-2 · The provenance scanner was blind to whole types

`unregistered_constants()` checked `int | float | dict | list | tuple`. It did not check
`set` or `frozenset` — and `HARD_DECLINE_CODES` is a frozenset. The scan was blind to exactly
the shape one of the real parameters has. It happened to be registered anyway, which is luck
rather than coverage.

A scan that reports clean while unable to see a category is worse than no scan: it
manufactures confidence. Fixed, with a parametrised test over every parameter-shaped type.

The scan was also structurally unable to see numbers written *inside* function bodies —
`p *= 0.9` would have been invisible. `unregistered_literals()` now walks the AST for those.
None exist today; the check exists so none appear.

### F-3 · `PARAMS.md` had drifted from the registry

`PARAMS.md` is the artifact a judge reads. The registry is what the code runs. Nothing kept
them in step, and Task 9 registered **six** generator parameters that `PARAMS.md` described
nowhere — including `self_recovery_rate_soft` and `_hard`, the numbers that define the
counterfactual the entire lift claim is measured against.

Every test passed throughout, because they only ever checked the registry against itself.

Fixed: `PARAMS.md` now documents all seventeen, and a test matches every registry key against
the document by exact key.

### F-4 · Two sources may be measuring the same decline twice

`recovery_probability` multiplies `DAY_OFFSET_CURVE` by `ATTEMPT_DECAY`. Baremetrics reports
recovery by day offset *within a dunning sequence*, so its later days are also its later
attempts; Churnkey reports incremental recovery by email index. Both encode "a later contact
recovers less", and multiplying them may discount that decline twice.

Neither source states how its dimensions relate, so this cannot be settled from the published
figures. Recorded as **A-016** in `DECISION.md`: it becomes an explicit swept parameter,
`attempt_decay_compounding`, defaulting to **1.0 — full compounding** — because that lowers
modelled recovery in both arms and therefore claims less.

### Also corrected

`PARAMS.md` said recovery falls "~3x" between day 7 and day 15. The measured ratio is
**2.727**. Rounding a load-bearing structural fact up to the next whole number is a small
overstatement of exactly the kind that gets checked.

**How these were found**

By a line-by-line audit against `PARAMS.md`, prompted by two prior errors in the same files
and by the freeze making them permanent. F-1 and F-2 were found by writing checks for the
checkers rather than by re-reading the parameters. The parameters themselves were, on this
pass, correct.

**Lesson kept**

Every finding here is the same shape as the five before it: **the guard sat fractionally
outside the path the failure takes.** The provenance scan could not see frozensets. The sweep
registry could not see dict members. The registry tests never looked at the document. Two of
these were in machinery written *specifically* to catch this class of error.

The audit that works is not "re-read the numbers" — the numbers were fine. It is "ask what
each check cannot see."

---

## 🔒 FREEZE RECORD — the simulator, 2026-08-30 21:05 IST

Not an incident. Recorded here because `INCIDENTS.md` is the live build log, and this is the
moment the ordering claim became checkable rather than asserted.

| | |
|---|---|
| `sha256(simulator/)` | `4cb02cb7ea9ad140e051c2de0ae6683d0c0bb80d4b55c0386f8f6cb0028a4e14` |
| Tag | `sim-freeze-v1` → `c25471a` |
| Tagged | 2026-08-30 21:05:22 +0530 |
| Parameters locked | 17 — **4 MEASURED, 10 ASSUMPTION, 3 DERIVED/DEFINITIONAL** |

**`src/recoup/agent/` did not exist at the moment of the freeze**, in the working tree or
anywhere in history:

```
$ git log --all --diff-filter=A -- src/recoup/agent/   →   0 commits
```

That is the claim, and it is now enforced three ways rather than remembered: a filesystem
check and a git-history check in `tests/test_build_order.py`, and an ordering job in CI that
fails the build if any commit adds a file under `agent/` before the commit that added
`PARAMS.lock.json`.

**The drift gate was verified to bite** before being trusted. One comment line appended to
`curve.py`:

```
SIMULATOR DRIFT: simulator/ has changed since the freeze.
  locked:  4cb02cb7ea9ad140e051c2de0ae6683d0c0bb80d4b55c0386f8f6cb0028a4e14
  current: e56cb61a694460eeff85ef6e51dfb4a9d94460e7f6c08973aedc3dc304c74900
exit=1
```

and exit 0 after reverting.

**The tag is deliberately not pushed.** It stays local until the build is further along, so
it can still be moved if a genuine correction is needed. A pushed tag that later has to move
is worse than an unpushed one — the point of the tag is that it did not move.

**Worth saying plainly:** 10 of 17 parameters are `ASSUMPTION`. That is the honest
description of this simulator, it is on the face of `SIMULATOR_FREEZE.md`, and it is why the
sensitivity sweep in Task 23b is not optional.

> **Superseded by INC-004.** The hash recorded above, `4cb02cb7…`, was computed with a
> platform-dependent file ordering and is **not reproducible off Windows**. The corrected
> hash is `a45ffdec3b83fab5dd7ec452a23b5d1e22565002c08d7c0b070a5f765f6eaee5`. The original
> figure is left here rather than edited, because a freeze record that quietly restates its
> own hash is worth nothing.

---

## INC-004 — The freeze hash was not reproducible on any machine but mine

**2026-08-31 · severity: high (the freeze claim was false for every third party) · status: fixed**

**What happened**

CI failed on three consecutive commits — `c25471a`, `95b8a9c`, `e8cc909` — with:

```
SIMULATOR DRIFT: simulator/ has changed since the freeze.
  locked:  4cb02cb7ea9ad140e051c2de0ae6683d0c0bb80d4b55c0386f8f6cb0028a4e14
  current: a45ffdec3b83fab5dd7ec452a23b5d1e22565002c08d7c0b070a5f765f6eaee5
make: *** [Makefile:22: verify-sim] Error 1
```

Nothing had changed. A fresh clone had byte-identical files of identical sizes.

**Cause**

`hash_simulator_dir()` iterated `sorted(paths)`. `PurePath.__lt__` compares `_str_normcase`,
which is **case-insensitive on Windows and case-sensitive on POSIX**. With `PARAMS.md`
sitting beside `curve.py` and `__init__.py`, the two platforms enumerate the same files in
different orders:

```
Windows : __init__.py, curve.py, generator.py, PARAMS.md, provenance.py
POSIX   : PARAMS.md, __init__.py, curve.py, generator.py, provenance.py
```

Identical bytes, different iteration order, different digest. Both values were reproduced
locally by re-running the hash under each ordering.

**Why this is worse than a red build**

The freeze exists so that *someone else* can recompute the hash and confirm the simulator has
not moved. A hash reproducible only on the machine that produced it is not evidence of
anything — it is a number in a document. Any judge cloning the repository and running
`verify-sim` would have been told the simulator had been tampered with.

There is a sharper irony. Two days earlier I deliberately normalised line endings in this
same function, reasoning explicitly about cross-platform reproducibility, and wrote a test
for it. I checked one axis of portability and never asked what the other one was.

**Fix**

Sort by the relative path as a POSIX string, compared byte-for-byte, rather than by `Path`
comparison. Corrected hash `a45ffdec3b83…`, confirmed to reproduce in an independent clone.
The lock and `SIMULATOR_FREEZE.md` were rewritten and `sim-freeze-v1` moved.

**Moving the tag was possible only because it had not been pushed.** That was a deliberate
choice at freeze time — "a pushed tag that later has to move is worse than an unpushed one" —
and it is the reason this cost a re-tag rather than a rewritten public history.

**What was added**

* A test asserting the hashed files are in byte-sorted relative-path order.
* A test pinning the exact expected order, against the discriminating case (an uppercase
  name, an underscore name, and lowercase names in one directory).
* A test that, on Windows, asserts the naive ordering *differs* from the fixed one — so if
  the discriminating filenames ever disappear, the test says it has gone blind rather than
  passing silently.

**How it was found — and how it should have been**

By CI, and reported to Gajanand by email. Not by me: I ran the local suite, saw green, and
reported the block complete without ever opening the CI result. The local suite could not
have caught this, since on Windows the lock and the computation agreed with each other — but
`test_the_repository_lock_verifies_if_it_exists` would have failed on the Linux runner too,
so the signal existed and I did not look at it.

**Lesson kept**

Two, and the second is the important one.

1. Any hash over a *set* of files must fix the ordering explicitly. Sorting paths is not
   ordering; it is asking the filesystem's collation rules for an opinion.
2. **"Tests pass locally" is not "the build is green."** Reporting a block complete without
   checking CI is reporting on a proxy. Check the artifact — which is the rule this build
   has been applying to code all week, and I did not apply it to my own reporting.
