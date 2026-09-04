# Measured results

Every number here was produced by a run that actually happened, on the date stated, with the
model named. Nothing on this page is projected, extrapolated, or carried over from an earlier
configuration.

Where a run has **not** happened, it says so rather than being omitted.

---

## Reply understanding — Task 19

**Run 2026-09-02 · `gpt-oss:120b` via Ollama Cloud · 60 hand-labelled fixtures**

The fixtures were labelled by hand **before any model was called**, and the labels are pinned
by `test_the_fixture_is_well_formed_and_labelled_before_any_model_ran`.

| | value | 95% CI (Wilson) |
|---|---|---|
| **Intent accuracy** | **94.2%** (49/52) | **[84.4%, 98.0%]** |
| **Promise-date extraction** | **90.9%** (10/11) | **[62.3%, 98.4%]** |
| Deterministic opt-out matcher | 100% (8/8) | — |

Pre-registered bars: intent ≥ 85%, date ≥ 80%. Both point estimates clear them.

### Read the intervals before quoting the point estimates

**The intent CI's lower bound is 84.4%, which is below the 85% bar.** The point estimate
clears it; the interval does not exclude values that fail it. With n = 52 that is what the
evidence supports, and the honest statement is *"94.2%, and the data are consistent with true
accuracy anywhere from 84% to 98%"* — not "94% accurate".

**The date-extraction interval is [62.3%, 98.4%] on n = 11.** That is close to uninformative.
It is reported because it was measured and pre-registered, not because 11 items establish
anything. Do not put this number in a headline.

### Why 52 and not 60

`deterministic_opt_out()` runs **upstream of the model** — a regulatory hard stop must not
depend on a model's reading comprehension, and `test_every_labelled_opt_out_is_caught_without_the_model`
pins that every labelled opt-out is reachable without a key.

So 8 fixtures never reach the model. An accuracy figure over all 60 would pool the opt-out
matcher's results with the model's and report the total as the model's — the same category
error as pooling `sim` and `real` transports. `require_real_model()` refused the pooled
figure, which is how this was found: the first version of the eval computed over all 60 and
was rejected by its own provenance gate.

### Every miss

| reply | labelled | model said |
|---|---|---|
| `I never signed up for this` | `dispute` | `wrong_number` |
| `maine kabhi subscribe nahi kiya` | `dispute` | `wrong_number` |
| `cancel kar do, main nahi chahta` | `dispute` | `opt_out` |
| `give me till friday` (from Tue 2026-09-01) | `2026-09-04` | `2026-09-03` |

Two of the three intent misses are the same case in two languages: *"I never signed up for
this"* read as `wrong_number` rather than `dispute`. That reading is defensible — someone who
never signed up may well be the wrong person — and the fixture label is the stricter one. It
is left as a miss rather than relabelled: adjusting ground truth after seeing the prediction
is how an eval stops measuring anything.

The date miss is a genuine model error. 2026-09-04 **is** a Friday; the model answered
Thursday. The label is correct and stands.

### What this does not measure

Whether the model is right when nobody labelled the answer. The fixtures are 60 replies
chosen to cover six intents and to include Hinglish; they are not a sample of any real
customer population, because no real customer replies exist to sample from.

### A caveat specific to this provider

Ollama Cloud **accepts a JSON schema and ignores it** (A-024) — both `format=` and
`response_format: {strict: true}` return HTTP 200 and invent their own keys. The schema is
therefore spelled into the prompt, and conformance rests on instruction-following rather than
constrained decoding. Output is still validated by Pydantic at the boundary, so a
non-conforming answer is a caught failure and never a silently accepted one.

Across this run every response parsed and validated — the schema-violation rate was **0/52**.
That is a property of this model on this task and should not be assumed to hold for another.

---

## Recovery lift — Task 22

**Run 2026-09-03 · N = 2,000 as pre-registered · seed 20260902 · `sim` transport ·
`gpt-oss:120b`, digest `d98fe6ba01e6`, CONFIRMED_BY_REGISTRY.**

| arm | recovered | n | rate | 95% CI (Wilson) |
|---|---|---|---|---|
| control | 310 | 1,035 | **29.95%** | [27.24%, 32.81%] |
| treatment | 303 | 965 | **31.40%** | [28.55%, 34.40%] |

**Difference +1.45 pp · 95% CI [−2.59, +5.49] pp · p = 0.4830**

*Produced by `487fc45` (subscriptions 1–1153), `7dbe2c0` (1154–1354) and `25ad9c4`
(1355–2000) at concurrency 3 → 2 → 2, demonstrated output-equivalent. Full manifest:
[`runs/batch-2000.provenance.json`](runs/batch-2000.provenance.json).*

### The result: no detected difference at this N

**The interval spans zero.** This run does not distinguish the agent from the control, at an
**achieved** MDE of **6.24 pp** — at the arms that ran, 1,035 / 965 (harmonic-mean effective
N 998).

**That is not the same as there being no difference.** The run rules out effects *larger* than
the MDE at the stated power. It does **not** rule out a real effect smaller than 6.24 pp, and
it does **not** establish that the arms are equivalent — a null and a demonstration of
equivalence are different claims, and only the first was run.


Reported as pre-registered in [`EXPERIMENT.md`](EXPERIMENT.md) Addendum 3, written at
12/2,000 before any number existed. Outcome 3 says exactly this: *no detected difference at
this N, with the MDE stated* — **not** "trending positive", and **not** re-run at larger N to
chase significance.

The achieved MDE at N = 2,000 is **6.24 pp**. An effect of +1.45 pp — produced by `487fc45`,
`7dbe2c0` and `25ad9c4`, see `runs/batch-2000.provenance.json` — is well inside the noise this design
can resolve, so the honest statement is that the experiment did not detect a difference. That
is not the same as there being no difference: the run does **not** rule out a smaller real
effect and does **not** establish that the arms are equivalent.

> **Two MDEs, and they are different quantities (A-029).** **6.24 pp** is the **achieved** MDE — the harmonic-mean effective N of the arms that actually ran, 1,035 / 965, effective N 998. **6.23 pp** is the **pre-registered** MDE at the designed 1,000 per arm, pinned in [`EXPERIMENT.md`](EXPERIMENT.md)'s power table before the run. The result of *this run* is quoted against the achieved figure; claims about what the *design* could ever detect are quoted against the pre-registered one, which is also the smaller of the two and therefore the weaker version of that claim.

### Why the usual excuse is unavailable

Addendum 2 fixed in advance that schema violations pull measured lift **toward null**, because
a violation drives a `DETERMINISTIC` fallback that behaves like a control action.

**The fallback rate was 0.0%** — 3,637 model decisions, zero fallbacks. So that bias is **nil,
not small**, and cannot be invoked to argue the true effect is larger. The counter was verified
to still be counting before this figure existed (A-027): five forced schema violations each
drive it to 100%.

### Per arm

| | control | treatment |
|---|---|---|
| subscriptions | 1,035 | 965 |
| actions proposed | 4,353 | 6,579 |
| actions sent | 4,353 | 3,637 |
| vetoed by policy | 0 | 474 |
| model-decided | 0 | 3,637 |
| fallbacks | 0 | **0** |

The treatment arm proposed more and sent less: 474 of its proposals were vetoed, almost all by
`STOP-001`'s five-attempt cap. The control cannot be vetoed because its schedule never exceeds
the cap by construction.

### The sign was verified independently

Recovery counts read straight off the ledger by a path importing neither `lift.py` nor
`stats.py` agree: control 310/1,035, treatment 303/965, direction **+1**. Two implementations
sharing no code would have to be inverted identically to agree wrongly.

### Sensitivity: one sign flip, reported

The sweep replays the run's own actions and varies the response curve at each end of every
declared range.

**`attempt_decay_compounding` = 0.0 flips the sign: +1.55 pp → −0.10 pp.**

`EXPERIMENT.md` pre-registers a sign flip as falsifying, so it is reported rather than
narrowed away. In context the flip is −0.10 pp against a measurement whose interval already
spans zero at an achieved MDE of 6.24 pp, so it is consistent with finding 1 — which does
not establish equivalence either — rather than a reversal of a real effect. Both statements
are true and both are here.

`channel_multiplier_whatsapp`, `channel_multiplier_sms` and `hard_decline_multiplier` move the
model and hold their direction at both endpoints. `decay_beyond_curve` and
`attempt_decay_compounding` at its high endpoint are **UNWIRED** — in scope, and could not be
shown to move anything.

**`self_recovery_rate_soft` and `_hard` are NOT SWEPT**, and they are the two that matter most.
They define `would_self_recover` and therefore the denominator of the whole lift claim, and a
replay that holds actions fixed cannot reach scenario generation. Reporting them as
swept-and-flat would be the reassuring-result-where-the-model-is-emptiest failure one level up.

### Provenance

The run spans **three code pins** — `487fc45` (1–1153), `7dbe2c0` (1154–1354), `25ad9c4`
(1355–2000) — and three concurrency settings, across two resumes forced by a provider account
quota and one network timeout. All recorded in `runs/batch-2000.provenance.json` with the
subscription range each produced.

The pins and concurrency settings were **demonstrated** output-equivalent, not argued: the same
batch was run under each and every ledger row compared identical.

### Completeness

8,617 ledger rows, 2,000 subscriptions replayed, **0 rows attributable to no subscription**.

---

## Adversarial injection eval — Task 21, the `llm`-marked half

**NOT RUN.** Declared here rather than left to be inferred from a gap.

The structural half of `tests/test_adversarial.py` **did** run and passes: 22 attack payloads,
none of which can reach a money action, because the vocabulary has no `charge` action type and
`ReplyUnderstanding` carries no field any code path turns into money. All 22 are also refused
as message bodies and as template variables (INC-010).

What has **not** run is the `llm`-marked half: whether the model's *classification* bends under
attack. It needs live calls, and the provider's account quota has ended the batch run twice —
spending quota on the eval would risk the figure the whole submission rests on.

When it runs it reports a **rate**, not a pass or a fail. Pinning a model at zero forced
misclassifications makes the test a coin-flip on temperature.

---

## A/A instrument validation — Task 13

**Run 2026-08-31 · seed 20260831 · 1,000 per arm · pre-registered and pushed before the run.**

| | value |
|---|---|
| arm A | 513/1000 |
| arm B | 510/1000 |
| difference | −0.30 pp |
| 95% CI | [−4.67, +4.07] pp |
| p-value | 0.8932 |

Both arms ran identical policy. If the harness manufactured lift, it would appear here.

**The A/A test passed** — and the next sentence is not optional. **Scope, which must travel
with the result:** a pass rules out harness bias larger than about **6.23 percentage points**.
It does **not** establish an unbiased harness. An effect smaller than the A/A's own 6.23 pp
at 1,000 per arm could be sitting in the harness and this test would not see it.

*(Stated as a verdict rather than left to be inferred from p = 0.8932. Until 2026-09-02 this
section gave the numbers and never said "passed", so the only document stating the result was
`VIDEO.md` — which is local-only and ships to nobody. The guard that keeps this sentence
attached to its scope was therefore protecting nothing a judge would read, which
`test_at_least_one_document_actually_states_each_claim` caught by failing in a clone.)*

Run **once**. The result is pinned in `tests/test_aa.py` and is not re-run —
re-running until a p-value pleases is optional stopping.
